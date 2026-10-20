"""Business logic of attendance: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

    Settings      update_settings, save_template, remove_template
    Schedules     create_schedule, update_schedule, archive_schedule, assign_schedule
    Roster        generate_shifts, create_shift, update_shift, delete_shift, bulk_roster,
                  publish_roster
    Check-ins     check_in, check_out, check_out_now, edit_record, create_record, excuse,
                  decide_overtime
    Corrections   request_correction, decide_correction
    Swaps         request_swap, accept_swap, decline_swap, cancel_swap, claim_open_shift,
                  decide_swap, expire_swaps
    Receivers     time_off_approved, time_off_cancelled, member_left
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.attendance import clock, conf, geo, notify, queries, rules
from apps.attendance.audit_actions import AttendanceAction
from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSettings,
    MemberSchedule,
    ShiftSwap,
    ShiftTemplate,
    WorkSchedule,
    WorkScheduleDay,
    WorkShift,
)
from apps.audit import services as audit
from apps.companies.models import Branch, Company
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.uploads import sanitize_image
from apps.inbox import services as inbox
from apps.members import scope
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from apps.timeoff.models import Holiday, TimeOff

# Pulse keys (registered in hooks.py).
PULSE_BOARD = "attendance.board"
PULSE_NOT_IN = "attendance.not_in"
PULSE_ROSTER = "attendance.roster"
PULSE_SWAPS = "attendance.swaps"
PULSE_CORRECTIONS = "attendance.corrections"
PULSE_SCHEDULES = "attendance.schedules"
PULSE_SETTINGS = "attendance.settings"

# Shifts are generated from schedules this many days ahead of today.
GENERATE_DAYS = 14
# How far back a person may ask to correct a day.
CORRECTION_DAYS = 31

Source = AttendanceRecord.Source
Flag = AttendanceRecord.Flag

APPROVED_TEXT = gettext_lazy("Approved")
REJECTED_TEXT = gettext_lazy("Rejected")


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _audit(by: Membership | None, action: str, target, **details) -> None:
    audit.record(
        action,
        company_id=target.company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


ANY_BRANCH = object()


def _require(by: Membership | None, perm: Perm, branch_id=ANY_BRANCH) -> None:
    """`by` holds `perm` and, when a branch is named, sees it (a row without a branch, None,
    needs every branch); the system (`by=None`) may do anything."""
    if by is None:
        return
    if not by.has_perm(perm):
        raise PermissionDenied(_("You don't have permission to do this."))
    if branch_id is not ANY_BRANCH and not scope.allows(scope.branch_ids(by), branch_id):
        raise PermissionDenied(_("You don't have permission to do this."))


def _same_company(company: Company, *objects) -> None:
    for obj in objects:
        if obj is not None and getattr(obj, "company_id", company.pk) != company.pk:
            raise DomainError(_("That doesn't belong to this company."))


def _clean(instance) -> None:
    try:
        instance.full_clean(exclude=["company"], validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        first = next(iter(exc.message_dict.values()))[0] if hasattr(exc, "message_dict") else exc
        raise DomainError(str(first)) from exc


def _display(value):
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if hasattr(value, "pk"):
        return str(value)
    return value


def _changes(before: dict, after: dict) -> dict:
    return {
        key: [_display(before[key]), _display(after[key])]
        for key in after
        if before.get(key) != after[key]
    }


def _ensure_module(company: Company) -> None:
    if not company.has_feature("attendance"):
        raise DomainError(_("Attendance isn't switched on for this company."))


# Settings and templates ----------------------------------------------------------------

SETTINGS_FIELDS = (
    "require_location",
    "require_photo",
    "outside_action",
    "grace_minutes",
    "early_leave_grace_minutes",
    "remind_after_minutes",
    "no_show_alert_minutes",
    "auto_close_after_hours",
    "max_accuracy_m",
    "tasks_follow_shifts",
    "swaps_need_approval",
    "open_shift_claim_needs_approval",
    "pre_shift_reminder_minutes",
    "early_check_in_minutes",
    "overtime_after_minutes",
)


def update_settings(company: Company, *, by: Membership | None, **changes) -> AttendanceSettings:
    _require(by, Perm.ATTENDANCE_MANAGE)
    unknown = set(changes) - set(SETTINGS_FIELDS)
    if unknown:
        raise DomainError(_("Unknown setting: %(name)s") % {"name": ", ".join(sorted(unknown))})
    with transaction.atomic():
        row = AttendanceSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        before = {name: getattr(row, name) for name in changes}
        for name, value in changes.items():
            setattr(row, name, value)
        _clean(row)
        row.save()
        changed = _changes(before, changes)
        if changed:
            _audit(by, AttendanceAction.SETTINGS_CHANGED, row, changes=changed)
            _bump(company.pk, PULSE_SETTINGS)
    return row


def save_template(
    company: Company,
    *,
    by: Membership | None,
    template: ShiftTemplate | None = None,
    **fields,
) -> ShiftTemplate:
    _require(by, Perm.ATTENDANCE_MANAGE)
    allowed = {
        "name",
        "starts_at",
        "ends_at",
        "break_minutes",
        "color",
        "position",
        "is_active",
        "order",
    }
    if set(fields) - allowed:
        raise DomainError(_("Unknown field."))
    _same_company(company, template, fields.get("position"))
    row = template or ShiftTemplate(company=company)
    for name, value in fields.items():
        setattr(row, name, value)
    _clean(row)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        raise DomainError(_("A shift template with this name already exists.")) from exc
    _audit(by, AttendanceAction.TEMPLATE_SAVED, row, name=row.name)
    _bump(company.pk, PULSE_SCHEDULES)
    return row


def remove_template(template: ShiftTemplate, *, by: Membership | None) -> None:
    _require(by, Perm.ATTENDANCE_MANAGE)
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])
    _audit(by, AttendanceAction.TEMPLATE_REMOVED, template, name=template.name)
    _bump(template.company_id, PULSE_SCHEDULES)


# Schedules ------------------------------------------------------------------------------


def _validate_schedule(kind: str, days: list[dict], rotation: str, rotation_start, starts, ends):
    if kind == WorkSchedule.Kind.WEEKLY and not days:
        raise DomainError(_("Pick at least one working day."))
    if kind == WorkSchedule.Kind.ROTATING:
        if not rotation or "W" not in rotation:
            raise DomainError(_('Describe the rotation with W and O, e.g. "WWOO".'))
        if rotation_start is None or starts is None or ends is None:
            raise DomainError(_("A rotation needs its first day and its hours."))
    weekdays = [day["weekday"] for day in days]
    if len(weekdays) != len(set(weekdays)):
        raise DomainError(_("Each weekday can appear only once."))
    for day in days:
        if day["starts_at"] == day["ends_at"]:
            raise DomainError(_("A shift can't start and end at the same time."))


def create_schedule(
    company: Company,
    *,
    by: Membership | None,
    name: str,
    kind: str = WorkSchedule.Kind.WEEKLY,
    days: list[dict] = (),
    rotation: str = "",
    rotation_start: date | None = None,
    rotation_starts_at: time | None = None,
    rotation_ends_at: time | None = None,
    rotation_break_minutes: int = 60,
    color: int = 1,
) -> WorkSchedule:
    """A schedule; `days` are `{weekday, starts_at, ends_at, break_minutes}` for weekly ones."""
    _require(by, Perm.ATTENDANCE_MANAGE)
    days = list(days or [])
    rotation = (rotation or "").upper().replace(" ", "")
    _validate_schedule(kind, days, rotation, rotation_start, rotation_starts_at, rotation_ends_at)
    schedule = WorkSchedule(
        company=company,
        name=name.strip(),
        kind=kind,
        rotation=rotation if kind == WorkSchedule.Kind.ROTATING else "",
        rotation_start=rotation_start,
        rotation_starts_at=rotation_starts_at,
        rotation_ends_at=rotation_ends_at,
        rotation_break_minutes=rotation_break_minutes,
        color=color,
    )
    _clean(schedule)
    try:
        with transaction.atomic():
            schedule.save()
            if kind == WorkSchedule.Kind.WEEKLY:
                WorkScheduleDay.objects.bulk_create(
                    WorkScheduleDay(schedule=schedule, **day) for day in days
                )
            _audit(by, AttendanceAction.SCHEDULE_CREATED, schedule, name=schedule.name, kind=kind)
    except IntegrityError as exc:
        raise DomainError(_("A schedule with this name already exists.")) from exc
    _bump(company.pk, PULSE_SCHEDULES)
    return schedule


def update_schedule(
    schedule: WorkSchedule, *, by: Membership | None, days: list[dict] | None = None, **fields
) -> WorkSchedule:
    """Change a schedule; people following it get their untouched future shifts again."""
    _require(by, Perm.ATTENDANCE_MANAGE)
    allowed = {
        "name",
        "kind",
        "rotation",
        "rotation_start",
        "rotation_starts_at",
        "rotation_ends_at",
        "rotation_break_minutes",
        "color",
    }
    if set(fields) - allowed:
        raise DomainError(_("Unknown field."))
    if "rotation" in fields:
        fields["rotation"] = (fields["rotation"] or "").upper().replace(" ", "")
    before = {name: getattr(schedule, name) for name in fields}
    before_days = _days_snapshot(schedule)
    for name, value in fields.items():
        setattr(schedule, name, value)
    new_days = (
        days
        if days is not None
        else [
            {key: day[key] for key in ("weekday", "starts_at", "ends_at", "break_minutes")}
            for day in before_days
        ]
    )
    _validate_schedule(
        schedule.kind,
        new_days if schedule.kind == WorkSchedule.Kind.WEEKLY else [],
        schedule.rotation,
        schedule.rotation_start,
        schedule.rotation_starts_at,
        schedule.rotation_ends_at,
    )
    _clean(schedule)
    try:
        with transaction.atomic():
            schedule.save()
            if days is not None:
                schedule.days.all().delete()
                WorkScheduleDay.objects.bulk_create(
                    WorkScheduleDay(schedule=schedule, **day) for day in days
                )
            changed = _changes(before, fields)
            if days is not None and _days_snapshot(schedule) != before_days:
                changed["days"] = ["…", "…"]
            if changed:
                _audit(by, AttendanceAction.SCHEDULE_CHANGED, schedule, changes=changed)
            members = list(
                MemberSchedule.objects.filter(schedule=schedule).values_list(
                    "membership_id", flat=True
                )
            )
            if members:
                regenerate(schedule.company, members)
    except IntegrityError as exc:
        raise DomainError(_("A schedule with this name already exists.")) from exc
    _bump(schedule.company_id, PULSE_SCHEDULES, PULSE_ROSTER)
    return schedule


def _days_snapshot(schedule: WorkSchedule) -> list[dict]:
    return [
        {
            "weekday": day.weekday,
            "starts_at": day.starts_at,
            "ends_at": day.ends_at,
            "break_minutes": day.break_minutes,
        }
        for day in schedule.days.order_by("weekday")
    ]


def archive_schedule(schedule: WorkSchedule, *, by: Membership | None) -> WorkSchedule:
    """Retire a schedule: its people keep their past shifts, lose its untouched future ones."""
    _require(by, Perm.ATTENDANCE_MANAGE)
    with transaction.atomic():
        schedule.is_active = False
        schedule.save(update_fields=["is_active", "updated_at"])
        members = list(
            MemberSchedule.objects.filter(schedule=schedule).values_list("membership_id", flat=True)
        )
        MemberSchedule.objects.filter(schedule=schedule).update(schedule=None)
        if members:
            regenerate(schedule.company, members)
        _audit(by, AttendanceAction.SCHEDULE_ARCHIVED, schedule, name=schedule.name)
    _bump(schedule.company_id, PULSE_SCHEDULES, PULSE_ROSTER)
    return schedule


def assign_schedule(
    company: Company,
    schedule: WorkSchedule | None,
    member_ids: list[int],
    *,
    by: Membership | None,
    effective_from: date | None = None,
) -> int:
    """Put people on `schedule` (None takes them off any) from `effective_from` (today by
    default); their untouched future shifts are made again. Returns how many changed."""
    _require(by, Perm.ATTENDANCE_MANAGE)
    _same_company(company, schedule)
    if schedule is not None and not schedule.is_active:
        raise DomainError(_("This schedule is archived."))
    today = clock.today(company)
    effective_from = effective_from or today
    allowed = scope.branch_ids(by) if by is not None else None
    people = list(
        queries.staff(company, branch_ids=allowed).filter(pk__in=list(member_ids)).distinct()
    )
    if len(people) != len(set(member_ids)):
        raise DomainError(_("Some of these people aren't in your team."))
    with transaction.atomic():
        for member in people:
            MemberSchedule.objects.update_or_create(
                membership=member,
                defaults={
                    "company": company,
                    "schedule": schedule,
                    "effective_from": effective_from,
                },
            )
        regenerate(company, [member.pk for member in people], from_day=max(today, effective_from))
        target = schedule or conf.get_settings(company)
        _audit(
            by,
            AttendanceAction.SCHEDULE_ASSIGNED,
            target,
            people=[str(member) for member in people],
            effective_from=effective_from.isoformat(),
            schedule=schedule.name if schedule else None,
        )
    _bump(company.pk, PULSE_SCHEDULES, PULSE_ROSTER)
    return len(people)


# Shift generation -----------------------------------------------------------------------


def generate_shifts(
    company: Company,
    *,
    start: date | None = None,
    days: int = GENERATE_DAYS,
    member_ids: list[int] | None = None,
    now: datetime | None = None,
) -> int:
    """Shifts from people's schedules for `start` (today) and the `days` after it.

    Idempotent: a person's day that already has any shift row (planned, leave, a draft, or
    one a manager cancelled) is never touched, so manual and swapped shifts stay as they
    are. Holidays get no shift; approved time off gets a leave shift; suspended people get
    nothing while suspended. Generated shifts are published at once."""
    now = now or timezone.now()
    first = start or clock.today(company, now)
    last = first + timedelta(days=days)
    plans = (
        MemberSchedule.objects.for_company(company)
        .filter(
            schedule__isnull=False,
            schedule__is_active=True,
            membership__status__in=queries.STAFF_STATUSES,
        )
        .select_related("schedule", "membership")
        .prefetch_related("schedule__days")
    )
    if member_ids is not None:
        plans = plans.filter(membership_id__in=list(member_ids))
    plans = list(plans)
    if not plans:
        return 0
    ids = [plan.membership_id for plan in plans]
    days_off = set(queries.holidays(company, first, last))
    taken = set(
        WorkShift.objects.filter(
            company=company, date__range=(first, last), membership_id__in=ids
        ).values_list("membership_id", "date")
    )
    away = queries.leave_days(company, first, last, ids)
    made = []
    for plan in plans:
        member = plan.membership
        weekly = {row.weekday: row for row in plan.schedule.days.all()}
        for day in clock.days(max(first, plan.effective_from), last):
            if day in days_off or (member.pk, day) in taken:
                continue
            if queries.is_suspended_on(member, day):
                continue
            hours = rules.plan_for(plan.schedule, day, weekly)
            if hours is None:
                continue
            starts_at, ends_at = clock.window(company, day, hours.starts_at, hours.ends_at)
            time_off_id = away.get(member.pk, {}).get(day)
            made.append(
                WorkShift(
                    company=company,
                    membership=member,
                    date=day,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    break_minutes=hours.break_minutes,
                    branch_id=member.home_branch_id,
                    position_id=member.position_id,
                    status=WorkShift.Status.LEAVE if time_off_id else WorkShift.Status.PLANNED,
                    time_off_id=time_off_id,
                    source=WorkShift.Source.SCHEDULE,
                    published_at=now,
                )
            )
    if made:
        # Another run making the same rows at the same moment loses on the unique constraint.
        WorkShift.objects.bulk_create(made, ignore_conflicts=True)
        _bump(company.pk, PULSE_ROSTER)
    return len(made)


def regenerate(company: Company, member_ids: list[int], *, from_day: date | None = None) -> int:
    """Throw away people's untouched future shifts made from schedules (not started, no
    check-in, no open swap) and generate them again from their current schedule."""
    now = timezone.now()
    today = clock.today(company, now)
    from_day = from_day or today
    untouched = (
        WorkShift.objects.for_company(company)
        .filter(
            membership_id__in=list(member_ids),
            source=WorkShift.Source.SCHEDULE,
            date__gte=from_day,
            starts_at__gt=now,
            status__in=(WorkShift.Status.PLANNED, WorkShift.Status.LEAVE),
        )
        .exclude(pk__in=AttendanceRecord.objects.filter(shift__isnull=False).values("shift_id"))
        .exclude(
            pk__in=ShiftSwap.objects.filter(status__in=ShiftSwap.OPEN_STATUSES).values("shift_id")
        )
    )
    WorkShift.objects.filter(pk__in=list(untouched.values_list("pk", flat=True))).delete()
    horizon = today + timedelta(days=GENERATE_DAYS)
    if from_day > horizon:
        return 0
    return generate_shifts(
        company, start=from_day, days=(horizon - from_day).days, member_ids=member_ids, now=now
    )


# The roster -----------------------------------------------------------------------------


def _member_in_scope(by: Membership | None, member: Membership) -> None:
    if by is None:
        return
    allowed = scope.branch_ids(by)
    if allowed is None:
        return
    ids = set(member.branches.values_list("pk", flat=True))
    if member.home_branch_id:
        ids.add(member.home_branch_id)
    if not ids & set(allowed):
        raise PermissionDenied(_("You don't have permission to do this."))


def _check_free(member: Membership, starts_at: datetime, ends_at: datetime, *, exclude=None):
    clash = (
        WorkShift.objects.filter(membership=member, starts_at__lt=ends_at, ends_at__gt=starts_at)
        .exclude(status=WorkShift.Status.CANCELLED)
        .exclude(pk=exclude.pk if exclude else None)
        .first()
    )
    if clash is not None:
        raise DomainError(
            _("%(name)s already has a shift then (%(start)s–%(end)s).")
            % {
                "name": member,
                "start": clock.hhmm(member.company, clash.starts_at),
                "end": clock.hhmm(member.company, clash.ends_at),
            }
        )


def _check_not_away(member: Membership, day: date) -> None:
    if queries.on_leave(member, day) is not None:
        raise DomainError(_("%(name)s is on leave that day.") % {"name": member})


def _default_branch(company: Company, by: Membership | None) -> Branch | None:
    if by is not None and by.home_branch_id:
        return by.home_branch
    branches = list(Branch.objects.filter(company=company, is_active=True)[:2])
    return branches[0] if len(branches) == 1 else None


def create_shift(
    company: Company,
    *,
    by: Membership | None,
    date: date,
    starts_at: time,
    ends_at: time,
    membership: Membership | None = None,
    break_minutes: int = 60,
    branch: Branch | None = None,
    position: Position | None = None,
    note: str = "",
    publish: bool = False,
) -> WorkShift:
    """A shift added by hand (a draft until the roster is published, unless `publish`).
    Without `membership` it is an open shift that eligible people may claim."""
    _same_company(company, membership, branch, position)
    if membership is not None:
        if membership.status not in queries.STAFF_STATUSES:
            raise DomainError(_("This person isn't working here any more."))
        branch = branch or membership.home_branch
        position = position or membership.position
    else:
        branch = branch or _default_branch(company, by)
        if branch is None:
            raise DomainError(_("Pick the branch of this open shift."))
    _require(by, Perm.ATTENDANCE_MANAGE, branch.pk if branch else None)
    if membership is not None:
        _member_in_scope(by, membership)
    start_dt, end_dt = clock.window(company, date, starts_at, ends_at)
    if membership is not None:
        _check_free(membership, start_dt, end_dt)
        _check_not_away(membership, date)
    with transaction.atomic():
        shift = WorkShift.objects.create(
            company=company,
            membership=membership,
            date=date,
            starts_at=start_dt,
            ends_at=end_dt,
            break_minutes=break_minutes,
            branch=branch,
            position=position,
            status=WorkShift.Status.PLANNED if membership else WorkShift.Status.OPEN,
            source=WorkShift.Source.MANUAL,
            note=note,
            created_by=by.user if by else None,
            published_at=timezone.now() if publish else None,
        )
        _audit(
            by,
            AttendanceAction.SHIFT_CREATED,
            shift,
            person=str(membership) if membership else None,
            date=date.isoformat(),
            hours=f"{clock.hhmm(company, start_dt)}–{clock.hhmm(company, end_dt)}",
        )
        if publish:
            _announce([shift])
    _bump(company.pk, PULSE_ROSTER)
    return shift


SHIFT_FIELDS = (
    "membership",
    "date",
    "starts_at",
    "ends_at",
    "break_minutes",
    "branch",
    "position",
    "note",
)
UNSET = object()


def update_shift(shift: WorkShift, *, by: Membership | None, **changes) -> WorkShift:
    """Move or change a shift (another person, day, hours, branch, position, note). A
    published shift stays published and the people concerned are told at once."""
    company = shift.company
    if set(changes) - set(SHIFT_FIELDS):
        raise DomainError(_("Unknown field."))
    _require(by, Perm.ATTENDANCE_MANAGE, shift.branch_id)
    if shift.status == WorkShift.Status.CANCELLED:
        raise DomainError(_("This shift was removed."))
    moves = {"membership", "date", "starts_at", "ends_at"} & set(changes)
    if moves and shift.records.exists():
        raise DomainError(_("Someone already checked in on this shift, so it can't be moved."))
    _same_company(
        company, changes.get("membership"), changes.get("branch"), changes.get("position")
    )
    if "branch" in changes and changes["branch"] is not None:
        _require(by, Perm.ATTENDANCE_MANAGE, changes["branch"].pk)
    before = {
        "membership": shift.membership,
        "date": shift.date,
        "starts_at": clock.hhmm(company, shift.starts_at),
        "ends_at": clock.hhmm(company, shift.ends_at),
        "break_minutes": shift.break_minutes,
        "branch": shift.branch,
        "position": shift.position,
        "note": shift.note,
    }
    previous_member = shift.membership
    day = changes.get("date", shift.date)
    starts = changes.get("starts_at", clock.local(company, shift.starts_at).time())
    ends = changes.get("ends_at", clock.local(company, shift.ends_at).time())
    member = changes.get("membership", shift.membership)
    if member is not None:
        if member.status not in queries.STAFF_STATUSES:
            raise DomainError(_("This person isn't working here any more."))
        _member_in_scope(by, member)
    start_dt, end_dt = clock.window(company, day, starts, ends)
    if member is not None and (moves or "membership" in changes):
        _check_free(member, start_dt, end_dt, exclude=shift)
        _check_not_away(member, day)
    with transaction.atomic():
        shift.membership = member
        shift.date = day
        shift.starts_at, shift.ends_at = start_dt, end_dt
        for name in ("break_minutes", "branch", "position", "note"):
            if name in changes:
                setattr(shift, name, changes[name])
        if member is None:
            shift.status = WorkShift.Status.OPEN
        elif shift.status == WorkShift.Status.OPEN:
            shift.status = WorkShift.Status.PLANNED
        if shift.source == WorkShift.Source.SCHEDULE:
            shift.source = WorkShift.Source.MANUAL
        shift.save()
        after = {
            "membership": shift.membership,
            "date": shift.date,
            "starts_at": clock.hhmm(company, shift.starts_at),
            "ends_at": clock.hhmm(company, shift.ends_at),
            "break_minutes": shift.break_minutes,
            "branch": shift.branch,
            "position": shift.position,
            "note": shift.note,
        }
        changed = _changes(before, after)
        if changed:
            _audit(by, AttendanceAction.SHIFT_CHANGED, shift, changes=changed)
            if moves or "membership" in changes:
                _cancel_open_swaps([shift.pk], by=by)
            if shift.is_published and shift.date >= clock.today(company):
                people = {m for m in (previous_member, shift.membership) if m is not None}
                transaction.on_commit(
                    lambda: notify.shift_changed(shift.pk, [m.pk for m in people])
                )
    _bump(company.pk, PULSE_ROSTER)
    return shift


def delete_shift(shift: WorkShift, *, by: Membership | None) -> None:
    """Remove a shift. A draft disappears; a published shift is cancelled (so the schedule
    never makes it again) and its person is told. A shift with a check-in stays."""
    _require(by, Perm.ATTENDANCE_MANAGE, shift.branch_id)
    if shift.records.exists():
        raise DomainError(_("Someone already checked in on this shift, so it can't be removed."))
    with transaction.atomic():
        _cancel_open_swaps([shift.pk], by=by)
        _audit(
            by,
            AttendanceAction.SHIFT_CANCELLED,
            shift,
            person=str(shift.membership) if shift.membership else None,
            date=shift.date.isoformat(),
        )
        if shift.published_at is None:
            shift.delete()
        else:
            shift.status = WorkShift.Status.CANCELLED
            shift.save(update_fields=["status", "updated_at"])
            if shift.membership_id and shift.date >= clock.today(shift.company):
                shift_id, member_id = shift.pk, shift.membership_id
                transaction.on_commit(lambda: notify.shift_removed(shift_id, member_id))
    _bump(shift.company_id, PULSE_ROSTER)


BULK_ACTIONS = ("copy_week", "apply_schedule", "clear")


def bulk_roster(
    company: Company,
    *,
    by: Membership | None,
    action: str,
    week: date,
    branch_id: int | None = None,
    member_ids: list[int] | None = None,
) -> int:
    """Roster actions on one week (Monday first): `copy_week` copies last week's shifts as
    drafts, `apply_schedule` fills the week from people's schedules as drafts, `clear`
    removes the week's shifts without check-ins. Returns how many shifts changed."""
    if action not in BULK_ACTIONS:
        raise DomainError(_("Unknown roster action."))
    _require(by, Perm.ATTENDANCE_MANAGE, branch_id if branch_id is not None else ANY_BRANCH)
    start = clock.week_start(week)
    end = start + timedelta(days=6)
    allowed = scope.branch_ids(by) if by is not None else None
    people = queries.staff_at(company, branch_id, branch_ids=allowed).filter(
        status=Membership.Status.APPROVED
    )
    if member_ids is not None:
        people = people.filter(pk__in=list(member_ids))
    people = list(people.select_related("home_branch", "position", "work_schedule__schedule"))
    ids = [member.pk for member in people]
    with transaction.atomic():
        if action == "copy_week":
            count = _copy_week(company, by, start, ids, branch_id, allowed)
        elif action == "apply_schedule":
            count = _apply_schedules(company, by, start, end, people)
        else:
            count = _clear_week(company, by, start, end, ids, branch_id, allowed)
        _audit(
            by,
            AttendanceAction.ROSTER_BULK,
            conf.get_settings(company),
            operation=action,
            week=start.isoformat(),
            branch=branch_id,
            shifts=count,
        )
    _bump(company.pk, PULSE_ROSTER)
    return count


