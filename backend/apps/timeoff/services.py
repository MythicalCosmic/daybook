"""Time off: requests and decisions, time off recorded for someone, revoking approved time off,
and the company's holidays. Every change is audited; side effects run after commit."""

from datetime import date, datetime, time, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Company
from apps.core.exceptions import DomainError
from apps.core.signals import send_on_commit
from apps.core.uploads import accept_document
from apps.inbox import services as inbox
from apps.members import scope
from apps.members import services as members
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks.models import Task
from apps.timeoff import tasks as jobs
from apps.timeoff.audit_actions import TimeOffAuditAction
from apps.timeoff.models import Holiday, TimeOff
from apps.timeoff.signals import time_off_approved, time_off_cancelled

MAX_DAYS = 60
# Time off recorded for someone may reach this far back and be this long.
MAX_RECORD_DAYS = 366
TAKEN = (TimeOff.Status.PENDING, TimeOff.Status.APPROVED)
REQUEST_KIND = "timeoff.request"
APPROVED = gettext_lazy("Approved")
REJECTED = gettext_lazy("Rejected")
CANCELLED = gettext_lazy("Cancelled")

# Uzbekistan's public holidays on fixed dates (month, day, name). Ramazon and Qurbon hayiti
# move with the lunar calendar; the government announces them each year.
PUBLIC_HOLIDAYS = (
    (1, 1, gettext_lazy("New Year")),
    (3, 8, gettext_lazy("International Women's Day")),
    (3, 21, gettext_lazy("Navruz")),
    (5, 9, gettext_lazy("Day of Remembrance and Honour")),
    (9, 1, gettext_lazy("Independence Day")),
    (10, 1, gettext_lazy("Teachers' Day")),
    (12, 8, gettext_lazy("Constitution Day")),
)


# Requests -------------------------------------------------------------------------------


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
    if _overlapping(member, first_day, last_day).exists():
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
    """Approve or reject a pending request (from the bot, Needs you or the dashboard). Every
    approver's copy of the request, in the dashboard and in Telegram, shows the outcome."""
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
    acting = members.get_membership(by, time_off.company)
    if acting is not None and not _in_scope(acting, time_off.membership):
        raise PermissionDenied(_("This person works in a branch you don't manage."))
    _settle(time_off, TimeOff.Status.APPROVED if approve else TimeOff.Status.REJECTED, by)
    inbox.settle(
        time_off,
        outcome=APPROVED if approve else REJECTED,
        by=acting if acting is not None and acting.status == Membership.Status.APPROVED else None,
        kind=REQUEST_KIND,
    )
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
    previous_status = time_off.status
    time_off.status = TimeOff.Status.CANCELLED
    time_off.save(update_fields=["status", "updated_at"])
    if previous_status == TimeOff.Status.PENDING:
        inbox.settle(time_off, outcome=CANCELLED, by=None, kind=REQUEST_KIND)
    send_on_commit(
        time_off_cancelled,
        sender=TimeOff,
        time_off=time_off,
        by=by,
        previous_status=previous_status,
    )
    return time_off


def get(time_off_id: int) -> TimeOff | None:
    return (
        TimeOff.objects.select_related("company", "membership__user", "decided_by")
        .filter(pk=time_off_id)
        .first()
    )


# Recording and revoking (owner console) -------------------------------------------------


