"""What payroll's Celery jobs do (`tasks.py` wraps them), a plain module: each runs often and
acts once per company and day or month, in the company's own calendar. Companies with the
payroll module switched off are skipped."""

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.companies.models import Company
from apps.core.exceptions import DomainError
from apps.payroll import conf, notify, periods, rules
from apps.payroll.models import PayrollRun, PayrollSettings

logger = logging.getLogger(__name__)

PREPARE_FROM_HOUR = 6
REMIND_HOURS = range(8, 13)
DAILY_RULES_FROM_HOUR = 4  # after attendance closed yesterday (it acts after 03:00)


def _companies():
    return Company.objects.filter(is_active=True, features__contains=["payroll"])


def prepare_runs(now: datetime | None = None) -> int:
    """On the 1st after 06:00 local: last month's draft run, calculated, and the people who
    finalize payroll told. Once: a run for the month already there (even cancelled by hand
    afterwards, the job doesn't make another) stops it."""
    from apps.payroll import services

    now = now or timezone.now()
    made = 0
    for company in _companies():
        local = periods.local(company, now)
        if local.day != 1 or local.hour < PREPARE_FROM_HOUR:
            continue
        if not conf.get_settings(company).auto_prepare:
            continue
        period = periods.previous_period(local.date())
        if (
            PayrollRun.objects.for_company(company)
            .filter(kind=PayrollRun.Kind.REGULAR, period=period)
            .exists()
        ):
            continue
        try:
            with transaction.atomic():
                run = services.create_run(company, by=None, period=period)
                notify.run_prepared(run)
        except DomainError as exc:
            logger.warning("Payroll for %s of company %s not prepared: %s", period, company.pk, exc)
            continue
        made += 1
    return made


def pay_day_reminders(now: datetime | None = None) -> int:
    """Pay day morning, last month not paid yet: the payers and owners hear, once a month."""
    now = now or timezone.now()
    sent = 0
    for company in _companies():
        local = periods.local(company, now)
        settings_row = conf.get_settings(company)
        if local.day != settings_row.pay_day or local.hour not in REMIND_HOURS:
            continue
        period = periods.previous_period(local.date())
        if settings_row.reminded_period == period:
            continue
        run = (
            PayrollRun.objects.for_company(company)
            .filter(kind=PayrollRun.Kind.REGULAR, period=period)
            .exclude(status=PayrollRun.Status.CANCELLED)
            .first()
        )
        with transaction.atomic():
            updated = (
                PayrollSettings.objects.filter(pk=settings_row.pk)
                .exclude(reminded_period=period)
                .update(reminded_period=period)
            )
            if not updated:
                continue
            if run is not None and run.status == PayrollRun.Status.PAID:
                continue
            notify.pay_day(run, company, period)
        sent += 1
    return sent


def evaluate_daily_rules(now: datetime | None = None) -> int:
    """Once a company day after 04:00 local: yesterday's daily rules (per-unit bonuses and
    fines) proposed for this month, never twice (`rule_key`)."""
    now = now or timezone.now()
    changed = 0
    for company in _companies():
        local = periods.local(company, now)
        if local.hour < DAILY_RULES_FROM_HOUR:
            continue
        changed += rules.evaluate_daily(company, local.date(), now=now)
    return changed