def _copy_week(company, by, start, ids, branch_id, allowed) -> int:
    source = queries.shifts_between(
        company,
        start - timedelta(days=7),
        start - timedelta(days=1),
        branch_ids=allowed,
        branch_id=branch_id,
    ).filter(status__in=(WorkShift.Status.PLANNED, WorkShift.Status.OPEN))
    source = source.filter(Q(membership_id__in=ids) | Q(membership__isnull=True))
    days_off = set(queries.holidays(company, start, start + timedelta(days=6)))
    taken = set(
        WorkShift.objects.filter(
            company=company, date__range=(start, start + timedelta(days=6)), membership_id__in=ids
        )
        .exclude(status=WorkShift.Status.CANCELLED)
        .values_list("membership_id", "date")
    )
    away = queries.leave_days(company, start, start + timedelta(days=6), ids)
    made = []
    for shift in source:
        day = shift.date + timedelta(days=7)
        if day in days_off:
            continue
        if shift.membership_id and (
            (shift.membership_id, day) in taken or day in away.get(shift.membership_id, {})
        ):
            continue
        starts = clock.local(company, shift.starts_at).time()
        ends = clock.local(company, shift.ends_at).time()
        start_dt, end_dt = clock.window(company, day, starts, ends)
        made.append(
            WorkShift(
                company=company,
                membership_id=shift.membership_id,
                date=day,
                starts_at=start_dt,
                ends_at=end_dt,
                break_minutes=shift.break_minutes,
                branch_id=shift.branch_id,
                position_id=shift.position_id,
                status=shift.status,
                source=WorkShift.Source.MANUAL,
                note=shift.note,
                created_by=by.user if by else None,
            )
        )
        if shift.membership_id:
            taken.add((shift.membership_id, day))
    WorkShift.objects.bulk_create(made)
    return len(made)