@transaction.atomic
def record_time_off(
    member: Membership,
    *,
    by: Membership,
    first_day: date,
    last_day: date,
    reason: str = "",
    attachment=None,
) -> TimeOff:
    """Record days off for someone, approved at once: sick leave after the fact, a day off
    agreed in person. Past days are allowed, back to the last finalized payroll period and at
    most 366 days; `attachment` (a sick note: PDF or photo) is stored privately."""
    member = Membership.objects.select_for_update(of=("self",)).get(pk=member.pk)
    _ensure_approver(by, member.company_id)
    if member.company_id != by.company_id:
        raise PermissionDenied(_("You don't have permission to do this."))
    if member.status != Membership.Status.APPROVED:
        raise DomainError(_("Time off can only be recorded for current members."))
    if not _in_scope(by, member):
        raise PermissionDenied(_("This person works in a branch you don't manage."))
    if last_day < first_day:
        raise DomainError(_("The last day can't be before the first one."))
    if (last_day - first_day).days + 1 > MAX_RECORD_DAYS:
        raise DomainError(_("Record at most %(days)d days at a time.") % {"days": MAX_RECORD_DAYS})
    today = _today(member)
    if first_day < today - timedelta(days=MAX_RECORD_DAYS):
        raise DomainError(_("Time off can be recorded at most a year back."))
    locked_until = payroll_locked_until(member.company)
    if locked_until is not None and first_day <= locked_until:
        raise DomainError(
            _("Payroll is already finalized up to %(date)s; pick days after it.")
            % {"date": locked_until.strftime("%d.%m.%Y")}
        )
    clash = _overlapping(member, first_day, last_day).order_by("first_day").first()
    if clash is not None:
        raise DomainError(
            _("%(name)s already has time off on some of these days (%(dates)s).")
            % {"name": member, "dates": _span(clash.first_day, clash.last_day)}
        )

    now = timezone.now()
    time_off = TimeOff(
        company_id=member.company_id,
        membership=member,
        first_day=first_day,
        last_day=last_day,
        reason=reason.strip()[:300],
        status=TimeOff.Status.APPROVED,
        decided_by=by.user,
        decided_at=now,
        recorded_by=by,
    )
    if attachment is not None:
        document = accept_document(attachment, allowed=("pdf", "image"))
        time_off.attachment.save(document.name, document, save=False)
    time_off.save()
    audit.record(
        TimeOffAuditAction.RECORDED,
        company_id=time_off.company_id,
        actor=by.user,
        target=time_off,
        member=str(member),
        first_day=first_day.isoformat(),
        last_day=last_day.isoformat(),
        reason=time_off.reason,
    )
    _cancel_todays_daily_tasks(time_off)
    send_on_commit(time_off_approved, sender=TimeOff, time_off=time_off, by=by)
    transaction.on_commit(partial(jobs.notify_time_off_recorded.delay, time_off.pk))
    return time_off


@transaction.atomic
def revoke(
    time_off: TimeOff, *, by: Membership, reason: str, from_day: date | None = None
) -> TimeOff:
    """Take back approved time off. Before it starts it is cancelled; once it has started (or
    when `from_day` falls inside it) it now ends the day before `from_day` (today by default)
    and the rest is cancelled. `time_off_cancelled` carries the cut days."""
    time_off = (
        TimeOff.objects.select_for_update(of=("self",))
        .select_related("company", "membership__user")
        .get(pk=time_off.pk)
    )
    _ensure_approver(by, time_off.company_id)
    if not _in_scope(by, time_off.membership):
        raise PermissionDenied(_("This person works in a branch you don't manage."))
    if time_off.status != TimeOff.Status.APPROVED:
        raise DomainError(_("Only approved time off can be revoked."))
    reason = reason.strip()
    if not reason:
        raise DomainError(_("Say why the time off is revoked."))
    today = _today(time_off.membership)
    if from_day is None:
        from_day = max(time_off.first_day, today)
    if from_day > time_off.last_day:
        raise DomainError(_("This time off ends before that day; there is nothing to revoke."))

    cut_from = max(from_day, time_off.first_day)
    cut_to = time_off.last_day
    locked_until = payroll_locked_until(time_off.company)
    if locked_until is not None and cut_from <= locked_until:
        raise DomainError(
            _("Payroll is already finalized up to %(date)s; pick days after it.")
            % {"date": locked_until.strftime("%d.%m.%Y")}
        )
    if from_day <= time_off.first_day:
        time_off.status = TimeOff.Status.CANCELLED
    else:
        time_off.last_day = from_day - timedelta(days=1)
    time_off.revoked_at = timezone.now()
    time_off.revoked_by = by.user
    time_off.revoke_reason = reason[:300]
    time_off.save(
        update_fields=[
            "status",
            "last_day",
            "revoked_at",
            "revoked_by",
            "revoke_reason",
            "updated_at",
        ]
    )
    audit.record(
        TimeOffAuditAction.REVOKED,
        company_id=time_off.company_id,
        actor=by.user,
        target=time_off,
        member=str(time_off.membership),
        cancelled_from=cut_from.isoformat(),
        cancelled_to=cut_to.isoformat(),
        reason=time_off.revoke_reason,
    )
    send_on_commit(
        time_off_cancelled,
        sender=TimeOff,
        time_off=time_off,
        by=by,
        previous_status=TimeOff.Status.APPROVED,
        cancelled_from=cut_from,
        cancelled_to=cut_to,
    )
    transaction.on_commit(partial(jobs.notify_time_off_revoked.delay, time_off.pk))
    return time_off


def payroll_locked_until(company: Company) -> date | None:
    """The last day of the last finalized payroll period, when payroll says so (package H's
    `payroll.queries.finalized_until(company)`); None until then."""
    try:
        from apps.payroll import queries as payroll_queries
    except ImportError:  # pragma: no cover - the app always exists
        return None
    finalized_until = getattr(payroll_queries, "finalized_until", None)
    return finalized_until(company) if callable(finalized_until) else None


# Holidays ------------------------------------------------------------------------------


