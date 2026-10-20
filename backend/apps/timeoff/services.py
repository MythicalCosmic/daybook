from datetime import date, datetime, time, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members import services as members
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks.models import Task
from apps.timeoff import tasks as jobs
from apps.timeoff.models import TimeOff

MAX_DAYS = 60
TAKEN = (TimeOff.Status.PENDING, TimeOff.Status.APPROVED)


@transaction.atomic
def request_time_off(
    member: Membership, *, first_day: date, last_day: date, reason: str = ""
) -> TimeOff:
    """Ask for days off. Someone who approves time off themselves just takes it."""
    if member.status != Membership.Status.APPROVED or not member.is_onboarded:
        raise DomainError(_("Finish registration first."))
    if last_day < first_day:
        raise DomainError(_("The last day can't be before the first one."))
    if first_day < _today(member):
        raise DomainError(_("Time off can't start in the past."))
    if (last_day - first_day).days + 1 > MAX_DAYS:
        raise DomainError(_("Ask for at most %(days)d days at a time.") % {"days": MAX_DAYS})
    overlapping = TimeOff.objects.filter(
        membership=member, status__in=TAKEN, first_day__lte=last_day, last_day__gte=first_day
    )
    if overlapping.exists():
        raise DomainError(_("You've already asked for some of these days."))

    time_off = TimeOff.objects.create(
        company_id=member.company_id,
        membership=member,
        first_day=first_day,
        last_day=last_day,
        reason=reason.strip()[:300],
    )
    if member.has_perm(Perm.TIME_OFF_APPROVE):
        _settle(time_off, TimeOff.Status.APPROVED, member.user)
    else:
        transaction.on_commit(partial(jobs.notify_time_off_requested.delay, time_off.pk))
    return time_off


@transaction.atomic
def decide(time_off_id: int, approve: bool, *, by: User) -> TimeOff:
    time_off = (
        TimeOff.objects.select_for_update()
        .select_related("company", "membership__user")
        .filter(pk=time_off_id)
        .first()
    )
    if time_off is None:
        raise DomainError(_("This request no longer exists."))
    members.ensure_can(by, time_off.company, Perm.TIME_OFF_APPROVE)
    if time_off.membership.user_id == by.pk:
        raise PermissionDenied(_("Someone else has to decide on your own time off."))
    if time_off.status != TimeOff.Status.PENDING:
        raise DomainError(_already(time_off))
    _settle(time_off, TimeOff.Status.APPROVED if approve else TimeOff.Status.REJECTED, by)
    transaction.on_commit(partial(jobs.notify_time_off_decided.delay, time_off.pk))
    return time_off


@transaction.atomic
def cancel(time_off: TimeOff, *, by: Membership) -> TimeOff:
    time_off = TimeOff.objects.select_for_update().get(pk=time_off.pk)
    if time_off.membership_id != by.pk:
        raise PermissionDenied(_("Only the person who asked can cancel this."))
    if time_off.status not in TAKEN:
        raise DomainError(_already(time_off))
    if time_off.status == TimeOff.Status.APPROVED and time_off.first_day <= _today(by):
        raise DomainError(_("Time off that has already started can't be cancelled."))
    time_off.status = TimeOff.Status.CANCELLED
    time_off.save(update_fields=["status", "updated_at"])
    return time_off


def get(time_off_id: int) -> TimeOff | None:
    return (
        TimeOff.objects.select_related("company", "membership__user", "decided_by")
        .filter(pk=time_off_id)
        .first()
    )


def _settle(time_off: TimeOff, status: TimeOff.Status, by: User) -> None:
    time_off.status = status
    time_off.decided_by = by
    time_off.decided_at = timezone.now()
    time_off.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    action = (
        AuditLog.Action.TIME_OFF_APPROVED
        if status == TimeOff.Status.APPROVED
        else AuditLog.Action.TIME_OFF_REJECTED
    )
    audit.record(
        action,
        company_id=time_off.company_id,
        actor=by,
        target=time_off,
        first_day=time_off.first_day.isoformat(),
        last_day=time_off.last_day.isoformat(),
    )
    if status == TimeOff.Status.APPROVED:
        _cancel_todays_daily_tasks(time_off)


def _cancel_todays_daily_tasks(time_off: TimeOff) -> None:
    """Approved for today, after today's daily tasks were made: take them off the list."""
    member = time_off.membership
    today = _today(member)
    if not time_off.first_day <= today <= time_off.last_day:
        return
    start = datetime.combine(today, time.min, tzinfo=ZoneInfo(member.company.timezone))
    Task.objects.filter(
        assignee=member,
        kind=Task.Kind.DAILY,
        status__in=Task.OPEN_STATUSES,
        due_at__gte=start,
        due_at__lt=start + timedelta(days=1),
    ).update(status=Task.Status.CANCELLED, next_reminder_at=None)


def _today(member: Membership) -> date:
    return timezone.localdate(timezone=ZoneInfo(member.company.timezone))


def _already(time_off: TimeOff) -> str:
    return _("This request is already %(status)s.") % {
        "status": time_off.get_status_display().lower()
    }