def _apply_schedules(company, by, start, end, people) -> int:
    days_off = set(queries.holidays(company, start, end))
    ids = [member.pk for member in people]
    taken = set(
        WorkShift.objects.filter(company=company, date__range=(start, end), membership_id__in=ids)
        .exclude(status=WorkShift.Status.CANCELLED)
        .values_list("membership_id", "date")
    )
    away = queries.leave_days(company, start, end, ids)
    made = []
    for member in people:
        plan = getattr(member, "work_schedule", None)
        if plan is None or plan.schedule is None or not plan.schedule.is_active:
            continue
        weekly = {row.weekday: row for row in plan.schedule.days.all()}
        for day in clock.days(max(start, plan.effective_from), end):
            if day in days_off or (member.pk, day) in taken or day in away.get(member.pk, {}):
                continue
            hours = rules.plan_for(plan.schedule, day, weekly)
            if hours is None:
                continue
            start_dt, end_dt = clock.window(company, day, hours.starts_at, hours.ends_at)
            made.append(
                WorkShift(
                    company=company,
                    membership=member,
                    date=day,
                    starts_at=start_dt,
                    ends_at=end_dt,
                    break_minutes=hours.break_minutes,
                    branch_id=member.home_branch_id,
                    position_id=member.position_id,
                    source=WorkShift.Source.MANUAL,
                    created_by=by.user if by else None,
                )
            )
    WorkShift.objects.bulk_create(made)
    return len(made)