@transaction.atomic
def create_holiday(company: Company, *, by: Membership, date: date, name: str) -> Holiday:
    """A day the whole company is off: no daily tasks, no reminders, never counted as leave."""
    _ensure_approver(by, company.pk)
    name = _holiday_name(name)
    if Holiday.objects.for_company(company).filter(date=date).exists():
        raise DomainError(_("There is already a holiday on that day."))
    try:
        with transaction.atomic():
            holiday = Holiday.objects.create(company=company, date=date, name=name)
    except IntegrityError:
        raise DomainError(_("There is already a holiday on that day.")) from None
    audit.record(
        TimeOffAuditAction.HOLIDAY_ADDED,
        company_id=company.pk,
        actor=by.user,
        target=holiday,
        date=date.isoformat(),
        name=name,
    )
    return holiday


@transaction.atomic
def update_holiday(
    holiday: Holiday, *, by: Membership, date: date | None = None, name: str | None = None
) -> Holiday:
    holiday = Holiday.objects.select_for_update().get(pk=holiday.pk)
    _ensure_approver(by, holiday.company_id)
    changes = {}
    if name is not None and _holiday_name(name) != holiday.name:
        changes["name"] = [holiday.name, _holiday_name(name)]
        holiday.name = _holiday_name(name)
    if date is not None and date != holiday.date:
        taken = Holiday.objects.filter(company_id=holiday.company_id, date=date)
        if taken.exclude(pk=holiday.pk).exists():
            raise DomainError(_("There is already a holiday on that day."))
        changes["date"] = [holiday.date.isoformat(), date.isoformat()]
        holiday.date = date
    if not changes:
        return holiday
    holiday.save()
    audit.record(
        TimeOffAuditAction.HOLIDAY_CHANGED,
        company_id=holiday.company_id,
        actor=by.user,
        target=holiday,
        changes=changes,
    )
    return holiday


@transaction.atomic
def delete_holiday(holiday: Holiday, *, by: Membership) -> None:
    holiday = Holiday.objects.select_for_update().get(pk=holiday.pk)
    _ensure_approver(by, holiday.company_id)
    audit.record(
        TimeOffAuditAction.HOLIDAY_REMOVED,
        company_id=holiday.company_id,
        actor=by.user,
        target=holiday,
        date=holiday.date.isoformat(),
        name=holiday.name,
    )
    holiday.delete()


@transaction.atomic
def add_public_holidays(company: Company, *, by: Membership, year: int) -> list[Holiday]:
    """Uzbekistan's fixed public holidays of `year` that the company doesn't have yet."""
    _ensure_approver(by, company.pk)
    if not 2000 <= year <= 2100:
        raise DomainError(_("Pick a year between 2000 and 2100."))
    taken = set(
        Holiday.objects.for_company(company).filter(date__year=year).values_list("date", flat=True)
    )
    added = []
    for month, day, name in PUBLIC_HOLIDAYS:
        when = date(year, month, day)
        if when in taken:
            continue
        added.append(create_holiday(company, by=by, date=when, name=str(name)))
    return added


# Helpers --------------------------------------------------------------------------------


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
        acting = members.get_membership(by, time_off.company)
        send_on_commit(
            time_off_approved,
            sender=TimeOff,
            time_off=time_off,
            by=acting if acting is not None and acting.has_perm(Perm.TIME_OFF_APPROVE) else None,
        )


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


def _overlapping(member: Membership, first_day: date, last_day: date):
    return TimeOff.objects.filter(
        membership=member, status__in=TAKEN, first_day__lte=last_day, last_day__gte=first_day
    )


def _ensure_approver(by: Membership, company_id: int) -> None:
    if by.company_id != company_id or not by.has_perm(Perm.TIME_OFF_APPROVE):
        raise PermissionDenied(_("You don't have permission to do this."))


def _in_scope(viewer: Membership, member: Membership) -> bool:
    """Whether `viewer` may act on `member`'s time off: their own, or someone sharing one of
    the branches they see (everyone when their scope is every branch)."""
    if viewer.pk == member.pk:
        return True
    branches = scope.branch_ids(viewer)
    if branches is None:
        return True
    return member.branches.filter(pk__in=branches).exists()


def _holiday_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise DomainError(_("Name the holiday."))
    return name[:100]


def _span(first: date, last: date) -> str:
    return f"{first:%d.%m}" if first == last else f"{first:%d.%m}–{last:%d.%m}"


def _today(member: Membership) -> date:
    return timezone.localdate(timezone=ZoneInfo(member.company.timezone))


def _already(time_off: TimeOff) -> str:
    return _("This request is already %(status)s.") % {
        "status": time_off.get_status_display().lower()
    }
