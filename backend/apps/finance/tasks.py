"""Celery tasks of the finance ledger, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.finance import alerts, cbu

logger = logging.getLogger(__name__)


@shared_task
def fetch_exchange_rates() -> dict:
    """Hourly 08:00-18:00 Tashkent: today's Central Bank rates until they are stored (and
    yesterday's, when a quiet night left it missing). Keeps the last rate on failure: the
    companies' entries then use it, marked stale."""
    today = timezone.localdate()
    outcome = cbu.ensure_rates(today)
    if not cbu.has_rate(today - timedelta(days=1)):
        cbu.ensure_rates(today - timedelta(days=1))
    return outcome


@shared_task
def verify_balances() -> int:
    """Daily 03:00: recompute account balances and debt totals from the ledger and fix drift,
    and drop receipts uploaded for entries that were never recorded."""
    from apps.finance import maintenance

    drifted = len(maintenance.verify_balances())
    maintenance.purge_orphan_receipts()
    return drifted


@shared_task
def alert_large_expense(txn_id: int) -> int:
    """On commit of a big expense made by someone who isn't an owner: tell the owners."""
    return alerts.send_large_expense(txn_id)


@shared_task
def run_recurring() -> int:
    """Every 30 minutes: post the automatic recurring payments that are due (idempotent per due
    date) and mark own-money claims paid once payroll paid them back."""
    from apps.finance import claims, recurring

    posted = recurring.run_due()
    claims.sync_paid()
    return posted


@shared_task
def remind_payments() -> int:
    """Every 15 minutes: bills and taxes due, automatic payments that couldn't post, overdue
    payables and receivables, in each company's morning, once per person and item a day."""
    from apps.finance import reminders

    return reminders.remind()


@shared_task
def check_budgets(company_id: int, month: str) -> int:
    """On commit of a posted expense in a budgeted category: the month's 80 % / 100 % alerts."""
    from datetime import date

    from apps.companies.models import Company
    from apps.finance import budgets

    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        return 0
    return budgets.check(company, date.fromisoformat(month))


@shared_task
def check_all_budgets() -> int:
    """Daily 03:30: this month's budget alerts of every company (a safety net)."""
    from apps.finance import budgets

    return budgets.check_all()
