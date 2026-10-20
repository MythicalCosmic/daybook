"""What attendance hands to the shared registries (wired in `hooks.py`): "Needs you" items,
the offboarding step, calendar dates, the setup step, the timesheet exporter, the copy-setup
part and the selfie file check."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l
from rest_framework import serializers

from apps.attendance import bot_messages, clock, queries
from apps.attendance.models import (
    AttendanceRecord,
    MemberSchedule,
    ShiftSwap,
    ShiftTemplate,
    WorkSchedule,
    WorkScheduleDay,
    WorkShift,
)
from apps.console.registry import CalendarItem, OffboardStep, QueueAction, QueueItem
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm


def _name(member: Membership | None) -> str:
    return (member.full_name or str(member.user)) if member is not None else "—"


def _decide(path: str) -> list[QueueAction]:
    return [
        QueueAction("approve", _("Approve"), "primary", "POST", path, body={"approve": True}),
        QueueAction(
            "reject",
            _("Reject"),
            "danger",
            "POST",
            path,
            body={"approve": False},
            needs_reason=True,
        ),
    ]


# Needs you ------------------------------------------------------------------------------


def correction_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    items = []
    for row in queries.pending_corrections(member).order_by("created_at")[:limit]:
        times = []
        if row.check_in_at:
            times.append(_("came %(time)s") % {"time": clock.hhmm(company, row.check_in_at)})
        if row.check_out_at:
            times.append(_("left %(time)s") % {"time": clock.hhmm(company, row.check_out_at)})
        items.append(
            QueueItem(
                kind="attendance.corrections",
                id=row.pk,
                title=_("%(name)s · %(date)s: %(times)s")
                % {
                    "name": _name(row.membership),
                    "date": clock.day_month(row.date),
                    "times": ", ".join(times),
                },
                subtitle=row.reason,
                created_at=row.created_at,
                url=f"/c/{company.pk}/attendance/corrections?correction={row.pk}",
                actions=_decide(f"attendance/corrections/{row.pk}/decide/"),
            )
        )
    return items


def overtime_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    items = []
    for record in queries.pending_overtime(member).order_by("check_out_at")[:limit]:
        items.append(
            QueueItem(
                kind="attendance.overtime",
                id=record.pk,
                title=_("%(name)s · %(date)s: %(extra)s overtime")
                % {
                    "name": _name(record.membership),
                    "date": clock.day_month(record.date),
                    "extra": bot_messages.duration(record.overtime_minutes),
                },
                subtitle=_("Checked in %(start)s, out %(end)s")
                % {
                    "start": clock.hhmm(company, record.check_in_at),
                    "end": clock.hhmm(company, record.check_out_at),
                },
                created_at=record.check_out_at,
                url=f"/c/{company.pk}/attendance/corrections?tab=overtime&record={record.pk}",
                actions=_decide(f"attendance/records/{record.pk}/overtime/"),
            )
        )
    return items


def swap_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    items = []
    for swap in queries.pending_swaps(member).order_by("expires_at")[:limit]:
        shift = bot_messages.shift_line(swap.shift)
        if swap.kind == ShiftSwap.Kind.CLAIM:
            title = _("%(name)s wants the open shift %(shift)s") % {
                "name": _name(swap.accepted_by),
                "shift": shift,
            }
        elif swap.kind == ShiftSwap.Kind.SWAP:
            title = _("%(a)s ⇄ %(b)s: %(shift)s") % {
                "a": _name(swap.requested_by),
                "b": _name(swap.accepted_by),
                "shift": shift,
            }
        else:
            title = _("%(b)s covers %(a)s: %(shift)s") % {
                "a": _name(swap.requested_by),
                "b": _name(swap.accepted_by),
                "shift": shift,
            }
        path = f"attendance/swaps/{swap.pk}/"
        items.append(
            QueueItem(
                kind="attendance.swaps",
                id=swap.pk,
                title=title,
                subtitle=swap.note,
                created_at=swap.updated_at,
                url=f"/c/{company.pk}/attendance/swaps?swap={swap.pk}",
                actions=[
                    QueueAction("approve", _("Approve"), "primary", "POST", path + "approve/"),
                    QueueAction(
                        "reject", _("Reject"), "danger", "POST", path + "reject/", needs_reason=True
                    ),
                ],
            )
        )
    return items


# Offboarding ----------------------------------------------------------------------------


def offboard_preview(membership: Membership) -> OffboardStep:
    """What leaving does to attendance: future shifts cancelled, open swaps ended, an open
    check-in closed."""
    now = timezone.now()
    lines = []
    future = (
        WorkShift.objects.filter(membership=membership, starts_at__gt=now)
        .exclude(status=WorkShift.Status.CANCELLED)
        .count()
    )
    if future:
        lines.append(_("%(count)s coming shifts will be cancelled.") % {"count": future})
    swaps = (
        ShiftSwap.objects.filter(status__in=ShiftSwap.OPEN_STATUSES)
        .filter(requested_by=membership)
        .count()
        + ShiftSwap.objects.filter(
            status__in=ShiftSwap.OPEN_STATUSES, accepted_by=membership
        ).count()
    )
    if swaps:
        lines.append(_("%(count)s open swap requests will be cancelled.") % {"count": swaps})
    record = queries.open_record(membership)
    if record is not None:
        lines.append(
            _("Checked in since %(time)s: the check-in will be closed now.")
            % {"time": clock.hhmm(membership.company, record.check_in_at)}
        )
    schedule = (
        MemberSchedule.objects.filter(membership=membership, schedule__isnull=False)
        .select_related("schedule")
        .first()
    )
    if schedule is not None:
        lines.append(_("Follows the schedule “%(name)s”.") % {"name": schedule.schedule.name})
    if not lines:
        lines.append(_("No coming shifts or open requests."))
    return OffboardStep(lines=lines, blockers=[], fields=[], defaults={})


# Calendar -------------------------------------------------------------------------------


def calendar_events(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """The member's own shifts, and for `attendance.view` holders the number of people on
    shift per branch and day."""
    items = []
    for shift in (
        WorkShift.objects.live()
        .filter(company=company, membership=member, date__range=(start, end))
        .exclude(status=WorkShift.Status.OPEN)
        .select_related("branch")
    ):
        title = _("Shift") if shift.status == WorkShift.Status.PLANNED else _("Leave")
        if shift.branch_id:
            title = f"{title} · {shift.branch.name}"
        items.append(
            CalendarItem(
                id=f"shift-{shift.pk}",
                kind="attendance.shift",
                title=title,
                start=clock.local(company, shift.starts_at),
                end=clock.local(company, shift.ends_at),
                all_day=False,
                color="chart-3" if shift.status == WorkShift.Status.PLANNED else "chart-8",
                url=f"/c/{company.pk}/attendance/roster?week={clock.week_start(shift.date).isoformat()}",
            )
        )
    if member.has_perm(Perm.ATTENDANCE_VIEW):
        shifts = scope.restrict(
            WorkShift.objects.working().filter(company=company, date__range=(start, end)),
            scope.branch_ids(member),
        )
        counts: dict[tuple[date, int | None, str], int] = {}
        for day, branch_id, branch_name in shifts.values_list("date", "branch_id", "branch__name"):
            key = (day, branch_id, branch_name or "")
            counts[key] = counts.get(key, 0) + 1
        for (day, branch_id, branch_name), count in sorted(
            counts.items(), key=lambda kv: (kv[0][0], kv[0][2])
        ):
            items.append(
                CalendarItem(
                    id=f"cover-{day.isoformat()}-{branch_id}",
                    kind="attendance.coverage",
                    title=_("%(branch)s: %(count)s on shift")
                    % {"branch": branch_name or "—", "count": count},
                    start=day,
                    end=None,
                    all_day=True,
                    color="chart-6",
                    url=f"/c/{company.pk}/attendance/roster?week={clock.week_start(day).isoformat()}"
                    + (f"&branch={branch_id}" if branch_id else ""),
                )
            )
    return items


# Setup, copy, files ---------------------------------------------------------------------


def setup_done(company) -> bool:
    return MemberSchedule.objects.filter(
        company=company, schedule__isnull=False, schedule__is_active=True
    ).exists()


def copy_setup(source, target, by: Membership) -> int:
    """Copy work schedules (with their days) and shift templates. People's assignments are
    never copied."""
    made = 0
    for schedule in WorkSchedule.objects.filter(company=source, is_active=True).prefetch_related(
        "days"
    ):
        if WorkSchedule.objects.filter(company=target, name=schedule.name, is_active=True).exists():
            continue
        days = list(schedule.days.all())
        schedule.pk = None
        schedule.company = target
        schedule.save()
        WorkScheduleDay.objects.bulk_create(
            WorkScheduleDay(
                schedule=schedule,
                weekday=day.weekday,
                starts_at=day.starts_at,
                ends_at=day.ends_at,
                break_minutes=day.break_minutes,
            )
            for day in days
        )
        made += 1
    for template in ShiftTemplate.objects.filter(company=source, is_active=True):
        if ShiftTemplate.objects.filter(company=target, name=template.name).exists():
            continue
        ShiftTemplate.objects.create(
            company=target,
            name=template.name,
            starts_at=template.starts_at,
            ends_at=template.ends_at,
            break_minutes=template.break_minutes,
            color=template.color,
            order=template.order,
        )
        made += 1
    return made


def selfie_check(user, company_id, object_id) -> bool:
    """A check-in selfie opens for its person, or for `attendance.view` holders who see the
    record's branch."""
    record = (
        AttendanceRecord.objects.for_company(company_id)
        .filter(pk=object_id)
        .select_related("membership")
        .first()
    )
    if record is None:
        return False
    if record.membership.user_id == user.pk:
        return True
    viewer = (
        Membership.objects.filter(
            company_id=company_id, user=user, status=Membership.Status.APPROVED
        )
        .select_related("role", "company")
        .first()
    )
    return (
        viewer is not None
        and viewer.has_perm(Perm.ATTENDANCE_VIEW)
        and scope.allows(scope.branch_ids(viewer), record.branch_id)
    )