def _clear_week(company, by, start, end, ids, branch_id, allowed) -> int:
    shifts = queries.shifts_between(
        company, start, end, branch_ids=allowed, branch_id=branch_id
    ).filter(Q(membership_id__in=ids) | Q(membership__isnull=True))
    shifts = shifts.exclude(
        pk__in=AttendanceRecord.objects.filter(shift__isnull=False).values("shift_id")
    )
    shifts = shifts.filter(starts_at__gt=timezone.now())
    rows = list(shifts)
    _cancel_open_swaps([shift.pk for shift in rows], by=by)
    drafts = [shift.pk for shift in rows if shift.published_at is None]
    published = [shift for shift in rows if shift.published_at is not None]
    WorkShift.objects.filter(pk__in=drafts).delete()
    WorkShift.objects.filter(pk__in=[shift.pk for shift in published]).update(
        status=WorkShift.Status.CANCELLED, updated_at=timezone.now()
    )
    told: dict[int, list[int]] = {}
    for shift in published:
        if shift.membership_id:
            told.setdefault(shift.membership_id, []).append(shift.pk)
    if told:
        transaction.on_commit(lambda: notify.shifts_removed(told))
    return len(rows)


def publish_roster(
    company: Company,
    *,
    by: Membership | None,
    start: date,
    end: date,
    branch_id: int | None = None,
) -> int:
    """Publish the drafts from `start` to `end`: they become expected work, show in the app,
    and each person gets one message listing their new shifts (open shifts go to the people
    who may claim them)."""
    _require(by, Perm.ATTENDANCE_MANAGE, branch_id if branch_id is not None else ANY_BRANCH)
    allowed = scope.branch_ids(by) if by is not None else None
    drafts = (
        WorkShift.objects.for_company(company)
        .filter(published_at__isnull=True, date__range=(start, end))
        .exclude(status=WorkShift.Status.CANCELLED)
    )
    drafts = scope.restrict(drafts, allowed)
    if branch_id is not None:
        drafts = drafts.filter(branch_id=branch_id)
    with transaction.atomic():
        rows = list(drafts.select_for_update(of=("self",)))
        if not rows:
            return 0
        now = timezone.now()
        WorkShift.objects.filter(pk__in=[row.pk for row in rows]).update(
            published_at=now, updated_at=now
        )
        for row in rows:
            row.published_at = now
        _announce(rows)
        _audit(
            by,
            AttendanceAction.ROSTER_PUBLISHED,
            conf.get_settings(company),
            start=start.isoformat(),
            end=end.isoformat(),
            branch=branch_id,
            shifts=len(rows),
        )
    _bump(company.pk, PULSE_ROSTER)
    return len(rows)


def _announce(shifts: list[WorkShift]) -> None:
    """After commit: tell each person about their newly published shifts and offer open
    shifts to the people who may claim them."""
    today = clock.today(shifts[0].company) if shifts else None
    mine: dict[int, list[int]] = {}
    open_ids = []
    for shift in shifts:
        if shift.date < today:
            continue
        if shift.membership_id and shift.status == WorkShift.Status.PLANNED:
            mine.setdefault(shift.membership_id, []).append(shift.pk)
        elif shift.status == WorkShift.Status.OPEN:
            open_ids.append(shift.pk)
    if mine:
        transaction.on_commit(lambda: notify.roster_published(mine))
    if open_ids:
        transaction.on_commit(lambda: notify.open_shifts_posted(open_ids))


# Check-in and check-out -----------------------------------------------------------------


@dataclass
class CheckResult:
    record: AttendanceRecord
    created: bool
    outside: bool
    distance_m: int | None


def _locate(branch: Branch | None, lat, lng, accuracy, settings) -> tuple[int | None, bool, list]:
    """(distance to the branch, outside its geofence, flags) for a tap at lat/lng.

    Outside means farther than the geofence plus the reading's accuracy (at most the fence
    again): an honest but imprecise reading isn't called outside, only marked imprecise."""
    if lat is None or lng is None:
        return None, False, [Flag.NO_LOCATION]
    flags = []
    if accuracy is not None and accuracy > settings.max_accuracy_m:
        flags.append(Flag.LOW_ACCURACY)
    if branch is None or branch.latitude is None or branch.longitude is None:
        return None, False, flags
    distance = geo.distance_m(branch.latitude, branch.longitude, lat, lng)
    allowance = min(int(accuracy or 0), branch.geofence_m)
    outside = distance > branch.geofence_m + allowance
    if outside:
        flags.append(Flag.OUTSIDE_GEOFENCE)
    return distance, outside, flags


def _point(lat, lng, accuracy):
    if lat is None and lng is None:
        return None, None, None
    if not geo.valid_point(lat, lng):
        raise DomainError(_("That location doesn't look right. Try again."))
    acc = None
    if accuracy is not None:
        try:
            acc = max(0, round(float(accuracy)))
        except TypeError, ValueError:
            acc = None
    return geo.coordinate(lat), geo.coordinate(lng), acc


def _distance_text(meters: int) -> str:
    if meters >= 1000:
        return _("%(km)s km") % {"km": f"{meters / 1000:.1f}"}
    return _("%(m)s m") % {"m": meters}


def check_in(
    membership: Membership,
    *,
    lat=None,
    lng=None,
    accuracy=None,
    photo=None,
    source: str = Source.APP,
    now: datetime | None = None,
) -> CheckResult:
    """Check `membership` in at `now`.

    The check-in belongs to the shift whose window holds `now` (overnight shifts included);
    without one it is an unscheduled check-in. Distance and flags come from the shift's
    branch, else the person's home branch. A second tap within two minutes returns the same
    record; a row lock on the person and a unique constraint make a double tap one record.
    Checking in again during a shift whose check-out was a mistake reopens that record."""
    company = membership.company
    _ensure_module(company)
    settings = conf.get_settings(company)
    now = now or timezone.now()
    lat, lng, accuracy = _point(lat, lng, accuracy)
    if settings.require_location and lat is None and source in (Source.APP, Source.BOT):
        raise DomainError(_("Share your location to check in."))
    if settings.require_photo and photo is None and source == Source.APP:
        raise DomainError(_("Take a selfie to check in."))
    selfie = sanitize_image(photo, max_side=1280) if photo is not None else None
    with transaction.atomic():
        member = (
            Membership.objects.select_for_update(of=("self",))
            .select_related("company", "home_branch", "user", "position")
            .get(pk=membership.pk)
        )
        if member.status != Membership.Status.APPROVED:
            raise DomainError(_("Your access is paused, so you can't check in."))
        current = queries.open_record(member)
        if current is not None:
            if current.check_in_at and (now - current.check_in_at).total_seconds() < (
                rules.DOUBLE_TAP_SECONDS
            ):
                return CheckResult(
                    current, False, Flag.OUTSIDE_GEOFENCE in current.flags, current.in_distance_m
                )
            raise DomainError(
                _("You're already checked in since %(time)s.")
                % {"time": clock.hhmm(company, current.check_in_at)}
            )
        shift = queries.current_shift(member, now, settings=settings)
        branch = (shift.branch if shift else None) or member.home_branch
        distance, outside, flags = _locate(branch, lat, lng, accuracy, settings)
        if outside and settings.outside_action == AttendanceSettings.OutsideAction.REJECT:
            raise DomainError(
                _("You're %(distance)s from %(branch)s. Check in when you get there.")
                % {"distance": _distance_text(distance), "branch": branch.name}
            )
        record = (
            AttendanceRecord.objects.filter(membership=member, shift=shift).first()
            if shift
            else None
        )
        created = record is None
        reopened = False
        if record is not None and record.attended and record.check_in_at is not None:
            # A check-out by mistake: the shift goes on.
            reopened = True
            record.status = AttendanceRecord.Status.OPEN
            record.check_out_at = None
            record.out_lat = record.out_lng = record.out_accuracy_m = record.out_distance_m = None
            record.out_source = ""
            rules.drop_flag(record, Flag.AUTO_CLOSED)
        else:
            if record is None:
                record = AttendanceRecord(
                    company=company,
                    membership=member,
                    shift=shift,
                    date=shift.date if shift else clock.today(company, now),
                )
            record.status = AttendanceRecord.Status.OPEN
            record.check_in_at = now
            record.in_lat, record.in_lng, record.in_accuracy_m = lat, lng, accuracy
            record.in_distance_m = distance
            record.in_source = source
            record.branch = branch
            record.flags = [flag for flag in record.flags if flag == Flag.EDITED]
            for flag in flags:
                rules.add_flag(record, flag)
            if shift is None:
                rules.add_flag(record, Flag.UNSCHEDULED)
        rules.compute(record, settings)
        try:
            with transaction.atomic():
                record.save()
        except IntegrityError:
            existing = queries.open_record(member)
            if existing is None:
                raise
            return CheckResult(
                existing, False, Flag.OUTSIDE_GEOFENCE in existing.flags, existing.in_distance_m
            )
        if selfie is not None and not reopened:
            record.in_photo.save(selfie.name, selfie, save=False)
            record.save(update_fields=["in_photo", "updated_at"])
        record_id = record.pk
        if record.is_late and not reopened:
            transaction.on_commit(lambda: notify.late_arrival(record_id))
        if outside and not reopened:
            transaction.on_commit(lambda: notify.outside_check_in(record_id))
    _bump(company.pk, PULSE_BOARD, PULSE_NOT_IN)
    return CheckResult(record, created, outside, distance)


