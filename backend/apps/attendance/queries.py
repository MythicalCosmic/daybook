"""Read functions of attendance, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

Contracts other packages call (docs/PLAN-OWNER.md §3.10, §11.3):

    period_summary(company, start, end, *, branch_ids) -> dict[int, PeriodAttendance]   (H)
    summary(company, start, end, *, branch_ids, membership=None, compare=None) -> dict (N)
    day_board(company, day, *, branch_ids, now=None) -> dict                             (N)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.attendance import clock, conf
from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    MemberSchedule,
    ShiftSwap,
    WorkShift,
)
from apps.companies.models import Branch, Company
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm, suspended_ids
from apps.timeoff.models import Holiday, TimeOff

STAFF_STATUSES = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)
# Board states (contracts.ATTENDANCE_TODAY plus nothing else).
IN, LATE, NOT_YET, ABSENT, OFF = "in", "late", "not_yet", "absent", "off"


# People ---------------------------------------------------------------------------------


def staff(company: Company, *, branch_ids: list[int] | None) -> QuerySet[Membership]:
    """Approved (and suspended) people whose branches meet `branch_ids`."""
    people = Membership.objects.for_company(company).filter(status__in=STAFF_STATUSES)
    return scope.restrict(people, branch_ids, field="branches")


def staff_at(company: Company, branch_id: int | None, *, branch_ids) -> QuerySet[Membership]:
    """`staff`, narrowed to people working at `branch_id` (home branch or one of theirs)."""
    people = staff(company, branch_ids=branch_ids)
    if branch_id is not None:
        people = people.filter(Q(home_branch_id=branch_id) | Q(branches=branch_id)).distinct()
    return people


def person(member: Membership | None) -> dict | None:
    if member is None:
        return None
    return {"id": member.pk, "name": member.full_name or str(member.user)}


def person_card(member: Membership) -> dict:
    """A person with what the dashboard shows next to their name."""
    user = member.user
    photo = user.photo.url if getattr(user, "photo", None) else None
    return {
        "id": member.pk,
        "name": member.full_name or str(user),
        "photo_url": photo,
        "position": {"id": member.position_id, "name": member.position.name}
        if member.position_id
        else None,
        "home_branch": {"id": member.home_branch_id, "name": member.home_branch.name}
        if member.home_branch_id
        else None,
        "status": member.status,
    }


def managers_for(company: Company, branch_id: int | None, *, exclude: int | None = None):
    """Approved `attendance.manage` holders who see `branch_id` (everyone with every branch
    when it is None), and the branch's own manager."""
    holders = members_with_perm(company, Perm.ATTENDANCE_MANAGE).select_related(
        "role", "user", "company"
    )
    found = []
    for holder in holders.prefetch_related("branches"):
        if holder.pk == exclude:
            continue
        if scope.allows(scope.branch_ids(holder), branch_id):
            found.append(holder)
    return found


def is_suspended_on(member: Membership, day: date) -> bool:
    return member.status == Membership.Status.SUSPENDED and (
        member.suspended_until is None or day <= member.suspended_until
    )


def on_leave(member: Membership, day: date) -> TimeOff | None:
    """The member's approved time off covering `day`, if any."""
    return (
        TimeOff.objects.filter(
            membership=member,
            status=TimeOff.Status.APPROVED,
            first_day__lte=day,
            last_day__gte=day,
        )
        .order_by("pk")
        .first()
    )


def leave_days(company: Company, start: date, end: date, member_ids) -> dict[int, dict[date, int]]:
    """{member id: {day: time off id}} of approved time off between `start` and `end`."""
    rows = TimeOff.objects.filter(
        company=company,
        status=TimeOff.Status.APPROVED,
        first_day__lte=end,
        last_day__gte=start,
        membership_id__in=list(member_ids),
    ).order_by("first_day", "pk")
    found: dict[int, dict[date, int]] = defaultdict(dict)
    for time_off in rows:
        for day in clock.days(max(time_off.first_day, start), min(time_off.last_day, end)):
            found[time_off.membership_id].setdefault(day, time_off.pk)
    return found


def holidays(company: Company, start: date, end: date) -> dict[date, str]:
    return dict(
        Holiday.objects.filter(company=company, date__range=(start, end)).values_list(
            "date", "name"
        )
    )


# Shifts and records ---------------------------------------------------------------------


def open_record(member: Membership) -> AttendanceRecord | None:
    return (
        AttendanceRecord.objects.filter(membership=member, status=AttendanceRecord.Status.OPEN)
        .select_related("shift", "branch")
        .first()
    )


def current_shift(member: Membership, now: datetime, *, settings=None) -> WorkShift | None:
    """The live shift a check-in at `now` belongs to: one whose window (from
    `early_check_in_minutes` before its start until its end) holds `now`. Overnight shifts
    match by that window, never by calendar day. The nearest start wins."""
    settings = settings or conf.get_settings(member.company)
    early = timedelta(minutes=settings.early_check_in_minutes)
    candidates = (
        WorkShift.objects.working()
        .filter(membership=member, starts_at__lte=now + early, ends_at__gt=now)
        .select_related("branch", "position")
    )
    return min(candidates, key=lambda shift: abs(shift.starts_at - now), default=None)


def next_shift(member: Membership, now: datetime) -> WorkShift | None:
    return (
        WorkShift.objects.working()
        .filter(membership=member, starts_at__gt=now)
        .select_related("branch", "position")
        .order_by("starts_at")
        .first()
    )


def shifts_between(
    company: Company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    branch_id: int | None = None,
    member_id: int | None = None,
    drafts: bool = True,
) -> QuerySet[WorkShift]:
    """Shifts dated `start`..`end` in scope (cancelled ones left out; drafts only when asked)."""
    shifts = (
        WorkShift.objects.for_company(company)
        .filter(date__range=(start, end))
        .exclude(status=WorkShift.Status.CANCELLED)
        .select_related("membership__user", "branch", "position")
    )
    if not drafts:
        shifts = shifts.filter(published_at__isnull=False)
    shifts = scope.restrict(shifts, branch_ids)
    if branch_id is not None:
        shifts = shifts.filter(branch_id=branch_id)
    if member_id is not None:
        shifts = shifts.filter(membership_id=member_id)
    return shifts.annotate(
        swap_pending=Exists(
            ShiftSwap.objects.filter(shift=OuterRef("pk"), status__in=ShiftSwap.OPEN_STATUSES)
        ),
        has_record=Exists(AttendanceRecord.objects.filter(shift=OuterRef("pk"))),
    ).order_by("starts_at", "pk")


