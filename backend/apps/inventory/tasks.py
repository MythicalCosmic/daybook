"""Celery tasks of stock, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import (`scan.py`).
"""

from celery import shared_task


@shared_task
def daily_scan() -> int:
    """Hourly; acts once per company day at 06:00 company time."""
    from apps.inventory import scan

    return scan.daily_scan()


@shared_task
def recompute_low_stock() -> int:
    from apps.inventory import scan

    return scan.recompute_low_stock()


@shared_task
def remind_unposted() -> int:
    from apps.inventory import scan

    return scan.remind_unposted()