def check_out(
    membership: Membership,
    *,
    lat=None,
    lng=None,
    accuracy=None,
    source: str = Source.APP,
    now: datetime | None = None,
) -> CheckResult:
    """Check `membership` out of their open record at `now` (a second tap within two minutes
    returns the record just closed). Overtime beyond the shift waits for approval."""
    company = membership.company
    _ensure_module(company)
    settings = conf.get_settings(company)
    now = now or timezone.now()
    lat, lng, accuracy = _point(lat, lng, accuracy)
    if settings.require_location and lat is None and source in (Source.APP, Source.BOT):
        raise DomainError(_("Share your location to check out."))
    with transaction.atomic():
        member = Membership.objects.select_for_update(of=("self",)).get(pk=membership.pk)
        record = queries.open_record(member)
        if record is None:
            recent = (
                AttendanceRecord.objects.filter(
                    membership=member,
                    check_out_at__gte=now - timedelta(seconds=rules.DOUBLE_TAP_SECONDS),
                )
                .order_by("-check_out_at")
                .first()
            )
            if recent is not None:
                return CheckResult(recent, False, False, recent.out_distance_m)
            raise DomainError(_("You haven't checked in."))
        distance, outside, flags = _locate(record.branch, lat, lng, accuracy, settings)
        record.check_out_at = max(now, record.check_in_at)
        record.out_lat, record.out_lng, record.out_accuracy_m = lat, lng, accuracy
        record.out_distance_m = distance
        record.out_source = source
        record.status = AttendanceRecord.Status.CLOSED
        for flag in flags:
            if flag != Flag.NO_LOCATION or lat is None:
                rules.add_flag(record, flag)
        rules.compute(record, settings)
        record.save()
        if record.overtime_status == AttendanceRecord.Overtime.PENDING:
            record_id = record.pk
            transaction.on_commit(lambda: notify.overtime_waiting(record_id))
    _bump(company.pk, PULSE_BOARD, PULSE_CORRECTIONS)
    return CheckResult(record, False, outside, distance)


def check_out_now(membership: Membership, *, source: str = Source.BOT) -> CheckResult:
    """ "I'm done now" from the bot: a check-out without a location. It is marked as such,
    never refused, so a forgotten check-out doesn't wait for the automatic close."""
    company = membership.company
    settings = conf.get_settings(company)
    now = timezone.now()
    with transaction.atomic():
        member = Membership.objects.select_for_update(of=("self",)).get(pk=membership.pk)
        record = queries.open_record(member)
        if record is None:
            raise DomainError(_("You haven't checked in."))
        record.check_out_at = max(now, record.check_in_at)
        record.out_source = source
        record.status = AttendanceRecord.Status.CLOSED
        rules.add_flag(record, Flag.NO_LOCATION)
        rules.compute(record, settings)
        record.save()
        if record.overtime_status == AttendanceRecord.Overtime.PENDING:
            record_id = record.pk
            transaction.on_commit(lambda: notify.overtime_waiting(record_id))
    _bump(company.pk, PULSE_BOARD, PULSE_CORRECTIONS)
    return CheckResult(record, False, False, None)


# Records: manager edits -----------------------------------------------------------------


def _reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise DomainError(_("Give a reason."))
    return reason[:300]


def _times(record_date: date, check_in_at, check_out_at, company) -> None:
    if check_in_at is None and check_out_at is not None:
        raise DomainError(_("Give the check-in time too."))
    if check_in_at is not None and check_out_at is not None and check_out_at <= check_in_at:
        raise DomainError(_("The check-out must be after the check-in."))
    if check_in_at is not None:
        local = clock.local(company, check_in_at).date()
        if not record_date - timedelta(days=1) <= local <= record_date + timedelta(days=1):
            raise DomainError(_("The check-in must be on that day."))
    if check_in_at is not None and check_in_at > timezone.now() + timedelta(minutes=5):
        raise DomainError(_("That time is in the future."))
    if check_out_at is not None and check_out_at > timezone.now() + timedelta(minutes=5):
        raise DomainError(_("That time is in the future."))


def edit_record(
    record: AttendanceRecord,
    *,
    by: Membership | None,
    reason: str,
    check_in_at=UNSET,
    check_out_at=UNSET,
    note=UNSET,
) -> AttendanceRecord:
    """A manager fixes a record's times or note (the reason goes to the audit log)."""
    _require(by, Perm.ATTENDANCE_MANAGE, record.branch_id)
    reason = _reason(reason)
    company = record.company
    settings = conf.get_settings(company)
    with transaction.atomic():
        record = (
            AttendanceRecord.objects.select_for_update(of=("self",))
            .select_related("shift")
            .get(pk=record.pk)
        )
        before = {
            "check_in_at": record.check_in_at,
            "check_out_at": record.check_out_at,
            "status": record.status,
            "note": record.note,
        }
        new_in = record.check_in_at if check_in_at is UNSET else check_in_at
        new_out = record.check_out_at if check_out_at is UNSET else check_out_at
        _times(record.date, new_in, new_out, company)
        record.check_in_at, record.check_out_at = new_in, new_out
        if note is not UNSET:
            record.note = (note or "")[:300]
        if new_in is not None and new_out is not None:
            record.status = AttendanceRecord.Status.CLOSED
            rules.drop_flag(record, Flag.AUTO_CLOSED)
            if not record.out_source:
                record.out_source = Source.MANUAL
        elif new_in is not None:
            other = (
                AttendanceRecord.objects.filter(
                    membership_id=record.membership_id, status=AttendanceRecord.Status.OPEN
                )
                .exclude(pk=record.pk)
                .exists()
            )
            if other:
                raise DomainError(_("This person is checked in elsewhere; give a check-out time."))
            record.status = AttendanceRecord.Status.OPEN
        if new_in is not None and not record.in_source:
            record.in_source = Source.MANUAL
        rules.add_flag(record, Flag.EDITED)
        record.edited_by = by.user if by else None
        if before["check_in_at"] != new_in or before["check_out_at"] != new_out:
            record.overtime_status = AttendanceRecord.Overtime.NONE
        rules.compute(record, settings)
        record.save()
        after = {
            "check_in_at": record.check_in_at,
            "check_out_at": record.check_out_at,
            "status": record.status,
            "note": record.note,
        }
        _audit(
            by,
            AttendanceAction.RECORD_EDITED,
            record,
            changes=_changes(before, after),
            reason=reason,
        )
    _bump(company.pk, PULSE_BOARD, PULSE_CORRECTIONS)
    return record


def create_record(
    company: Company,
    *,
    by: Membership | None,
    membership: Membership,
    date: date,
    check_in_at: datetime,
    check_out_at: datetime | None,
    reason: str,
    note: str = "",
) -> AttendanceRecord:
    """A manager records a day nobody checked in for (the timesheet's empty cell)."""
    _same_company(company, membership)
    reason = _reason(reason)
    _times(date, check_in_at, check_out_at, company)
    if check_out_at is None:
        raise DomainError(_("Give the check-out time too."))
    settings = conf.get_settings(company)
    if AttendanceRecord.objects.filter(membership=membership, date=date).exists():
        raise DomainError(_("This day already has a record; correct that one instead."))
    shift = (
        WorkShift.objects.working()
        .filter(membership=membership, date=date)
        .exclude(records__isnull=False)
        .order_by("starts_at")
        .first()
    )
    branch = (shift.branch if shift else None) or membership.home_branch
    _require(by, Perm.ATTENDANCE_MANAGE, branch.pk if branch else None)
    with transaction.atomic():
        record = AttendanceRecord(
            company=company,
            membership=membership,
            shift=shift,
            date=date,
            status=AttendanceRecord.Status.CLOSED,
            check_in_at=check_in_at,
            check_out_at=check_out_at,
            branch=branch,
            in_source=Source.MANUAL,
            out_source=Source.MANUAL,
            flags=[Flag.EDITED] + ([] if shift else [Flag.UNSCHEDULED]),
            note=note[:300],
            edited_by=by.user if by else None,
        )
        rules.compute(record, settings)
        try:
            with transaction.atomic():
                record.save()
        except IntegrityError as exc:
            raise DomainError(
                _("This day already has a record; correct that one instead.")
            ) from exc
        _audit(
            by,
            AttendanceAction.RECORD_CREATED,
            record,
            person=str(membership),
            date=date.isoformat(),
            reason=reason,
        )
    _bump(company.pk, PULSE_BOARD)
    return record