def records_between(
    company: Company, start: date, end: date, *, branch_ids: list[int] | None
) -> QuerySet[AttendanceRecord]:
    records = (
        AttendanceRecord.objects.for_company(company)
        .filter(date__range=(start, end))
        .select_related("membership__user", "membership__position", "shift", "branch")
    )
    return scope.restrict(records, branch_ids)


def eligible_for(shift: WorkShift, *, exclude_ids=(), ignore_shift_ids=()) -> QuerySet[Membership]:
    """Who may cover or claim `shift`: approved colleagues in its position (the shift's, or
    its owner's), working at its branch, not on leave that day and free (no other live
    shift that day or overlapping it). `ignore_shift_ids` lets a swap partner's own shift
    not count as busy."""
    company = shift.company
    people = Membership.objects.for_company(company).filter(status=Membership.Status.APPROVED)
    if shift.membership_id:
        people = people.exclude(pk=shift.membership_id)
    if exclude_ids:
        people = people.exclude(pk__in=list(exclude_ids))
    position_id = shift.position_id or (shift.membership.position_id if shift.membership else None)
    if position_id:
        people = people.filter(position_id=position_id)
    if shift.branch_id:
        people = people.filter(Q(branches=shift.branch_id) | Q(home_branch_id=shift.branch_id))
    busy = (
        WorkShift.objects.live()
        .filter(membership__isnull=False, company=company)
        .filter(Q(date=shift.date) | Q(starts_at__lt=shift.ends_at, ends_at__gt=shift.starts_at))
        .exclude(status=WorkShift.Status.OPEN)
        .exclude(pk__in=[shift.pk, *ignore_shift_ids])
        .values("membership_id")
    )
    away = TimeOff.objects.filter(
        company=company,
        status=TimeOff.Status.APPROVED,
        first_day__lte=shift.date,
        last_day__gte=shift.date,
    ).values("membership_id")
    return (
        people.exclude(pk__in=busy)
        .exclude(pk__in=away)
        .select_related("user", "position", "home_branch")
        .distinct()
        .order_by("first_name", "last_name", "pk")
    )


def is_eligible(shift: WorkShift, member: Membership, *, ignore_shift_ids=()) -> bool:
    return eligible_for(shift, ignore_shift_ids=ignore_shift_ids).filter(pk=member.pk).exists()


# Pending work for managers -------------------------------------------------------------


def pending_corrections(member: Membership) -> QuerySet[AttendanceCorrection]:
    rows = AttendanceCorrection.objects.for_company(member.company).filter(
        status=AttendanceCorrection.Status.PENDING
    )
    allowed = scope.branch_ids(member)
    if allowed is not None:
        rows = rows.filter(
            Q(record__branch_id__in=allowed)
            | Q(record__isnull=True, membership__home_branch_id__in=allowed)
        )
    return rows.select_related("membership__user", "record__branch", "membership__home_branch")


def pending_overtime(member: Membership) -> QuerySet[AttendanceRecord]:
    rows = AttendanceRecord.objects.for_company(member.company).filter(
        overtime_status=AttendanceRecord.Overtime.PENDING
    )
    return scope.restrict(rows, scope.branch_ids(member)).select_related(
        "membership__user", "shift", "branch"
    )


def pending_swaps(member: Membership) -> QuerySet[ShiftSwap]:
    """Swaps, covers and claims a colleague accepted that wait for a manager."""
    rows = ShiftSwap.objects.for_company(member.company).filter(status=ShiftSwap.Status.ACCEPTED)
    rows = scope.restrict(rows, scope.branch_ids(member), field="shift__branch")
    return rows.select_related(
        "shift__branch",
        "shift__membership__user",
        "other_shift",
        "requested_by__user",
        "accepted_by__user",
        "target__user",
    )


def corrections_count(member: Membership) -> int:
    return pending_corrections(member).count() + pending_overtime(member).count()


def swaps_count(member: Membership) -> int:
    return pending_swaps(member).count()


def not_in_count(member: Membership, now: datetime | None = None) -> int:
    """People whose shift today started more than the grace minutes ago and who haven't
    checked in (the sidebar badge)."""
    now = now or timezone.now()
    company = member.company
    settings = conf.get_settings(company)
    today = clock.today(company, now)
    shifts = WorkShift.objects.working().filter(
        company=company,
        date=today,
        starts_at__lte=now - timedelta(minutes=settings.grace_minutes),
        membership__status=Membership.Status.APPROVED,
    )
    shifts = scope.restrict(shifts, scope.branch_ids(member))
    shifts = shifts.exclude(
        membership_id__in=AttendanceRecord.objects.filter(company=company, date=today).values(
            "membership_id"
        )
    )
    return shifts.values("membership_id").distinct().count()


# The day board --------------------------------------------------------------------------


