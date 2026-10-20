"""Celery tasks of the company calendar, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from celery import shared_task

from apps.agenda import schedule


@shared_task
def send_event_reminders() -> int:
    """Every minute: bot reminders `remind_before` minutes before each event."""
    return schedule.send_event_reminders()