def excuse(record: AttendanceRecord, *, by: Membership | None, reason: str) -> AttendanceRecord:
    """Turn an absence into an excused day (sick without time off, a family emergency)."""
    _require(by, Perm.ATTENDANCE_MANAGE, record.branch_id)
    reason = _reason(reason)
    if record.status != AttendanceRecord.Status.ABSENT:
        raise DomainError(_("Only an absence can be excused."))
    with transaction.atomic():
        record.status = AttendanceRecord.Status.EXCUSED
        record.note = reason
        record.edited_by = by.user if by else None
        rules.add_flag(record, Flag.EDITED)
        record.save()
        _audit(by, AttendanceAction.RECORD_EXCUSED, record, reason=reason)
    _bump(record.company_id, PULSE_BOARD)
    return record


def decide_overtime(
    record: AttendanceRecord, *, by: Membership | None, approve: bool, reason: str = ""
) -> AttendanceRecord:
    _require(by, Perm.ATTENDANCE_MANAGE, record.branch_id)
    if not approve:
        reason = _reason(reason)
    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
        if record.overtime_status != AttendanceRecord.Overtime.PENDING:
            raise DomainError(_("This overtime has already been decided."))
        record.overtime_status = (
            AttendanceRecord.Overtime.APPROVED if approve else AttendanceRecord.Overtime.REJECTED
        )
        record.save(update_fields=["overtime_status", "updated_at"])
        _audit(
            by,
            AttendanceAction.OVERTIME_APPROVED if approve else AttendanceAction.OVERTIME_REJECTED,
            record,
            minutes=record.overtime_minutes,
            reason=reason,
        )
        inbox.settle(record, outcome=APPROVED_TEXT if approve else REJECTED_TEXT, by=by)
        record_id = record.pk
        transaction.on_commit(lambda: notify.overtime_decided(record_id, reason))
    _bump(record.company_id, PULSE_CORRECTIONS)
    return record


# Corrections ----------------------------------------------------------------------------


def request_correction(
    membership: Membership,
    *,
    date: date,
    reason: str,
    check_in_at: datetime | None = None,
    check_out_at: datetime | None = None,
    record: AttendanceRecord | None = None,
) -> AttendanceCorrection:
    """ "I forgot to check in": ask a manager to set a day's times."""
    company = membership.company
    _ensure_module(company)
    reason = _reason(reason)
    today = clock.today(company)
    if date > today:
        raise DomainError(_("You can't correct a day that hasn't come yet."))
    if date < today - timedelta(days=CORRECTION_DAYS):
        raise DomainError(_("That day is too long ago to correct."))
    if check_in_at is None and check_out_at is None:
        raise DomainError(_("Give the time you came or left."))
    if record is not None and record.membership_id != membership.pk:
        raise DomainError(_("That isn't your record."))
    if record is None:
        record = (
            AttendanceRecord.objects.filter(membership=membership, date=date)
            .order_by("-check_in_at")
            .first()
        )
    if record is None and (check_in_at is None or check_out_at is None):
        raise DomainError(_("Give both the time you came and the time you left."))
    _times(
        date,
        check_in_at if check_in_at is not None else (record.check_in_at if record else None),
        check_out_at,
        company,
    )
    if AttendanceCorrection.objects.filter(
        membership=membership, date=date, status=AttendanceCorrection.Status.PENDING
    ).exists():
        raise DomainError(_("You already asked to correct this day."))
    with transaction.atomic():
        correction = AttendanceCorrection.objects.create(
            company=company,
            membership=membership,
            record=record,
            date=date,
            check_in_at=check_in_at,
            check_out_at=check_out_at,
            reason=reason,
        )
        correction_id = correction.pk
        transaction.on_commit(lambda: notify.correction_waiting(correction_id))
    _bump(company.pk, PULSE_CORRECTIONS)
    return correction


def _correction_branch(correction: AttendanceCorrection) -> int | None:
    if correction.record_id and correction.record.branch_id:
        return correction.record.branch_id
    return correction.membership.home_branch_id


def decide_correction(
    correction: AttendanceCorrection, *, by: Membership | None, approve: bool, reason: str = ""
) -> AttendanceCorrection:
    """Approve (the times are applied to the day's record, or a record is made) or reject
    (a reason is required)."""
    _require(by, Perm.ATTENDANCE_MANAGE, _correction_branch(correction))
    if not approve:
        reason = _reason(reason)
    company = correction.company
    settings = conf.get_settings(company)
    with transaction.atomic():
        correction = (
            AttendanceCorrection.objects.select_for_update(of=("self",))
            .select_related("membership", "record")
            .get(pk=correction.pk)
        )
        if correction.status != AttendanceCorrection.Status.PENDING:
            raise DomainError(_("This correction has already been decided."))
        if approve:
            record = _apply_correction(correction, settings, by)
            correction.record = record
        correction.status = (
            AttendanceCorrection.Status.APPROVED
            if approve
            else AttendanceCorrection.Status.REJECTED
        )
        correction.decided_by = by.user if by else None
        correction.decided_at = timezone.now()
        correction.decision_note = reason
        correction.save()
        _audit(
            by,
            AttendanceAction.CORRECTION_APPROVED
            if approve
            else AttendanceAction.CORRECTION_REJECTED,
            correction,
            person=str(correction.membership),
            date=correction.date.isoformat(),
            reason=reason or correction.reason,
        )
        inbox.settle(correction, outcome=APPROVED_TEXT if approve else REJECTED_TEXT, by=by)
        correction_id = correction.pk
        transaction.on_commit(lambda: notify.correction_decided(correction_id))
    _bump(company.pk, PULSE_CORRECTIONS, PULSE_BOARD)
    return correction


def _apply_correction(correction, settings, by) -> AttendanceRecord:
    record = correction.record
    member = correction.membership
    if record is None:
        record = (
            AttendanceRecord.objects.select_for_update()
            .filter(membership=member, date=correction.date)
            .order_by("-check_in_at")
            .first()
        )
    if record is None:
        shift = (
            WorkShift.objects.working()
            .filter(membership=member, date=correction.date)
            .exclude(records__isnull=False)
            .order_by("starts_at")
            .first()
        )
        record = AttendanceRecord(
            company=correction.company,
            membership=member,
            shift=shift,
            date=correction.date,
            branch=(shift.branch if shift else None) or member.home_branch,
            in_source=Source.MANUAL,
            out_source=Source.MANUAL,
            flags=[] if shift else [Flag.UNSCHEDULED],
        )
    if correction.check_in_at is not None:
        record.check_in_at = correction.check_in_at
        record.in_source = record.in_source or Source.MANUAL
    if correction.check_out_at is not None:
        record.check_out_at = correction.check_out_at
        record.out_source = Source.MANUAL
    if record.check_in_at and record.check_out_at:
        if record.check_out_at <= record.check_in_at:
            raise DomainError(_("The check-out must be after the check-in."))
        record.status = AttendanceRecord.Status.CLOSED
        rules.drop_flag(record, Flag.AUTO_CLOSED)
    elif record.check_in_at:
        record.status = AttendanceRecord.Status.OPEN
    rules.add_flag(record, Flag.EDITED)
    record.edited_by = by.user if by else None
    record.overtime_status = AttendanceRecord.Overtime.NONE
    rules.compute(record, settings)
    try:
        with transaction.atomic():
            record.save()
    except IntegrityError as exc:
        raise DomainError(_("This person is checked in elsewhere right now.")) from exc
    return record


# Swaps, covers and open shifts ----------------------------------------------------------


def _swap_settings(company: Company) -> AttendanceSettings:
    return conf.get_settings(company)


def request_swap(
    membership: Membership,
    *,
    shift: WorkShift,
    kind: str,
    other_shift: WorkShift | None = None,
    target: Membership | None = None,
    note: str = "",
    now: datetime | None = None,
) -> ShiftSwap:
    """Ask for cover (a named colleague, or anyone eligible when `target` is None) or offer
    to swap `shift` for a colleague's `other_shift`."""
    company = membership.company
    _ensure_module(company)
    now = now or timezone.now()
    _same_company(company, shift, other_shift, target)
    if kind not in (ShiftSwap.Kind.COVER, ShiftSwap.Kind.SWAP):
        raise DomainError(_("Ask for cover or a swap."))
    if shift.membership_id != membership.pk or not shift.is_published:
        raise DomainError(_("That isn't your shift."))
    if shift.status != WorkShift.Status.PLANNED or shift.starts_at <= now:
        raise DomainError(_("This shift can't be handed over any more."))
    if shift.swaps.filter(status__in=ShiftSwap.OPEN_STATUSES).exists():
        raise DomainError(_("You already asked about this shift."))
    expires = shift.starts_at
    if kind == ShiftSwap.Kind.SWAP:
        if other_shift is None:
            raise DomainError(_("Pick the colleague's shift to swap with."))
        if (
            other_shift.membership_id in (None, membership.pk)
            or not other_shift.is_published
            or other_shift.status != WorkShift.Status.PLANNED
            or other_shift.starts_at <= now
        ):
            raise DomainError(_("That shift can't be swapped."))
        target = other_shift.membership
        if not queries.is_eligible(shift, target, ignore_shift_ids=[other_shift.pk]):
            raise DomainError(_("%(name)s can't take this shift.") % {"name": target})
        if not queries.is_eligible(other_shift, membership, ignore_shift_ids=[shift.pk]):
            raise DomainError(_("You can't take that shift."))
        expires = min(shift.starts_at, other_shift.starts_at)
    elif target is not None:
        if not queries.is_eligible(shift, target):
            raise DomainError(_("%(name)s can't take this shift.") % {"name": target})
    elif not queries.eligible_for(shift).exists():
        raise DomainError(_("Nobody else can take this shift right now."))
    with transaction.atomic():
        swap = ShiftSwap.objects.create(
            company=company,
            shift=shift,
            requested_by=membership,
            kind=kind,
            other_shift=other_shift if kind == ShiftSwap.Kind.SWAP else None,
            target=target,
            note=note[:300],
            expires_at=expires,
        )
        swap_id = swap.pk
        transaction.on_commit(lambda: notify.swap_offered(swap_id))
    _bump(company.pk, PULSE_SWAPS)
    return swap


