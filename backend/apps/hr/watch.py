"""The periodic work behind HR's Celery tasks (docs/PLAN-OWNER.md §10.1).

- `watch_expiries` (hourly): from each company's morning report time on, documents, contracts
  in force and probations that reach a warning step (the company's warning days, 7 and 0
  days before their day) reach HR, once per item and step. The steps already sent are kept on
  the item (`expiry_notified`, `end_notified`, `probation_notified`); a run that finds an item
  past several steps announces the tightest one and marks them all.
- `post_celebrations` (every 15 minutes): in the three hours after the morning report time,
  today's birthdays and work anniversaries are posted to the groups that want them and the
  person is greeted, once per celebration.

- `watch_coverage` (every 5 minutes, docs/PLAN-OWNER.md §14.9): a pharmacy open with fewer
  qualified pharmacists checked in than it needs, for `coverage_alert_minutes`, reaches its
  manager and the owners (critical, once per branch and gap); so does a till opened by someone
  who isn't a qualified pharmacist (once per till shift).
- `watch_planned_coverage` (hourly): gaps in the published roster of the next `coverage_days`
  reach whoever runs the roster at that branch (a warning, once per gap). Days past the last
  published shift of a branch aren't planned yet and stay quiet; a gap already under way is the
  live check's.

Every job walks the active companies with HR switched on; one company's failure is logged and
never stops the others. The coverage jobs do nothing until the rule is set up
(`conf.coverage_settings`).
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
from apps.hr import bot_messages, conf, coverage, notify, overview, queries
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


# Pharmacist coverage ---------------------------------------------------------------------------

# A till shift that opened and closed between two runs is still told about.
SELLER_WINDOW = timedelta(minutes=15)


def watch_coverage(now: datetime | None = None) -> int:
    return _each(coverage_company, now)


def coverage_company(company: Company, now: datetime) -> int:
    settings = conf.coverage_settings(company)
    if settings is None:
        return 0
    branches = {branch.pk: branch for branch in coverage.pharmacies(company, branch_ids=None)}
    wait = timedelta(minutes=settings.coverage_alert_minutes)
    sent = 0
    for gap in coverage.live(company, now):
        if now - gap.since < wait or gap.branch_id not in branches:
            continue
        names = [
            str(person)
            for person in Membership.objects.filter(pk__in=gap.others).order_by(
                "first_name", "last_name", "pk"
            )
        ]
        sent += notify.coverage_gap_live(branches[gap.branch_id], gap, names)
    tz = ZoneInfo(company.timezone)
    day = timezone.localtime(now, tz).date()
    for row in coverage.unqualified_sellers(company, day, branch_ids=None):
        if row["status"] != "open" and now - row["opened_at"] > SELLER_WINDOW:
            continue
        branch = branches.get(row["branch_id"])
        if branch is not None:
            sent += notify.unqualified_seller(branch, row, timezone.localtime(row["opened_at"], tz))
    return sent


def watch_planned_coverage(now: datetime | None = None) -> int:
    return _each(planned_company, now)


def planned_company(company: Company, now: datetime) -> int:
    from apps.attendance import queries as attendance

    settings = conf.coverage_settings(company)
    if settings is None:
        return 0
    branches = {branch.pk: branch for branch in coverage.pharmacies(company, branch_ids=None)}
    recipients: dict[int, list[Membership]] = {}
    sent = 0
    for gap in coverage.upcoming(company, now, settings.coverage_days, branch_ids=None):
        if gap.start <= now or gap.branch_id not in branches:
            continue  # under way: the live check has it
        if gap.branch_id not in recipients:
            recipients[gap.branch_id] = attendance.managers_for(company, gap.branch_id)
        monday = gap.start.date() - timedelta(days=gap.start.weekday())
        sent += notify.coverage_gap_planned(
            branches[gap.branch_id], gap, recipients[gap.branch_id], monday.isoformat()
        )
    return sent


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
