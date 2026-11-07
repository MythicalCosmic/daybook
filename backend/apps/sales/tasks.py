"""Celery tasks of sales and cash, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from datetime import date

from celery import shared_task

from apps.sales import lines, reminders, rollup, scan


@shared_task
def remind_customer_debts() -> int:
    """Every 15 minutes, acting in each company's morning: overdue nasiya and invoices to the
    person responsible, once a day per debt (`Debt.last_reminded_on`)."""
    return reminders.remind()


@shared_task
def process_import(import_id: int) -> str | None:
    """Read an uploaded file of sale lines (PLAN-OWNER §14.7): receipts, lines, stock, the day
    check and the legal price check. Idempotent: only a queued import is read."""
    imp = lines.process(import_id)
    return imp.status if imp is not None else None


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