def accept_swap(swap: ShiftSwap, *, by: Membership, now: datetime | None = None) -> ShiftSwap:
    """The colleague agrees. Without required approval the shift moves at once; otherwise
    it waits for a manager (queue `attendance.swaps`)."""
    now = now or timezone.now()
    settings = _swap_settings(swap.company)
    with transaction.atomic():
        swap = (
            ShiftSwap.objects.select_for_update(of=("self",))
            .select_related("shift__membership", "shift__company", "other_shift", "requested_by")
            .get(pk=swap.pk)
        )
        if swap.status != ShiftSwap.Status.REQUESTED:
            raise DomainError(_("This request has already been answered."))
        if swap.expires_at <= now:
            raise DomainError(_("This shift has already started."))
        if swap.requested_by_id == by.pk:
            raise DomainError(_("You can't accept your own request."))
        if swap.target_id is not None and swap.target_id != by.pk:
            raise PermissionDenied(_("This request is for someone else."))
        ignore = [swap.other_shift_id] if swap.other_shift_id else []
        if not queries.is_eligible(swap.shift, by, ignore_shift_ids=ignore):
            raise DomainError(_("You can't take this shift."))
        swap.accepted_by = by
        swap.status = ShiftSwap.Status.ACCEPTED
        swap.save(update_fields=["accepted_by", "status", "updated_at"])
        inbox.settle(swap, outcome=gettext_lazy("Accepted"), by=by, kind="attendance.cover_request")
        if not settings.swaps_need_approval:
            _apply_swap(swap, by=None, now=now)
        else:
            swap_id = swap.pk
            transaction.on_commit(lambda: notify.swap_waiting(swap_id))
    _bump(swap.company_id, PULSE_SWAPS, PULSE_ROSTER)
    return swap


def decline_swap(swap: ShiftSwap, *, by: Membership) -> ShiftSwap:
    """The named colleague says no."""
    with transaction.atomic():
        swap = ShiftSwap.objects.select_for_update().get(pk=swap.pk)
        if swap.status != ShiftSwap.Status.REQUESTED:
            raise DomainError(_("This request has already been answered."))
        if swap.target_id != by.pk:
            raise PermissionDenied(_("This request is for someone else."))
        swap.status = ShiftSwap.Status.REJECTED
        swap.decided_by = by.user
        swap.decided_at = timezone.now()
        swap.decision_note = _("Declined by %(name)s") % {"name": by}
        swap.save(
            update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"]
        )
        inbox.settle(swap, outcome=gettext_lazy("Declined"), by=by)
        swap_id = swap.pk
        transaction.on_commit(lambda: notify.swap_closed(swap_id))
    _bump(swap.company_id, PULSE_SWAPS)
    return swap


def cancel_swap(swap: ShiftSwap, *, by: Membership) -> ShiftSwap:
    """The person who asked takes it back (before it's approved)."""
    with transaction.atomic():
        swap = ShiftSwap.objects.select_for_update().get(pk=swap.pk)
        if swap.requested_by_id != by.pk:
            raise PermissionDenied(_("Only the person who asked can cancel it."))
        if not swap.is_open:
            raise DomainError(_("This request is already closed."))
        swap.status = ShiftSwap.Status.CANCELLED
        swap.decided_by = by.user
        swap.decided_at = timezone.now()
        swap.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
        inbox.settle(swap, outcome=gettext_lazy("Cancelled"), by=by)
        swap_id = swap.pk
        transaction.on_commit(lambda: notify.swap_closed(swap_id))
    _bump(swap.company_id, PULSE_SWAPS)
    return swap


def claim_open_shift(shift: WorkShift, *, by: Membership, now: datetime | None = None) -> ShiftSwap:
    """Take an open shift. Without required approval the first claim gets it; otherwise
    claims wait for a manager, who picks one."""
    company = shift.company
    _ensure_module(company)
    now = now or timezone.now()
    settings = conf.get_settings(company)
    with transaction.atomic():
        shift = (
            WorkShift.objects.select_for_update(of=("self",))
            .select_related("company")
            .get(pk=shift.pk)
        )
        if (
            shift.status != WorkShift.Status.OPEN
            or shift.membership_id is not None
            or not shift.is_published
        ):
            raise DomainError(_("Someone has already taken this shift."))
        if shift.starts_at <= now:
            raise DomainError(_("This shift has already started."))
        existing = ShiftSwap.objects.filter(
            shift=shift, requested_by=by, status__in=ShiftSwap.OPEN_STATUSES
        ).first()
        if existing is not None:
            return existing
        if not queries.is_eligible(shift, by):
            raise DomainError(_("You can't take this shift."))
        swap = ShiftSwap.objects.create(
            company=company,
            shift=shift,
            requested_by=by,
            kind=ShiftSwap.Kind.CLAIM,
            accepted_by=by,
            status=ShiftSwap.Status.ACCEPTED,
            expires_at=shift.starts_at,
        )
        if not settings.open_shift_claim_needs_approval:
            _apply_swap(swap, by=None, now=now)
            inbox.settle(shift, outcome=gettext_lazy("Taken"), by=by)
        else:
            swap_id = swap.pk
            transaction.on_commit(lambda: notify.swap_waiting(swap_id))
    _bump(company.pk, PULSE_SWAPS, PULSE_ROSTER)
    return swap


def decide_swap(
    swap: ShiftSwap, *, by: Membership | None, approve: bool, reason: str = ""
) -> ShiftSwap:
    """A manager approves (the shift moves and both people are told) or rejects."""
    _require(by, Perm.ATTENDANCE_MANAGE, swap.shift.branch_id)
    if not approve:
        reason = _reason(reason)
    with transaction.atomic():
        swap = (
            ShiftSwap.objects.select_for_update(of=("self",))
            .select_related("shift", "other_shift", "requested_by", "accepted_by")
            .get(pk=swap.pk)
        )
        if swap.status != ShiftSwap.Status.ACCEPTED:
            raise DomainError(_("This request isn't waiting for approval."))
        if approve:
            _apply_swap(swap, by=by, now=timezone.now())
        else:
            swap.status = ShiftSwap.Status.REJECTED
            swap.decided_by = by.user if by else None
            swap.decided_at = timezone.now()
            swap.decision_note = reason
            swap.save()
            _audit(by, AttendanceAction.SWAP_REJECTED, swap, reason=reason)
            swap_id = swap.pk
            transaction.on_commit(lambda: notify.swap_closed(swap_id))
        inbox.settle(swap, outcome=APPROVED_TEXT if approve else REJECTED_TEXT, by=by)
    _bump(swap.company_id, PULSE_SWAPS, PULSE_ROSTER)
    return swap


def _apply_swap(swap: ShiftSwap, *, by: Membership | None, now: datetime) -> None:
    """Move the shift(s) (source `swap`), close the other requests on them and tell both
    people after commit."""
    ids = [swap.shift_id] + ([swap.other_shift_id] if swap.other_shift_id else [])
    shifts = {
        shift.pk: shift
        for shift in WorkShift.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    }
    shift = shifts[swap.shift_id]
    if shift.starts_at <= now:
        raise DomainError(_("This shift has already started."))
    taker = swap.accepted_by
    if swap.kind == ShiftSwap.Kind.CLAIM:
        if shift.status != WorkShift.Status.OPEN or shift.membership_id is not None:
            raise DomainError(_("Someone has already taken this shift."))
        _check_free(taker, shift.starts_at, shift.ends_at, exclude=shift)
        shift.membership = taker
        shift.status = WorkShift.Status.PLANNED
        shift.source = WorkShift.Source.SWAP
        shift.save()
    elif swap.kind == ShiftSwap.Kind.COVER:
        if shift.membership_id != swap.requested_by_id or shift.status != WorkShift.Status.PLANNED:
            raise DomainError(_("This shift has changed since the request."))
        _check_free(taker, shift.starts_at, shift.ends_at, exclude=shift)
        shift.membership = taker
        shift.source = WorkShift.Source.SWAP
        shift.save()
    else:
        other = shifts[swap.other_shift_id]
        if (
            shift.membership_id != swap.requested_by_id
            or other.membership_id != taker.pk
            or other.starts_at <= now
        ):
            raise DomainError(_("These shifts have changed since the request."))
        mine, theirs = shift.membership, other.membership
        # Through an empty owner first, so the one-shift-per-start constraint never trips.
        shift.membership = None
        shift.status = WorkShift.Status.OPEN
        shift.save()
        other.membership = mine
        other.source = WorkShift.Source.SWAP
        other.save()
        shift.membership = theirs
        shift.status = WorkShift.Status.PLANNED
        shift.source = WorkShift.Source.SWAP
        shift.save()
    swap.status = ShiftSwap.Status.APPROVED
    swap.decided_by = by.user if by else None
    swap.decided_at = now
    swap.save()
    # Other claims of the same open shift, and other requests on these shifts, are over.
    others = ShiftSwap.objects.filter(
        Q(shift_id__in=ids) | Q(other_shift_id__in=ids), status__in=ShiftSwap.OPEN_STATUSES
    ).exclude(pk=swap.pk)
    closed = list(others.values_list("pk", flat=True))
    others.update(
        status=ShiftSwap.Status.REJECTED,
        decided_at=now,
        decision_note=_("Another colleague took this shift."),
        updated_at=now,
    )
    if by is not None:
        _audit(by, AttendanceAction.SWAP_APPROVED, swap, kind=swap.kind, to=str(taker))
    swap_id = swap.pk
    transaction.on_commit(lambda: notify.swap_approved(swap_id, closed))


