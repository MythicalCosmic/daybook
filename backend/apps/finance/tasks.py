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