def day_board(
    company: Company, day: date, *, branch_ids: list[int] | None, now: datetime | None = None
) -> dict:
    """Who is in, late, not here yet, absent or off on `day`, per person, with the
    distance and flags of their check-in (trust signals), plus per-branch counts.

    In: checked in on time (checked-out people stay here, with their check-out). Late:
    checked in past the grace minutes. Not yet: a shift today without a check-in, until
    `no_show_alert_minutes` after its start. Absent: past that, or marked absent. Off: no
    shift (day off, leave, holiday, suspended).
    """
    now = now or timezone.now()
    settings = conf.get_settings(company)
    today = clock.today(company, now)
    people = list(
        staff(company, branch_ids=branch_ids).select_related("user", "position", "home_branch")
    )
    ids = [member.pk for member in people]
    shifts = list(
        WorkShift.objects.live()
        .filter(company=company, date=day, membership_id__in=ids)
        .exclude(status=WorkShift.Status.OPEN)
        .select_related("branch")
        .order_by("starts_at")
    )
    if branch_ids is not None:
        shifts = [shift for shift in shifts if shift.branch_id in branch_ids]
    records = list(
        AttendanceRecord.objects.filter(company=company, date=day, membership_id__in=ids)
        .select_related("branch", "shift")
        .order_by("check_in_at")
    )
    if branch_ids is not None:
        records = [record for record in records if record.branch_id in branch_ids]
    shift_of: dict[int, list[WorkShift]] = defaultdict(list)
    for shift in shifts:
        shift_of[shift.membership_id].append(shift)
    record_of: dict[int, list[AttendanceRecord]] = defaultdict(list)
    for record in records:
        record_of[record.membership_id].append(record)
    away = leave_days(company, day, day, ids)
    holiday = (
        Holiday.objects.filter(company=company, date=day).values_list("name", flat=True).first()
    )
    off_today = suspended_ids(company, day)
    no_show = timedelta(minutes=settings.no_show_alert_minutes)
    grace = timedelta(minutes=settings.grace_minutes)

    rows = []
    totals = defaultdict(int)
    with_shift = {shift.membership_id for shift in shifts}
    for member in people:
        member_shifts = shift_of.get(member.pk, [])
        working = [shift for shift in member_shifts if shift.status == WorkShift.Status.PLANNED]
        member_records = record_of.get(member.pk, [])
        record = _main_record(member_records)
        shift = record.shift if record and record.shift else (working[0] if working else None)
        if shift is None and member_shifts:
            shift = member_shifts[0]
        state, reason = _state(
            member,
            day,
            today,
            now,
            shift,
            record,
            working,
            away,
            holiday,
            off_today,
            grace,
            no_show,
        )
        # Outside the scope's branches and with nothing today: not part of this board.
        elsewhere = branch_ids is not None and member.home_branch_id not in branch_ids
        if member.pk not in with_shift and record is None and elsewhere:
            continue
        totals[state] += 1
        if working:
            totals["rostered"] += 1
            if record is None and working[0].starts_at + grace <= now and day == today:
                totals[LATE + "_missing"] += 1
        rows.append(
            {
                "member": person_card(member),
                "branch": _branch_ref((shift.branch if shift else None) or member.home_branch),
                "state": state,
                "reason": reason,
                "shift": shift_payload(shift, company) if shift else None,
                "record": record_payload(record, company) if record else None,
            }
        )
    order = {IN: 1, LATE: 0, NOT_YET: 2, ABSENT: 3, OFF: 4}
    rows.sort(
        key=lambda row: (
            order[row["state"]],
            row["shift"]["starts_at"] if row["shift"] else "~",
            row["member"]["name"],
        )
    )
    for key in (IN, LATE, NOT_YET, ABSENT, OFF, "rostered", LATE + "_missing"):
        totals.setdefault(key, 0)
    return {
        "date": day.isoformat(),
        "is_today": day == today,
        "now": clock.local(company, now).isoformat(),
        "holiday": holiday,
        "totals": dict(totals),
        "branches": _branch_cards(company, day, shifts, records, branch_ids),
        "people": rows,
    }


def _main_record(records: list[AttendanceRecord]) -> AttendanceRecord | None:
    """The record that tells the day: the open one, else the first attended, else any."""
    for record in records:
        if record.status == AttendanceRecord.Status.OPEN:
            return record
    for record in records:
        if record.attended:
            return record
    return records[0] if records else None


def _state(
    member, day, today, now, shift, record, working, away, holiday, off_today, grace, no_show
):
    if record is not None and record.attended:
        return (LATE if record.is_late else IN), None
    if record is not None and record.status == AttendanceRecord.Status.ABSENT:
        return ABSENT, None
    if record is not None and record.status == AttendanceRecord.Status.EXCUSED:
        return OFF, "excused"
    if member.pk in off_today or member.status == Membership.Status.SUSPENDED:
        return OFF, "suspended"
    if day in away.get(member.pk, {}) or (shift and shift.status == WorkShift.Status.LEAVE):
        return OFF, "leave"
    if not working:
        return OFF, ("holiday" if holiday else "day_off" if _has_roster(member) else "no_shift")
    first = working[0]
    if day < today or (day == today and first.starts_at + no_show <= now):
        return ABSENT, None
    if day == today and first.starts_at + grace <= now:
        return NOT_YET, "late"
    return NOT_YET, None


def _has_roster(member: Membership) -> bool:
    return hasattr(member, "work_schedule") and member.work_schedule.schedule_id is not None


def _branch_ref(branch: Branch | None) -> dict | None:
    if branch is None:
        return None
    return {"id": branch.pk, "name": branch.name, "code": branch.code}


def _branch_cards(company, day, shifts, records, branch_ids) -> list[dict]:
    branches = Branch.objects.filter(company=company, is_active=True).order_by("order", "name")
    if branch_ids is not None:
        branches = branches.filter(pk__in=branch_ids)
    cards = []
    for branch in branches:
        rostered = {
            s.membership_id
            for s in shifts
            if s.branch_id == branch.pk and s.status == WorkShift.Status.PLANNED
        }
        attended = [r for r in records if r.branch_id == branch.pk and r.attended]
        first = min((r.check_in_at for r in attended if r.check_in_at), default=None)
        cards.append(
            {
                "id": branch.pk,
                "name": branch.name,
                "code": branch.code,
                "latitude": str(branch.latitude) if branch.latitude is not None else None,
                "longitude": str(branch.longitude) if branch.longitude is not None else None,
                "geofence_m": branch.geofence_m,
                "rostered": len(rostered),
                "checked_in": len({r.membership_id for r in attended}),
                "first_check_in": clock.local(company, first).isoformat() if first else None,
            }
        )
    return cards


# Payloads -------------------------------------------------------------------------------


