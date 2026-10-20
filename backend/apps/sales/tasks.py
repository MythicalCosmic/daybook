"""Celery tasks of sales and cash, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from datetime import date

from celery import shared_task

from apps.sales import rollup, scan


@shared_task
def rollup_day(branch_id: int, day: str) -> None:
    """Rebuild one branch's `DailySales` row after a close, a correction or a void."""
    rollup.rebuild_day(branch_id, date.fromisoformat(day))


@shared_task
def rollup_yesterday() -> int:
    """Safety net (daily 04:30): rebuild the last two business days of every sales company."""
    return scan.rollup_recent()


@shared_task
def scan_operational() -> int:
    """Every 5 minutes: branches not opened, tills left open, unconfirmed handovers, cash over
    the branch limit after closing. Each alert goes out once (dedupe keys)."""
    return scan.scan_all()


@shared_task
def post_evening_sales() -> int:
    """Every 15 minutes: once per company and business day, after the last branch closes, the
    day's sales go to the groups that want sales news."""
    return scan.post_evening_all()
