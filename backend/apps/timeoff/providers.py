"""What time off hands to the shared registries (registered in hooks.py): Needs you items,
inbox action handlers, calendar dates, the offboarding step, person fields, exports and the
private file check."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.console.registry import CalendarItem, OffboardStep, QueueAction, QueueItem
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.timeoff import bot_messages, queries, services
from apps.timeoff.models import Holiday, TimeOff


def _today(company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


# Needs you -----------------------------------------------------------------------------


def queue_count(member: Membership) -> int:
    return queries.pending_count(member)


def queue_items(member: Membership, limit: int) -> list[QueueItem]:
    rows = (
        queries.pending_for(member)
        .select_related("membership__user", "membership__position")
        .order_by("created_at")[:limit]
    )
    items = []
    for time_off in rows:
        dates = bot_messages.dates(time_off)
        subtitle = _("%(dates)s · %(count)d days") % {"dates": dates, "count": time_off.days}
        if time_off.reason:
            subtitle = f"{subtitle} · {time_off.reason}"
        items.append(
            QueueItem(
                kind="timeoff.request",
                id=time_off.pk,
                title=_("%(name)s asks for time off") % {"name": time_off.membership},
                subtitle=subtitle,
                created_at=time_off.created_at,
                url=f"time-off?request={time_off.pk}",
                actions=(
                    QueueAction(
                        "approve",
                        _("Approve"),
                        "primary",
                        "POST",
                        f"time-off/{time_off.pk}/approve/",
                    ),
                    QueueAction(
                        "reject", _("Reject"), "danger", "POST", f"time-off/{time_off.pk}/reject/"
                    ),
                ),
            )
        )
    return items


# Inbox buttons (the Telegram copies of requests) ----------------------------------------


def _target(notification) -> TimeOff:
    time_off = TimeOff.objects.filter(
        pk=notification.target_id, company_id=notification.company_id
    ).first()
    if time_off is None:
        from apps.core.exceptions import DomainError

        raise DomainError(_("This request no longer exists."))
    return time_off


def approve_from_inbox(notification, by: Membership, reason: str) -> str:
    services.decide(_target(notification).pk, True, by=by.user)
    return _("Approved")


def reject_from_inbox(notification, by: Membership, reason: str) -> str:
    services.decide(_target(notification).pk, False, by=by.user)
    return _("Rejected")


# Company calendar (apps.agenda) ------------------------------------------------------------


def calendar_time_off(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    rows = (
        queries.visible(member)
        .filter(status__in=queries.SHOWN, first_day__lte=end, last_day__gte=start)
        .select_related("membership__user")
        .order_by("first_day")
    )
    return [
        CalendarItem(
            id=f"timeoff:{row.pk}",
            kind="timeoff.time_off",
            title=(
                _("%(name)s · time off")
                if row.status == TimeOff.Status.APPROVED
                else _("%(name)s · asks for time off")
            )
            % {"name": row.membership},
            start=row.first_day,
            end=row.last_day,
            all_day=True,
            color="var(--c-chart-3)"
            if row.status == TimeOff.Status.APPROVED
            else "var(--c-warning)",
            url=f"time-off?request={row.pk}",
        )
        for row in rows
    ]


def calendar_holidays(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    return [
        CalendarItem(
            id=f"holiday:{holiday.pk}",
            kind="timeoff.holiday",
            title=holiday.name,
            start=holiday.date,
            end=holiday.date,
            all_day=True,
            color="var(--c-chart-1)",
            url="time-off/holidays",
        )
        for holiday in Holiday.objects.filter(company=company, date__range=(start, end))
    ]


# Offboarding wizard ----------------------------------------------------------------------


def offboard_step(membership: Membership) -> OffboardStep:
    """Time off that ends with the person: future approved days and open requests."""
    today = _today(membership.company)
    rows = TimeOff.objects.filter(
        membership=membership,
        status__in=(TimeOff.Status.PENDING, TimeOff.Status.APPROVED),
        last_day__gte=today,
    ).order_by("first_day")
    lines = []
    for row in rows:
        if row.status == TimeOff.Status.APPROVED:
            lines.append(
                _("Approved time off %(dates)s will be cancelled.")
                % {"dates": bot_messages.dates(row)}
            )
        else:
            lines.append(
                _("Their request for %(dates)s will be dropped.")
                % {"dates": bot_messages.dates(row)}
            )
    if not lines:
        lines.append(_("No time off planned."))
    return OffboardStep(lines=lines, blockers=[], fields=[], defaults={})


# Person fields (directory status chip) ---------------------------------------------------


def person_fields(company, member_ids: list[int], now: datetime) -> dict[int, dict]:
    off = queries.off_on(
        company, timezone.localtime(now, ZoneInfo(company.timezone)).date(), member_ids
    )
    return {member_id: {"time_off_today": off.get(member_id)} for member_id in member_ids}


# Export ---------------------------------------------------------------------------------


EXPORT_COLUMNS = [
    ("member", gettext_lazy("Person")),
    ("position", gettext_lazy("Position")),
    ("first_day", gettext_lazy("First day"), "date"),
    ("last_day", gettext_lazy("Last day"), "date"),
    ("days", gettext_lazy("Days"), "number"),
    ("status", gettext_lazy("Status")),
    ("reason", gettext_lazy("Reason")),
    ("recorded_by", gettext_lazy("Recorded by")),
    ("decided_by", gettext_lazy("Decided by")),
]


def export_rows(member: Membership, params: dict):
    rows = queries.visible(member).select_related(
        "membership__position", "recorded_by", "decided_by"
    )
    start, end = params.get("from"), params.get("to")
    if start:
        rows = rows.filter(last_day__gte=start)
    if end:
        rows = rows.filter(first_day__lte=end)
    statuses = params.get("status")
    if statuses:
        rows = rows.filter(status__in=statuses if isinstance(statuses, list) else [statuses])
    for row in rows.order_by("first_day"):
        yield {
            "member": str(row.membership),
            "position": row.membership.position.name if row.membership.position_id else "",
            "first_day": row.first_day,
            "last_day": row.last_day,
            "days": row.days,
            "status": row.get_status_display(),
            "reason": row.reason,
            "recorded_by": str(row.recorded_by) if row.recorded_by else "",
            "decided_by": row.decided_by.get_full_name() if row.decided_by else "",
        }


# Private files --------------------------------------------------------------------------


def may_open_attachment(user, company_id, object_id) -> bool:
    time_off = (
        TimeOff.objects.for_company(company_id)
        .filter(pk=int(object_id))
        .select_related("membership")
        .first()
    )
    if time_off is None:
        return False
    viewer = (
        Membership.objects.select_related("role", "company")
        .filter(company_id=company_id, user=user, status=Membership.Status.APPROVED)
        .first()
    )
    if viewer is None:
        return False
    if time_off.membership_id == viewer.pk:
        return True
    if not viewer.has_perm(Perm.TIME_OFF_APPROVE):
        return False
    branches = scope.branch_ids(viewer)
    return branches is None or time_off.membership.branches.filter(pk__in=branches).exists()


def history_check(member: Membership, target_id: int) -> bool:
    return queries.visible(member).filter(pk=target_id).exists()