def shift_payload(shift: WorkShift, company: Company) -> dict:
    return {
        "id": shift.pk,
        "member_id": shift.membership_id,
        "date": shift.date.isoformat(),
        "starts_at": clock.local(company, shift.starts_at).isoformat(),
        "ends_at": clock.local(company, shift.ends_at).isoformat(),
        "start": clock.hhmm(company, shift.starts_at),
        "end": clock.hhmm(company, shift.ends_at),
        "break_minutes": shift.break_minutes,
        "minutes": shift.minutes,
        "branch": _branch_ref(shift.branch) if shift.branch_id else None,
        "position": {"id": shift.position_id, "name": shift.position.name}
        if shift.position_id
        else None,
        "status": shift.status,
        "source": shift.source,
        "published": shift.published_at is not None,
        "note": shift.note,
        "time_off_id": shift.time_off_id,
        "swap_pending": bool(getattr(shift, "swap_pending", False)),
        "has_record": bool(getattr(shift, "has_record", False)),
    }


def record_payload(record: AttendanceRecord, company: Company) -> dict:
    def iso(moment):
        return clock.local(company, moment).isoformat() if moment else None

    def text(value):
        return str(value) if value is not None else None

    return {
        "id": record.pk,
        "member_id": record.membership_id,
        "shift_id": record.shift_id,
        "date": record.date.isoformat(),
        "status": record.status,
        "check_in_at": iso(record.check_in_at),
        "check_out_at": iso(record.check_out_at),
        "in_lat": text(record.in_lat),
        "in_lng": text(record.in_lng),
        "in_accuracy_m": record.in_accuracy_m,
        "in_distance_m": record.in_distance_m,
        "out_lat": text(record.out_lat),
        "out_lng": text(record.out_lng),
        "out_accuracy_m": record.out_accuracy_m,
        "out_distance_m": record.out_distance_m,
        "branch": _branch_ref(record.branch) if record.branch_id else None,
        "in_source": record.in_source,
        "out_source": record.out_source,
        "late_minutes": record.late_minutes,
        "early_leave_minutes": record.early_leave_minutes,
        "worked_minutes": record.worked_minutes,
        "overtime_minutes": record.overtime_minutes,
        "overtime_status": record.overtime_status,
        "is_late": record.is_late,
        "flags": list(record.flags),
        "note": record.note,
        "has_photo": bool(record.in_photo),
    }


def swap_payload(swap: ShiftSwap, company: Company) -> dict:
    def iso(moment):
        return clock.local(company, moment).isoformat() if moment else None

    return {
        "id": swap.pk,
        "kind": swap.kind,
        "status": swap.status,
        "shift": shift_payload(swap.shift, company),
        "other_shift": shift_payload(swap.other_shift, company) if swap.other_shift_id else None,
        "requested_by": person(swap.requested_by),
        "target": person(swap.target) if swap.target_id else None,
        "accepted_by": person(swap.accepted_by) if swap.accepted_by_id else None,
        "note": swap.note,
        "decision_note": swap.decision_note,
        "expires_at": iso(swap.expires_at),
        "created_at": iso(swap.created_at),
        "decided_at": iso(swap.decided_at),
    }


def correction_payload(correction: AttendanceCorrection, company: Company) -> dict:
    def iso(moment):
        return clock.local(company, moment).isoformat() if moment else None

    return {
        "id": correction.pk,
        "member": person_card(correction.membership),
        "date": correction.date.isoformat(),
        "check_in_at": iso(correction.check_in_at),
        "check_out_at": iso(correction.check_out_at),
        "reason": correction.reason,
        "status": correction.status,
        "decision_note": correction.decision_note,
        "record": record_payload(correction.record, company) if correction.record_id else None,
        "created_at": iso(correction.created_at),
        "decided_at": iso(correction.decided_at),
    }


# Payroll contract -----------------------------------------------------------------------


@dataclass
class PeriodAttendance:
    """One person's attendance in a period (docs/PLAN-OWNER.md §3.10, §3.17)."""

    scheduled_days: int = 0
    attended_days: int = 0
    leave_days: int = 0
    leave_time_off_ids: list[int] = field(default_factory=list)
    absent_days: int = 0
    worked_minutes: int = 0
    approved_overtime_minutes: int = 0
    late_arrivals: int = 0
    late_minutes: int = 0
    holiday_worked_days: int = 0
    has_schedule: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def period_summary(
    company: Company, start: date, end: date, *, branch_ids: list[int] | None
) -> dict[int, PeriodAttendance]:
    """Attendance per membership id from `start` to `end` (both included), for payroll.

    Scheduled days `S` (§2.7, §3.17): the days with a published planned or leave shift when
    the person has any in the period, otherwise the days in `Company.workdays`; holidays are
    removed in both cases. Leave days are scheduled days covered by approved time off.
    Attended days are days with a check-in; absent days are scheduled days marked absent.
    """
    people = set(staff(company, branch_ids=branch_ids).values_list("pk", flat=True))
    # People who left during the period still get their days (a final payslip needs them).
    for rows in (
        scope.restrict(
            WorkShift.objects.live().filter(company=company, date__range=(start, end)), branch_ids
        ),
        scope.restrict(
            AttendanceRecord.objects.filter(company=company, date__range=(start, end)), branch_ids
        ),
    ):
        people |= set(rows.exclude(membership__isnull=True).values_list("membership_id", flat=True))
    people = sorted(people)
    days_off = holidays(company, start, end)
    workdays = set(company.workdays or [])
    plain_days = [day for day in clock.days(start, end) if day.weekday() in workdays]

    planned: dict[int, set[date]] = defaultdict(set)
    shift_leave: dict[int, dict[date, int | None]] = defaultdict(dict)
    for member_id, day, status, time_off_id in (
        WorkShift.objects.live()
        .filter(company=company, date__range=(start, end), membership_id__in=people)
        .filter(status__in=(WorkShift.Status.PLANNED, WorkShift.Status.LEAVE))
        .values_list("membership_id", "date", "status", "time_off_id")
    ):
        planned[member_id].add(day)
        if status == WorkShift.Status.LEAVE:
            shift_leave[member_id][day] = time_off_id
    away = leave_days(company, start, end, people)

    records = AttendanceRecord.objects.filter(
        company=company, date__range=(start, end), membership_id__in=people
    ).values_list(
        "membership_id",
        "date",
        "status",
        "worked_minutes",
        "overtime_minutes",
        "overtime_status",
        "is_late",
        "late_minutes",
    )
    by_member: dict[int, list[tuple]] = defaultdict(list)
    for row in records:
        by_member[row[0]].append(row)

    found: dict[int, PeriodAttendance] = {}
    for member_id in people:
        summary = PeriodAttendance(has_schedule=bool(planned.get(member_id)))
        base = planned[member_id] if summary.has_schedule else set(plain_days)
        scheduled = {day for day in base if day not in days_off}
        summary.scheduled_days = len(scheduled)
        leave = {
            day: time_off_id
            for day, time_off_id in {**shift_leave[member_id], **away.get(member_id, {})}.items()
            if day in scheduled
        }
        summary.leave_days = len(leave)
        summary.leave_time_off_ids = sorted({value for value in leave.values() if value})
        attended: set[date] = set()
        absent: set[date] = set()
        for _member, day, status, worked, overtime, overtime_status, is_late, late in by_member[
            member_id
        ]:
            if status in AttendanceRecord.ATTENDED:
                attended.add(day)
                summary.worked_minutes += worked
                if overtime_status == AttendanceRecord.Overtime.APPROVED:
                    summary.approved_overtime_minutes += overtime
                if is_late:
                    summary.late_arrivals += 1
                    summary.late_minutes += late
            elif status == AttendanceRecord.Status.ABSENT and day in scheduled and day not in leave:
                absent.add(day)
        summary.attended_days = len(attended)
        summary.absent_days = len(absent - attended)
        summary.holiday_worked_days = len({day for day in attended if day in days_off})
        found[member_id] = summary
    return found


