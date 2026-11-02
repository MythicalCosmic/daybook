"""Celery tasks of the people lifecycle, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import (`notify`).
"""

from celery import shared_task


@shared_task
def notify_record_issued(record_id: int) -> None:
    """The person hears a record was given to them, with a way into the app."""
    from apps.lifecycle import notify

    notify.record_issued(record_id)


@shared_task
def notify_explanation(record_id: int) -> None:
    """Whoever gave the record hears the person explained."""
    from apps.lifecycle import notify

    notify.explanation(record_id)
