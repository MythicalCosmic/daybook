"""Celery tasks of HR records, queued with `transaction.on_commit` or run by beat.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import (`notify`, `watch`).
"""

from celery import shared_task


@shared_task
def notify_contract_ready(contract_id: int) -> None:
    """The person hears their contract is in force and can be read in the app."""
    from apps.hr import notify

    notify.contract_ready(contract_id)