# Analytics ------------------------------------------------------------------------------


def _percent(part: int, whole: int) -> str | None:
    if not whole:
        return None
    value = Decimal(part * 100) / Decimal(whole)
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def daily_counts(
    company: Company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    membership: Membership | None = None,
) -> dict[date, dict]:
    """Per day: people rostered, present (checked in), late and absent."""
    shifts = WorkShift.objects.working().filter(company=company, date__range=(start, end))
    records = AttendanceRecord.objects.filter(company=company, date__range=(start, end))
    shifts = scope.restrict(shifts, branch_ids)
    records = scope.restrict(records, branch_ids)
    if membership is not None:
        shifts = shifts.filter(membership=membership)
        records = records.filter(membership=membership)
    counts = {
        day: {"rostered": 0, "present": 0, "late": 0, "absent": 0} for day in clock.days(start, end)
    }
    for row in shifts.values("date").annotate(n=Count("membership", distinct=True)):
        counts[row["date"]]["rostered"] = row["n"]
    for row in (
        records.filter(status__in=AttendanceRecord.ATTENDED)
        .values("date")
        .annotate(
            n=Count("membership", distinct=True),
            late=Count("membership", filter=Q(is_late=True), distinct=True),
        )
    ):
        counts[row["date"]]["present"] = row["n"]
        counts[row["date"]]["late"] = row["late"]
    for row in (
        records.filter(status=AttendanceRecord.Status.ABSENT)
        .values("date")
        .annotate(n=Count("membership", distinct=True))
    ):
        counts[row["date"]]["absent"] = row["n"]
    return counts


def _totals(counts: dict[date, dict], records: QuerySet[AttendanceRecord]) -> dict:
    present = sum(day["present"] for day in counts.values())
    late = sum(day["late"] for day in counts.values())
    absent = sum(day["absent"] for day in counts.values())
    rostered = sum(day["rostered"] for day in counts.values())
    worked = records.filter(status__in=AttendanceRecord.ATTENDED).values_list(
        "worked_minutes", flat=True
    )
    hours = Decimal(sum(worked)) / Decimal(60)
    return {
        "present": present,
        "late": late,
        "absent": absent,
        "rostered": rostered,
        "on_time_percent": _percent(present - late, present),
        "attendance_percent": _percent(present, present + absent),
        "worked_hours": str(hours.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
    }


def summary(
    company: Company,
    start: date,
    end: date,
    *,
    branch_ids: list[int] | None,
    membership: Membership | None = None,
    compare: tuple[date, date] | None = None,
) -> dict:
    """Attendance in the analytics shape (§4): totals (present, late, absent, rostered,
    on-time and attendance percentages, worked hours), a daily series (present, late, absent,
    rostered) and a breakdown per branch. `membership` narrows it to one person."""
    counts = daily_counts(company, start, end, branch_ids=branch_ids, membership=membership)
    records = scope.restrict(
        AttendanceRecord.objects.filter(company=company, date__range=(start, end)), branch_ids
    )
    if membership is not None:
        records = records.filter(membership=membership)
    result = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "compare": None,
        "currency": company.base_currency,
        "totals": _totals(counts, records),
        "previous": None,
        "series": [{"date": day.isoformat(), **values} for day, values in counts.items()],
        "breakdown": [],
    }
    if compare is not None:
        before = daily_counts(
            company, compare[0], compare[1], branch_ids=branch_ids, membership=membership
        )
        before_records = scope.restrict(
            AttendanceRecord.objects.filter(company=company, date__range=compare), branch_ids
        )
        if membership is not None:
            before_records = before_records.filter(membership=membership)
        result["compare"] = {"from": compare[0].isoformat(), "to": compare[1].isoformat()}
        result["previous"] = _totals(before, before_records)
    branches = Branch.objects.filter(company=company, is_active=True).order_by("order", "name")
    if branch_ids is not None:
        branches = branches.filter(pk__in=branch_ids)
    for branch in branches:
        per = daily_counts(company, start, end, branch_ids=[branch.pk], membership=membership)
        result["breakdown"].append(
            {
                "key": str(branch.pk),
                "label": branch.name,
                "present": sum(day["present"] for day in per.values()),
                "late": sum(day["late"] for day in per.values()),
                "absent": sum(day["absent"] for day in per.values()),
                "rostered": sum(day["rostered"] for day in per.values()),
            }
        )
    return result


# The timesheet --------------------------------------------------------------------------

# Cell codes: present, late, absent, leave, off (no shift), holiday, excused, open (in now),
# auto (closed automatically), planned (a future shift), unscheduled.
PRESENT, CELL_LATE, CELL_ABSENT, LEAVE, CELL_OFF, HOLIDAY = (
    "present",
    "late",
    "absent",
    "leave",
    "off",
    "holiday",
)
EXCUSED, OPEN, AUTO, PLANNED, UNSCHEDULED = "excused", "open", "auto", "planned", "unscheduled"