# The timesheet exporter -----------------------------------------------------------------


class TimesheetExportParams(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    month = serializers.CharField(required=False, max_length=7)
    branch = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs.get("start") and attrs.get("end") and attrs["end"] < attrs["start"]:
            raise serializers.ValidationError({"end": _("The last day can't be before the first.")})
        return attrs


TIMESHEET_COLUMNS = [
    ("date", _l("Date"), "date"),
    ("person", _l("Person")),
    ("position", _l("Position")),
    ("branch", _l("Branch")),
    ("shift", _l("Shift")),
    ("status", _l("Status")),
    ("check_in", _l("Check-in"), "datetime"),
    ("check_out", _l("Check-out"), "datetime"),
    ("worked_hours", _l("Worked hours"), "number"),
    ("late_minutes", _l("Late, min"), "number"),
    ("early_leave_minutes", _l("Left early, min"), "number"),
    ("overtime_minutes", _l("Overtime, min"), "number"),
    ("overtime_status", _l("Overtime")),
    ("distance_m", _l("Distance, m"), "number"),
    ("flags", _l("Flags")),
]


def timesheet_rows(member: Membership, params: dict):
    """One row per record (absences included) in the period and the member's scope."""
    company = member.company
    today = clock.today(company)
    if params.get("month"):
        try:
            first = datetime.strptime(params["month"][:7], "%Y-%m").date()
        except ValueError:
            first = today.replace(day=1)
        start, end = queries.month_bounds(first)
    else:
        start = params.get("start") or today.replace(day=1)
        end = params.get("end") or today
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    end = min(end, start + timedelta(days=366))
    records = queries.records_between(company, start, end, branch_ids=scope.branch_ids(member))
    if params.get("branch"):
        records = records.filter(branch_id=params["branch"])
    statuses = dict(AttendanceRecord.Status.choices)
    overtime = dict(AttendanceRecord.Overtime.choices)
    flags = dict(AttendanceRecord.Flag.choices)
    for record in records.order_by("date", "membership__first_name", "check_in_at"):
        shift = record.shift
        yield {
            "date": record.date,
            "person": _name(record.membership),
            "position": record.membership.position.name if record.membership.position_id else "",
            "branch": record.branch.name if record.branch_id else "",
            "shift": f"{clock.hhmm(company, shift.starts_at)}–{clock.hhmm(company, shift.ends_at)}"
            if shift
            else "",
            "status": str(statuses.get(record.status, record.status)),
            "check_in": record.check_in_at,
            "check_out": record.check_out_at,
            "worked_hours": f"{record.worked_minutes / 60:.2f}",
            "late_minutes": record.late_minutes,
            "early_leave_minutes": record.early_leave_minutes,
            "overtime_minutes": record.overtime_minutes,
            "overtime_status": str(overtime.get(record.overtime_status, ""))
            if record.overtime_minutes
            else "",
            "distance_m": record.in_distance_m,
            "flags": ", ".join(str(flags.get(flag, flag)) for flag in record.flags),
        }
