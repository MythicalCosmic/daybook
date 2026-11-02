"""The periodic work behind HR's Celery tasks (docs/PLAN-OWNER.md §10.1).

- `watch_expiries` (hourly): from each company's morning report time on, documents, contracts
  in force and probations that reach a warning step (the company's warning days, 7 and 0
  days before their day) reach HR, once per item and step. The steps already sent are kept on
  the item (`expiry_notified`, `end_notified`, `probation_notified`); a run that finds an item
  past several steps announces the tightest one and marks them all.
- `post_celebrations` (every 15 minutes): in the three hours after the morning report time,
  today's birthdays and work anniversaries are posted to the groups that want them and the
  person is greeted, once per celebration.

Every job walks the active companies with HR switched on; one company's failure is logged and
never stops the others.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone, translation

from apps.companies.models import Company
from apps.groups.models import GroupEvent
from apps.groups.services import broadcast
from apps.hr import bot_messages, conf, notify, overview, queries
from apps.hr.models import Celebration
from apps.members.models import Membership

logger = logging.getLogger(__name__)

# An item first seen this many days after its day is marked as told, not announced: someone
# entering an old, long-expired document doesn't need the news.
EXPIRED_GRACE_DAYS = 14
CELEBRATION_WINDOW = timedelta(hours=3)


def companies():
    return Company.objects.filter(is_active=True, features__contains=["hr"]).order_by("pk")


def _each(job: Callable[[Company, datetime], int], now: datetime | None = None) -> int:
    now = now or timezone.now()
    total = 0
    for company in companies():
        try:
            total += job(company, now) or 0
        except Exception:
            logger.exception("hr job %s failed for company %s", job.__name__, company.pk)
    return total


def steps(warn_days: int) -> list[int]:
    """The warning steps, furthest first: the warning days, a week, the day itself."""
    return sorted({value for value in (warn_days, 7, 0) if value <= warn_days}, reverse=True)


def due(days_left: int, warn_days: int, done: list[int]) -> tuple[int | None, list[int]]:
    """(the step to announce now, or None; the steps counted as told afterwards)."""
    crossed = [step for step in steps(warn_days) if days_left <= step]
    marked = sorted(set(done) | set(crossed), reverse=True)
    if not crossed or min(crossed) in done or days_left < -EXPIRED_GRACE_DAYS:
        return None, marked
    return min(crossed), marked


# Expiries -----------------------------------------------------------------------------------


def watch_expiries(now: datetime | None = None) -> int:
    return _each(watch_company, now)


def watch_company(company: Company, now: datetime) -> int:
    local = timezone.localtime(now, ZoneInfo(company.timezone))
    if local.time() < company.morning_report_at:
        return 0  # people hear it in the morning, not in the night
    day = local.date()
    settings = conf.get_settings(company)
    sent = 0
    documents = queries.expiring_documents(
        company, branch_ids=None, day=day, within=settings.document_warn_days
    ).select_related("membership__company")
    for document in documents:
        sent += _step(
            document,
            "expiry_notified",
            (document.expires_on - day).days,
            settings.document_warn_days,
            lambda step, item=document: notify.document_expiring(item, step, day),
        )
    ending = queries.ending_contracts(
        company, branch_ids=None, day=day, within=settings.contract_warn_days
    ).select_related("membership__company")
    for contract in ending.filter(membership__status__in=queries.CURRENT):
        sent += _step(
            contract,
            "end_notified",
            (contract.ends_on - day).days,
            settings.contract_warn_days,
            lambda step, item=contract: notify.contract_ending(item, step, day),
        )
    probations = queries.probation_endings(
        company, branch_ids=None, day=day, within=settings.probation_warn_days
    ).select_related("membership__company")
    for contract in probations.filter(membership__status__in=queries.CURRENT):
        sent += _step(
            contract,
            "probation_notified",
            (contract.probation_until - day).days,
            settings.probation_warn_days,
            lambda step, item=contract: notify.probation_ending(item, step, day),
        )
    return sent


def _step(item, field: str, days_left: int, warn_days: int, announce) -> int:
    done = list(getattr(item, field) or [])
    step, marked = due(days_left, warn_days, done)
    if step is None and marked == sorted(done, reverse=True):
        return 0
    with transaction.atomic():
        type(item).objects.filter(pk=item.pk).update(**{field: marked})
        return announce(step) if step is not None else 0


# Celebrations ----------------------------------------------------------------------------------


def post_celebrations(now: datetime | None = None) -> int:
    return _each(celebrate_company, now)


def celebrate_company(company: Company, now: datetime) -> int:
    settings = conf.get_settings(company)
    if not settings.celebrations_enabled:
        return 0
    tz = ZoneInfo(company.timezone)
    local = timezone.localtime(now, tz)
    start = datetime.combine(local.date(), company.morning_report_at, tzinfo=tz)
    if not start <= local < start + CELEBRATION_WINDOW:
        return 0
    day = local.date()
    people = queries.people(
        company, branch_ids=None, statuses=(Membership.Status.APPROVED,)
    ).select_related("user", "company", "position")
    rows = overview.celebrations_between(
        company, people, day, day, anniversaries=settings.celebrate_anniversaries
    )
    posted = 0
    for row in rows:
        posted += _celebrate(company, row, now)
    return posted


def _celebrate(company: Company, row: dict, now: datetime) -> int:
    member = row["member"]
    with transaction.atomic():
        celebration, _created = Celebration.objects.select_for_update().get_or_create(
            membership=member,
            kind=row["kind"],
            day=row["date"],
            defaults={"company_id": company.pk, "years": row["years"]},
        )
        if celebration.posted_at is not None:
            return 0
        Celebration.objects.filter(pk=celebration.pk).update(posted_at=now)
        with translation.override(company.default_language):
            if row["kind"] == Celebration.Kind.BIRTHDAY:
                text = bot_messages.birthday_post(str(member))
            else:
                text = bot_messages.anniversary_post(str(member), row["years"])
        broadcast(
            company.pk,
            GroupEvent.CELEBRATIONS,
            text,
            position_ids=[member.position_id] if member.position_id else [],
            branch_id=member.home_branch_id,
        )
        notify.greet(celebration)
    return 1