def month_bounds(month: date) -> tuple[date, date]:
    first = month.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return first, following - timedelta(days=1)


def timesheet(
    company: Company,
    month: date,
    *,
    branch_ids: list[int] | None,
    branch_id: int | None = None,
    member_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    """People by days of a month: a coded cell per day (with minutes and the record or shift
    behind it) and each person's period totals."""
    now = now or timezone.now()
    today = clock.today(company, now)
    start, end = month_bounds(month)
    people = staff_at(company, branch_id, branch_ids=branch_ids).select_related(
        "user", "position", "home_branch"
    )
    if member_id is not None:
        people = people.filter(pk=member_id)
    people = list(people.order_by("first_name", "last_name", "pk"))
    ids = [member.pk for member in people]
    days_off = holidays(company, start, end)
    shifts: dict[tuple[int, date], WorkShift] = {}
    for shift in (
        WorkShift.objects.live()
        .filter(company=company, date__range=(start, end), membership_id__in=ids)
        .order_by("starts_at")
    ):
        shifts.setdefault((shift.membership_id, shift.date), shift)
    records: dict[tuple[int, date], AttendanceRecord] = {}
    for record in AttendanceRecord.objects.filter(
        company=company, date__range=(start, end), membership_id__in=ids
    ).order_by("check_in_at"):
        key = (record.membership_id, record.date)
        if key not in records or (record.attended and not records[key].attended):
            records[key] = record
    away = leave_days(company, start, end, ids)
    totals = period_summary(company, start, end, branch_ids=None)

    rows = []
    for member in people:
        cells = {}
        for day in clock.days(start, end):
            cells[day.isoformat()] = _cell(
                member,
                day,
                today,
                shifts.get((member.pk, day)),
                records.get((member.pk, day)),
                away,
                days_off,
            )
        summary = totals.get(member.pk, PeriodAttendance())
        overtime = sum(
            record.overtime_minutes
            for (member_key, _day), record in records.items()
            if member_key == member.pk
        )
        rows.append(
            {
                "member": person_card(member),
                "totals": summary.as_dict() | {"overtime_minutes": overtime},
                "cells": cells,
            }
        )
    return {
        "month": start.strftime("%Y-%m"),
        "days": [day.isoformat() for day in clock.days(start, end)],
        "today": today.isoformat(),
        "holidays": {day.isoformat(): name for day, name in days_off.items()},
        "people": rows,
    }


def _cell(member, day, today, shift, record, away, days_off) -> dict:
    cell = {
        "code": CELL_OFF,
        "minutes": 0,
        "late": 0,
        "record_id": None,
        "shift_id": shift.pk if shift else None,
        "flags": [],
    }
    if record is not None:
        cell["record_id"] = record.pk
        cell["flags"] = list(record.flags)
        if record.status == AttendanceRecord.Status.OPEN:
            cell["code"] = OPEN
        elif record.status == AttendanceRecord.Status.AUTO_CLOSED:
            cell["code"] = AUTO
            cell["minutes"] = record.worked_minutes
        elif record.status == AttendanceRecord.Status.CLOSED:
            cell["code"] = (
                CELL_LATE if record.is_late else (UNSCHEDULED if not record.shift_id else PRESENT)
            )
            cell["minutes"] = record.worked_minutes
            cell["late"] = record.late_minutes
        elif record.status == AttendanceRecord.Status.ABSENT:
            cell["code"] = CELL_ABSENT
        else:
            cell["code"] = EXCUSED
        if record.status == AttendanceRecord.Status.OPEN and record.is_late:
            cell["late"] = record.late_minutes
        return cell
    if day in away.get(member.pk, {}) or (shift and shift.status == WorkShift.Status.LEAVE):
        cell["code"] = LEAVE
    elif day in days_off:
        cell["code"] = HOLIDAY
    elif shift is not None and shift.status == WorkShift.Status.PLANNED:
        cell["code"] = PLANNED if day >= today else CELL_ABSENT
        cell["minutes"] = shift.minutes if day >= today else 0
    return cell


# The roster -----------------------------------------------------------------------------


def roster(
    company: Company,
    week: date,
    *,
    branch_ids: list[int] | None,
    branch_id: int | None = None,
) -> dict:
    """One week of the roster: people (with their schedule and planned minutes), every shift
    including drafts and open shifts, leave days, holidays and coverage per day."""
    start = clock.week_start(week)
    end = start + timedelta(days=6)
    people = list(
        staff_at(company, branch_id, branch_ids=branch_ids)
        .filter(status=Membership.Status.APPROVED)
        .select_related("user", "position", "home_branch", "work_schedule__schedule")
        .order_by("position__order", "first_name", "last_name", "pk")
    )
    shifts = list(shifts_between(company, start, end, branch_ids=branch_ids, branch_id=branch_id))
    ids = {member.pk for member in people}
    # People of another branch working here this week still get a row.
    extra = {s.membership_id for s in shifts if s.membership_id and s.membership_id not in ids}
    if extra:
        people += list(
            Membership.objects.filter(pk__in=extra).select_related(
                "user", "position", "home_branch", "work_schedule__schedule"
            )
        )
    minutes: dict[int, int] = defaultdict(int)
    for shift in shifts:
        if shift.membership_id and shift.status == WorkShift.Status.PLANNED:
            minutes[shift.membership_id] += shift.minutes
    away = leave_days(company, start, end, [member.pk for member in people])
    coverage = {
        day.isoformat(): {"planned": 0, "open": 0, "minutes": 0} for day in clock.days(start, end)
    }
    for shift in shifts:
        cell = coverage[shift.date.isoformat()]
        if shift.status == WorkShift.Status.OPEN:
            cell["open"] += 1
        elif shift.status == WorkShift.Status.PLANNED:
            cell["planned"] += 1
            cell["minutes"] += shift.minutes
    return {
        "week": start.isoformat(),
        "days": [day.isoformat() for day in clock.days(start, end)],
        "holidays": {day.isoformat(): name for day, name in holidays(company, start, end).items()},
        "members": [
            person_card(member)
            | {
                "schedule": _schedule_ref(member),
                "minutes": minutes.get(member.pk, 0),
                "leave": sorted(day.isoformat() for day in away.get(member.pk, {})),
            }
            for member in people
        ],
        "shifts": [shift_payload(shift, company) for shift in shifts],
        "unpublished": sum(1 for shift in shifts if shift.published_at is None),
        "coverage": coverage,
    }


def _schedule_ref(member: Membership) -> dict | None:
    assignment = getattr(member, "work_schedule", None)
    if assignment is None or assignment.schedule is None:
        return None
    return {"id": assignment.schedule_id, "name": assignment.schedule.name}


def assignments(company: Company) -> dict[int, list[int]]:
    """{schedule id: [member ids]} of approved and suspended people."""
    found: dict[int, list[int]] = defaultdict(list)
    for schedule_id, member_id in (
        MemberSchedule.objects.for_company(company)
        .filter(schedule__isnull=False, membership__status__in=STAFF_STATUSES)
        .values_list("schedule_id", "membership_id")
    ):
        found[schedule_id].append(member_id)
    return found


# The person's own views ----------------------------------------------------------------


def my_day(member: Membership, now: datetime | None = None) -> dict:
    """What the mini app's check-in card shows: today's shift (the current one, else the next
    today), the open or latest record, the branch to check in at and a state:
    off · upcoming · due · late · in · done."""
    now = now or timezone.now()
    company = member.company
    settings = conf.get_settings(company)
    today = clock.today(company, now)
    record = open_record(member)
    shift = (
        record.shift if record and record.shift else current_shift(member, now, settings=settings)
    )
    if shift is None:
        later = next_shift(member, now)
        if later is not None and later.date == today:
            shift = later
    if record is None:
        record = (
            AttendanceRecord.objects.filter(membership=member, date=today)
            .select_related("shift", "branch")
            .order_by("-check_in_at")
            .first()
        )
    if record is not None and record.status == AttendanceRecord.Status.OPEN:
        state = "in"
    elif (
        shift is not None and record is not None and record.shift_id == shift.pk and record.attended
    ):
        state = "done"
    elif (shift is not None and shift.date >= today) or (shift and shift.ends_at > now):
        early = timedelta(minutes=settings.early_check_in_minutes)
        grace = timedelta(minutes=settings.grace_minutes)
        if now < shift.starts_at - early:
            state = "upcoming"
        elif now <= shift.starts_at + grace:
            state = "due"
        else:
            state = "late"
    elif record is not None and record.attended:
        state = "done"
    else:
        state = "off"
    branch = (
        (shift.branch if shift else None)
        or (record.branch if record else None)
        or member.home_branch
    )
    upcoming = next_shift(member, now)
    if upcoming is not None and shift is not None and upcoming.pk == shift.pk:
        upcoming = (
            WorkShift.objects.working()
            .filter(membership=member, starts_at__gt=shift.starts_at)
            .select_related("branch", "position")
            .order_by("starts_at")
            .first()
        )
    return {
        "now": clock.local(company, now).isoformat(),
        "date": today.isoformat(),
        "state": state,
        "settings": {
            "require_location": settings.require_location,
            "require_photo": settings.require_photo,
            "outside_action": settings.outside_action,
            "max_accuracy_m": settings.max_accuracy_m,
            "grace_minutes": settings.grace_minutes,
        },
        "shift": shift_payload(shift, company) if shift else None,
        "branch": branch_geo(branch),
        "record": record_payload(record, company) if record else None,
        "next_shift": shift_payload(upcoming, company) if upcoming else None,
        # Open shifts still to take (ones already asked for wait for the manager).
        "open_shifts": open_shifts_for(member, now=now).filter(claimed=False).count(),
        "requests": requests_for(member).count(),
    }


def branch_geo(branch: Branch | None) -> dict | None:
    if branch is None:
        return None
    return {
        "id": branch.pk,
        "name": branch.name,
        "code": branch.code,
        "latitude": str(branch.latitude) if branch.latitude is not None else None,
        "longitude": str(branch.longitude) if branch.longitude is not None else None,
        "geofence_m": branch.geofence_m,
    }


def my_month(member: Membership, month: date, now: datetime | None = None) -> dict:
    """The person's month: a coded day each (the timesheet's cell codes) and the totals."""
    sheet = timesheet(member.company, month, branch_ids=None, member_id=member.pk, now=now)
    row = sheet["people"][0] if sheet["people"] else {"cells": {}, "totals": {}}
    return {
        "month": sheet["month"],
        "days": sheet["days"],
        "today": sheet["today"],
        "holidays": sheet["holidays"],
        "cells": row["cells"],
        "totals": row["totals"],
    }


def open_shifts_for(member: Membership, *, now: datetime | None = None) -> QuerySet[WorkShift]:
    """Published open shifts that haven't started and that `member` is eligible for."""
    now = now or timezone.now()
    shifts = (
        WorkShift.objects.live()
        .filter(company=member.company, status=WorkShift.Status.OPEN, starts_at__gt=now)
        .select_related("branch", "position")
        .order_by("starts_at")
    )
    eligible = []
    for shift in shifts[:50]:
        if is_eligible(shift, member):
            eligible.append(shift.pk)
    return (
        WorkShift.objects.filter(pk__in=eligible)
        .select_related("branch", "position")
        .annotate(
            claimed=Exists(
                ShiftSwap.objects.filter(
                    shift=OuterRef("pk"), requested_by=member, status__in=ShiftSwap.OPEN_STATUSES
                )
            )
        )
        .order_by("starts_at")
    )


def requests_for(member: Membership) -> QuerySet[ShiftSwap]:
    """Cover and swap requests waiting for `member`'s answer: named to them, or offered to
    anyone eligible when they are."""
    now = timezone.now()
    offered = ShiftSwap.objects.filter(
        company=member.company,
        status=ShiftSwap.Status.REQUESTED,
        expires_at__gt=now,
        kind__in=(ShiftSwap.Kind.COVER, ShiftSwap.Kind.SWAP),
    ).exclude(requested_by=member)
    named = offered.filter(target=member)
    anyone = [
        swap.pk
        for swap in offered.filter(target__isnull=True).select_related(
            "shift__membership", "shift__company"
        )[:50]
        if is_eligible(swap.shift, member)
    ]
    return (
        ShiftSwap.objects.filter(Q(pk__in=named.values("pk")) | Q(pk__in=anyone))
        .select_related(
            "shift__branch", "shift__position", "other_shift__branch", "requested_by__user"
        )
        .order_by("expires_at")
    )


def my_swaps(member: Membership) -> QuerySet[ShiftSwap]:
    """Requests `member` made or accepted, newest first."""
    return (
        ShiftSwap.objects.filter(company=member.company)
        .filter(Q(requested_by=member) | Q(accepted_by=member))
        .select_related(
            "shift__branch",
            "shift__position",
            "other_shift__branch",
            "requested_by__user",
            "accepted_by__user",
            "target__user",
        )
        .order_by("-created_at")
    )


# Providers for the console registries ---------------------------------------------------


def person_fields(company: Company, member_ids: list[int], now: datetime) -> dict[int, dict]:
    """`attendance` person fields: today's board state and the 30-day attendance rate."""
    today = clock.today(company, now)
    board = day_board(company, today, branch_ids=None, now=now)
    states = {row["member"]["id"]: row["state"] for row in board["people"]}
    start = today - timedelta(days=30)
    end = today - timedelta(days=1)
    rates = period_summary(company, start, end, branch_ids=None)
    found = {}
    for member_id in member_ids:
        rate = rates.get(member_id)
        expected = 0
        if rate is not None and rate.has_schedule:
            expected = rate.scheduled_days - rate.leave_days
        found[member_id] = {
            "attendance_today": states.get(member_id),
            "attendance_30d": _percent(min(rate.attended_days, expected), expected)
            if rate and expected
            else None,
        }
    return found


def branch_facts(company: Company, day: date, now: datetime, branch_ids: list[int]) -> dict:
    """`attendance` branch facts (contracts.AttendanceFacts) per branch id."""
    shifts = WorkShift.objects.working().filter(company=company, date=day, branch_id__in=branch_ids)
    records = AttendanceRecord.objects.filter(
        company=company,
        date=day,
        branch_id__in=branch_ids,
        status__in=AttendanceRecord.ATTENDED,
    )
    found = {}
    for branch_id in branch_ids:
        here = records.filter(branch_id=branch_id)
        first = here.order_by("check_in_at").values_list("check_in_at", flat=True).first()
        found[branch_id] = {
            "rostered": shifts.filter(branch_id=branch_id)
            .values("membership_id")
            .distinct()
            .count(),
            "checked_in": here.values("membership_id").distinct().count(),
            "first_check_in": clock.local(company, first).isoformat() if first else None,
        }
    return found


def company_facts(company: Company, range_, member: Membership) -> dict:
    """`attendance` portfolio facts: present and rostered today, in the caller's scope."""
    board = day_board(company, clock.today(company), branch_ids=scope.branch_ids(member))
    totals = board["totals"]
    return {"present": totals[IN] + totals[LATE], "rostered": totals["rostered"]}


def brief_section(
    company: Company, day: date, now: datetime, branch_ids: list[int] | None
) -> dict | None:
    """Today's attendance for briefings and `/today`: counts and who is late or missing."""
    board = day_board(company, day, branch_ids=branch_ids, now=now)
    totals = board["totals"]
    if not totals["rostered"] and not (totals[IN] + totals[LATE]):
        return None
    late = [row for row in board["people"] if row["state"] == LATE]
    absent = [row for row in board["people"] if row["state"] == ABSENT]
    missing = [
        row for row in board["people"] if row["state"] == NOT_YET and row["reason"] == "late"
    ]
    return {
        "present": totals[IN] + totals[LATE],
        "rostered": totals["rostered"],
        "late": [
            {
                "id": row["member"]["id"],
                "name": row["member"]["name"],
                "minutes": row["record"]["late_minutes"],
            }
            for row in late
        ],
        "absent": [{"id": row["member"]["id"], "name": row["member"]["name"]} for row in absent],
        "not_in_yet": [
            {"id": row["member"]["id"], "name": row["member"]["name"]} for row in missing
        ],
    }


def stream(member: Membership, since: datetime | None, limit: int) -> list:
    """Check-ins for the Overview activity stream, newest first, in the member's scope."""
    from django.utils.translation import gettext as _

    from apps.console.registry import StreamItem

    company = member.company
    records = AttendanceRecord.objects.filter(
        company=company, check_in_at__isnull=False
    ).select_related("membership__user", "branch")
    records = scope.restrict(records, scope.branch_ids(member))
    if since is not None:
        records = records.filter(check_in_at__gt=since)
    else:
        records = records.filter(check_in_at__gte=timezone.now() - timedelta(days=2))
    items = []
    for record in records.order_by("-check_in_at")[:limit]:
        name = record.membership.full_name or str(record.membership.user)
        where = record.branch.name if record.branch_id else ""
        if record.is_late:
            title = _("%(name)s checked in %(minutes)s min late · %(branch)s") % {
                "name": name,
                "minutes": record.late_minutes,
                "branch": where,
            }
        else:
            title = _("%(name)s checked in · %(branch)s") % {"name": name, "branch": where}
        items.append(
            StreamItem(
                at=record.check_in_at,
                kind="attendance.checked_in",
                actor=person(record.membership),
                title=title.rstrip(" ·"),
                url=f"/c/{company.pk}/attendance?date={record.date.isoformat()}&record={record.pk}",
            )
        )
    return items


def off_day_people(company: Company, day: date) -> set[int]:
    """ "Tasks follow shifts": people with a roster that week but no shift to work on `day`
    (a rostered day off). People without any shift around that day aren't affected."""
    if not company.has_feature("attendance") or not conf.get_settings(company).tasks_follow_shifts:
        return set()
    around = (
        WorkShift.objects.live()
        .filter(company=company, membership__isnull=False)
        .filter(date__range=(day - timedelta(days=6), day + timedelta(days=6)))
    )
    rostered = set(around.values_list("membership_id", flat=True))
    working = set(
        around.filter(date=day, status=WorkShift.Status.PLANNED).values_list(
            "membership_id", flat=True
        )
    )
    return rostered - working