def _cancel_open_swaps(shift_ids: list[int], *, by: Membership | None) -> int:
    rows = ShiftSwap.objects.filter(
        Q(shift_id__in=shift_ids) | Q(other_shift_id__in=shift_ids),
        status__in=ShiftSwap.OPEN_STATUSES,
    )
    ids = list(rows.values_list("pk", flat=True))
    if not ids:
        return 0
    now = timezone.now()
    rows.update(
        status=ShiftSwap.Status.CANCELLED,
        decided_at=now,
        decision_note=_("The shift changed."),
        updated_at=now,
    )
    for swap in ShiftSwap.objects.filter(pk__in=ids):
        inbox.settle(swap, outcome=gettext_lazy("Cancelled"), by=by)
    transaction.on_commit(lambda: [notify.swap_closed(pk) for pk in ids])
    return len(ids)


def expire_swaps(now: datetime | None = None) -> int:
    """Requests whose shift has started lapse; the people involved are told."""
    now = now or timezone.now()
    rows = ShiftSwap.objects.filter(status__in=ShiftSwap.OPEN_STATUSES, expires_at__lte=now)
    ids = list(rows.values_list("pk", flat=True))
    if not ids:
        return 0
    with transaction.atomic():
        companies = set(rows.values_list("company_id", flat=True))
        ShiftSwap.objects.filter(pk__in=ids).update(
            status=ShiftSwap.Status.EXPIRED, decided_at=now, updated_at=now
        )
        for swap in ShiftSwap.objects.filter(pk__in=ids):
            inbox.settle(swap, outcome=gettext_lazy("Expired"))
        transaction.on_commit(lambda: [notify.swap_closed(pk) for pk in ids])
        for company_id in companies:
            _bump(company_id, PULSE_SWAPS)
    return len(ids)


# Periodic closing -----------------------------------------------------------------------


def auto_close(company: Company, now: datetime | None = None) -> int:
    """Close forgotten check-outs: a shift's record `auto_close_after_hours` after the shift
    ends (at the shift's end), an unscheduled one 16 hours after its check-in (with no worked
    time, so nobody is paid for a guess). Flagged, and the person is asked to correct it."""
    now = now or timezone.now()
    settings = conf.get_settings(company)
    late = now - timedelta(hours=settings.auto_close_after_hours)
    stale = AttendanceRecord.objects.filter(
        company=company, status=AttendanceRecord.Status.OPEN
    ).filter(
        Q(shift__isnull=False, shift__ends_at__lte=late)
        | Q(
            shift__isnull=True,
            check_in_at__lte=now - timedelta(hours=rules.UNSCHEDULED_AUTO_CLOSE_HOURS),
        )
    )
    closed = 0
    for record_id in list(stale.values_list("pk", flat=True)):
        with transaction.atomic():
            record = (
                AttendanceRecord.objects.select_for_update(of=("self",))
                .select_related("shift")
                .filter(pk=record_id, status=AttendanceRecord.Status.OPEN)
                .first()
            )
            if record is None:
                continue
            end = record.shift.ends_at if record.shift else record.check_in_at
            record.check_out_at = max(end, record.check_in_at)
            record.status = AttendanceRecord.Status.AUTO_CLOSED
            record.out_source = Source.SYSTEM
            rules.add_flag(record, Flag.AUTO_CLOSED)
            rules.compute(record, settings)
            record.save()
            transaction.on_commit(lambda pk=record.pk: notify.auto_closed(pk))
            closed += 1
    if closed:
        _bump(company.pk, PULSE_BOARD)
    return closed


ABSENCE_LOOKBACK_DAYS = 7


def mark_absences(company: Company, now: datetime | None = None) -> int:
    """Past published shifts nobody checked in for become absences, once the local time is
    past 03:00 and the shift has ended. People suspended that day, on leave or gone are left
    alone. Idempotent: a shift with any record is skipped (and the constraint guards)."""
    now = now or timezone.now()
    local = clock.local(company, now)
    if local.hour < 3:
        return 0
    today = local.date()
    shifts = (
        WorkShift.objects.working()
        .filter(
            company=company,
            date__lt=today,
            date__gte=today - timedelta(days=ABSENCE_LOOKBACK_DAYS),
            ends_at__lte=now,
        )
        .exclude(pk__in=AttendanceRecord.objects.filter(shift__isnull=False).values("shift_id"))
        .select_related("membership")
    )
    marked = 0
    for shift in shifts:
        member = shift.membership
        if member.status not in queries.STAFF_STATUSES or queries.is_suspended_on(
            member, shift.date
        ):
            continue
        time_off = queries.on_leave(member, shift.date)
        if time_off is not None:
            WorkShift.objects.filter(pk=shift.pk).update(
                status=WorkShift.Status.LEAVE, time_off=time_off, updated_at=now
            )
            continue
        try:
            with transaction.atomic():
                AttendanceRecord.objects.create(
                    company=company,
                    membership=member,
                    shift=shift,
                    date=shift.date,
                    status=AttendanceRecord.Status.ABSENT,
                    branch=shift.branch,
                )
            marked += 1
        except IntegrityError:
            continue
    if marked:
        _bump(company.pk, PULSE_BOARD)
    return marked


def say_off_today(membership: Membership, shift: WorkShift) -> bool:
    """ "I'm off today" from a missed-start nudge: managers hear it now (instead of the later
    no-show alert). Returns False when it was already said."""
    if shift.membership_id != membership.pk:
        raise PermissionDenied(_("That isn't your shift."))
    if not notify.mark_once(shift.company_id, f"off:{shift.pk}"):
        return False
    notify.mark_once(shift.company_id, f"noshow:{shift.pk}")
    transaction.on_commit(lambda: notify.no_show(shift.pk, True))
    return True


# Receivers ------------------------------------------------------------------------------


def time_off_approved(time_off: TimeOff) -> int:
    """Approved time off turns the person's planned shifts in its days into leave (open
    swaps on them end) and their absences into excused days."""
    member = time_off.membership
    with transaction.atomic():
        shifts = WorkShift.objects.filter(
            membership=member,
            date__range=(time_off.first_day, time_off.last_day),
            status=WorkShift.Status.PLANNED,
        ).exclude(
            pk__in=AttendanceRecord.objects.filter(
                shift__isnull=False, status__in=AttendanceRecord.ATTENDED
            ).values("shift_id")
        )
        ids = list(shifts.values_list("pk", flat=True))
        _cancel_open_swaps(ids, by=None)
        WorkShift.objects.filter(pk__in=ids).update(
            status=WorkShift.Status.LEAVE, time_off=time_off, updated_at=timezone.now()
        )
        AttendanceRecord.objects.filter(
            membership=member,
            date__range=(time_off.first_day, time_off.last_day),
            status=AttendanceRecord.Status.ABSENT,
        ).update(status=AttendanceRecord.Status.EXCUSED, updated_at=timezone.now())
    _bump(member.company_id, PULSE_ROSTER, PULSE_BOARD)
    return len(ids)


def time_off_cancelled(time_off: TimeOff, previous_status: str | None = None) -> int:
    """Cancelled or revoked time off gives the person back their coming shifts."""
    if previous_status not in (None, TimeOff.Status.APPROVED):
        return 0
    today = clock.today(time_off.company)
    count = WorkShift.objects.filter(
        time_off=time_off, status=WorkShift.Status.LEAVE, date__gte=today
    ).update(status=WorkShift.Status.PLANNED, time_off=None, updated_at=timezone.now())
    if count:
        _bump(time_off.company_id, PULSE_ROSTER)
    return count


def member_left(membership: Membership, *, by: Membership | None = None) -> dict:
    """Someone left or was blocked: their open check-in is closed, their future shifts are
    cancelled (drafts removed) and their open swap requests end."""
    now = timezone.now()
    settings = conf.get_settings(membership.company)
    with transaction.atomic():
        record = queries.open_record(membership)
        if record is not None:
            record.check_out_at = max(now, record.check_in_at)
            record.status = AttendanceRecord.Status.CLOSED
            record.out_source = Source.SYSTEM
            rules.add_flag(record, Flag.EDITED)
            rules.compute(record, settings)
            record.save()
        future = WorkShift.objects.filter(membership=membership, starts_at__gt=now).exclude(
            status=WorkShift.Status.CANCELLED
        )
        ids = list(future.values_list("pk", flat=True))
        _cancel_open_swaps(ids, by=by)
        WorkShift.objects.filter(pk__in=ids, published_at__isnull=True).delete()
        cancelled = WorkShift.objects.filter(pk__in=ids).update(
            status=WorkShift.Status.CANCELLED, updated_at=now
        )
        swaps = ShiftSwap.objects.filter(
            Q(requested_by=membership) | Q(target=membership) | Q(accepted_by=membership),
            status__in=ShiftSwap.OPEN_STATUSES,
        )
        swap_ids = list(swaps.values_list("pk", flat=True))
        swaps.update(status=ShiftSwap.Status.CANCELLED, decided_at=now, updated_at=now)
        for swap in ShiftSwap.objects.filter(pk__in=swap_ids):
            inbox.settle(swap, outcome=gettext_lazy("Cancelled"), by=by)
    _bump(membership.company_id, PULSE_ROSTER, PULSE_BOARD, PULSE_SWAPS)
    return {"closed_record": record is not None, "shifts": cancelled, "swaps": len(swap_ids)}


def holidays_between(company: Company, start: date, end: date) -> set[date]:
    return set(
        Holiday.objects.filter(company=company, date__range=(start, end)).values_list(
            "date", flat=True
        )
    )
