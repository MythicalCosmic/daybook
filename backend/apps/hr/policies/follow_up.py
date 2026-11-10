"""What runs by itself for policies: the beat job every 15 minutes, and the notices after a
publish or after someone joins.

For every company with HR on and a policy that asks for signatures:

1. each policy's request follows who it applies to (newcomers to a position or a branch are
   asked, people it no longer applies to are released); always, even in quiet hours;
2. then, outside the company's quiet hours (the hours and days of its default reminder policy,
   as every other reminder): everyone asked and not told yet hears (one message per policy, or
   one for several); a reminder goes out on the day before the deadline (or on the last day, when
   the day before was the day they were asked); and from the day after the deadline, each late
   person's manager hears, once per person.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.companies.models import Company
from apps.hr.models import Policy, PolicyAcknowledgement
from apps.hr.policies import notify, queries, services
from apps.members.models import Membership

APPROVED = Membership.Status.APPROVED


def quiet_end(company, now: datetime) -> datetime | None:
    """When the company's quiet hours end, if they are on now."""
    from apps.reminders.policies import default_policy
    from apps.reminders.schedule import quiet_until

    local = timezone.localtime(now, ZoneInfo(company.timezone))
    return quiet_until(local, default_policy(company.pk))


def follow_up(now: datetime | None = None) -> int:
    """The beat job over every company; returns the messages made."""
    now = now or timezone.now()
    asking = Policy.objects.filter(
        is_active=True, requires_ack=True, current_version__isnull=False
    ).values("company_id")
    sent = 0
    for company in Company.objects.filter(is_active=True, pk__in=asking):
        if company.has_feature("hr"):
            sent += follow_up_company(company, now)
    return sent


def follow_up_company(company, now: datetime) -> int:
    services.sync_company(company, now=now)
    if quiet_end(company, now) is not None:
        return 0
    return tell_pending(company, now) + remind_due(company, now) + late_notes(company, now)


def _owed(company):
    """The open rows of every current request of the company, of people working now."""
    return PolicyAcknowledgement.objects.filter(
        version__company_id=company.pk,
        version_id=F("version__policy__ack_version_id"),
        version__policy__is_active=True,
        version__policy__requires_ack=True,
        membership__status=APPROVED,
        acknowledged_at__isnull=True,
    ).select_related(
        "membership__user", "membership__company", "membership__home_branch", "version__policy"
    )


def tell_pending(company, now: datetime, *, policy_id: int | None = None) -> int:
    """Everyone asked and not told yet hears (and is marked told, whatever their preference)."""
    rows = _owed(company).filter(notified_at__isnull=True)
    if policy_id is not None:
        rows = rows.filter(version__policy_id=policy_id)
    rows = list(rows)
    if not rows:
        return 0
    with transaction.atomic():
        sent = notify.tell(rows)
        PolicyAcknowledgement.objects.filter(pk__in=[row.pk for row in rows]).update(
            notified_at=now
        )
    return sent


def remind_due(company, now: datetime) -> int:
    """One reminder before the deadline: on the day before it, or on the last day when the day
    before was the day they were asked (or the reminder couldn't go then)."""
    today = queries.today(company, now)
    rows = _owed(company).filter(
        notified_at__isnull=False, due_on__gte=today, due_on__lte=today + timedelta(days=1)
    )
    due = []
    for row in rows:
        if queries.today(company, row.asked_at) >= today:
            continue  # asked today: the message they just had is enough
        if row.reminded_at is not None and queries.today(company, row.reminded_at) >= (
            row.due_on - timedelta(days=1)
        ):
            continue  # reminded already since the day before the deadline
        due.append(row)
    if not due:
        return 0
    with transaction.atomic():
        sent = sum(notify.remind(row, today, now, manual=False) for row in due)
        PolicyAcknowledgement.objects.filter(pk__in=[row.pk for row in due]).update(reminded_at=now)
    return sent


def late_notes(company, now: datetime) -> int:
    """The day after the deadline, each late person's manager hears (once per person)."""
    today = queries.today(company, now)
    rows = list(
        _owed(company).filter(
            notified_at__isnull=False, late_notified_at__isnull=True, due_on__lt=today
        )
    )
    if not rows:
        return 0
    by_policy: dict[int, list[PolicyAcknowledgement]] = {}
    for row in rows:
        by_policy.setdefault(row.version.policy_id, []).append(row)
    sent = 0
    with transaction.atomic():
        for items in by_policy.values():
            sent += notify.late(items[0].version.policy, items)
        PolicyAcknowledgement.objects.filter(pk__in=[row.pk for row in rows]).update(
            late_notified_at=now
        )
    return sent


def notices_after_publish(policy_id: int, now: datetime | None = None) -> int:
    """Right after a publish (or a change that asked more people): the people asked hear now,
    or the beat tells them once the quiet hours are over. A policy that only asks to be read
    tells its readers now, or at the end of the quiet hours."""
    from apps.hr import tasks

    now = now or timezone.now()
    policy = (
        Policy.objects.filter(pk=policy_id, is_active=True, current_version__isnull=False)
        .select_related("company", "current_version")
        .prefetch_related("positions", "branches")
        .first()
    )
    if policy is None or not policy.company.has_feature("hr"):
        return 0
    end = quiet_end(policy.company, now)
    if policy.requires_ack:
        return 0 if end is not None else tell_pending(policy.company, now, policy_id=policy.pk)
    if end is not None:
        tasks.policy_to_read.apply_async((policy.pk, policy.current_version_id), eta=end)
        return 0
    return to_read(policy.pk, policy.current_version_id)


def to_read(policy_id: int, version_id: int) -> int:
    """The readers of a policy that asks no signature hear about its version `version_id`
    (unless a newer one came out since)."""
    policy = (
        Policy.objects.filter(pk=policy_id, is_active=True, current_version_id=version_id)
        .select_related("current_version")
        .prefetch_related("positions", "branches")
        .first()
    )
    if policy is None or policy.requires_ack:
        return 0
    people = queries.audience(policy).select_related("user", "company")
    return notify.to_read(policy.current_version, people)


def after_joining(company_id: int) -> int:
    """Someone was approved: the policies of their position and branches ask them now."""
    company = Company.objects.filter(pk=company_id, is_active=True).first()
    if company is None or not company.has_feature("hr"):
        return 0
    now = timezone.now()
    services.sync_company(company, now=now)
    if quiet_end(company, now) is not None:
        return 0
    return tell_pending(company, now)
