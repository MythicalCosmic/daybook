"""The hourly look at contracts (`tasks.watch_contracts`), for each active company that has any:

1. `maintain`, at any hour: an auto-renewing contract past its last day moves on by whole terms
   (`services.renew_by_itself`), and every status follows its dates (`services.refresh_status`):
   active, ending, ended, terminated.
2. `remind`, from the company's morning report time (`Company.morning_report_at`, its timezone):
   - a contract that doesn't renew by itself: from `ContractSettings.remind_days` before its
     last day ("soon"), and once more on the day ("today");
   - an auto-renewing one: from `notice_remind_days` before its notice deadline, and on the
     deadline itself, until someone confirms the renewal; and the morning after it renewed by
     itself (up to three days late, if the job was down).

Each reminder goes out once: the keys of the ones sent are kept on the contract
(`reminders_sent`, "<what>:<day>:<step>"), the day in them makes a renewed term's reminders new
ones. A run that finds a contract past several steps announces the tightest one and marks the
others. One company's failure is logged and never stops the others.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.companies.models import Company
from apps.contracts import conf, notify, services
from apps.contracts.models import BusinessContract, ContractSettings
from apps.contracts.services import reminder_key

logger = logging.getLogger(__name__)

Status = BusinessContract.Status
RENEWED_GRACE_DAYS = 3
KEEP_KEYS_DAYS = 400  # older keys are dropped, so the list stays short over the years


def companies():
    return (
        Company.objects.filter(is_active=True, business_contracts__isnull=False)
        .distinct()
        .order_by("pk")
    )


def watch_all(now: datetime | None = None) -> int:
    now = now or timezone.now()
    total = 0
    for company in companies():
        try:
            total += watch_company(company, now)
        except Exception:
            logger.exception("contracts watch failed for company %s", company.pk)
    return total


def watch_company(company: Company, now: datetime) -> int:
    """Statuses and renewals now; reminders once the company's morning has come."""
    local = timezone.localtime(now, ZoneInfo(company.timezone))
    today = local.date()
    settings = conf.get_settings(company)
    changed = maintain(company, today, settings)
    if changed:
        services._bump(company)
    if local.time() < company.morning_report_at:
        return 0
    return remind(company, today, settings)


def maintain(company: Company, today: date, settings: ContractSettings) -> int:
    moved = 0
    rows = (
        BusinessContract.objects.for_company(company)
        .filter(status__in=BusinessContract.IN_FORCE)
        .select_related("company")
    )
    for contract in rows:
        with transaction.atomic():
            renewed = services.renew_by_itself(contract, today, settings)
            if renewed or services.refresh_status(contract, today, settings):
                moved += 1
    return moved


def remind(company: Company, today: date, settings: ContractSettings) -> int:
    sent = 0
    rows = (
        BusinessContract.objects.for_company(company)
        .filter(status__in=BusinessContract.IN_FORCE, ends_on__isnull=False)
        .select_related("company", "branch", "counterparty", "responsible")
    )
    for contract in rows:
        sent += remind_one(contract, today, settings)
    return sent


def step(days_left: int, warn_days: int) -> str | None:
    """ "today" on the day, "soon" within the warning days, else nothing."""
    if days_left == 0:
        return "today"
    if 0 < days_left <= warn_days:
        return "soon"
    return None


def remind_one(contract: BusinessContract, today: date, settings: ContractSettings) -> int:
    done = set(contract.reminders_sent or [])
    new: list[str] = []
    sent = 0
    with transaction.atomic():
        if not contract.auto_renews:
            end = contract.ends_on
            found = step((end - today).days, settings.remind_days)
            if found is not None and reminder_key("end", end, found) not in done:
                sent += notify.ending(contract, found, today)
                new += [reminder_key("end", end, "soon"), reminder_key("end", end, found)]
        else:
            renewed = contract.last_renewed_on
            key = reminder_key("renewed", contract.ends_on, "auto")
            if (
                renewed is not None
                and 0 <= (today - renewed).days <= RENEWED_GRACE_DAYS
                and key not in done
            ):
                sent += notify.renewed(contract)
                new.append(key)
            deadline = contract.notice_deadline
            if contract.renewal_confirmed_for != contract.ends_on:
                found = step((deadline - today).days, settings.notice_remind_days)
                if found is not None and reminder_key("notice", deadline, found) not in done:
                    sent += notify.notice(contract, found, today)
                    new += [
                        reminder_key("notice", deadline, "soon"),
                        reminder_key("notice", deadline, found),
                    ]
        if new:
            keep = _recent(done | set(new), today)
            BusinessContract.objects.filter(pk=contract.pk).update(reminders_sent=keep)
            contract.reminders_sent = keep
    return sent


def _recent(keys: set[str], today: date) -> list[str]:
    oldest = today - timedelta(days=KEEP_KEYS_DAYS)
    kept = []
    for key in keys:
        try:
            day = date.fromisoformat(key.split(":")[1])
        except IndexError, ValueError:
            continue
        if day >= oldest:
            kept.append(key)
    return sorted(kept)
