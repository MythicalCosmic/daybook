"""Celery tasks of the knowledge base, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from celery import shared_task

from apps.knowledge import schedule


@shared_task
def remind_unread() -> int:
    """Pages people must confirm: one reminder to whoever hasn't, after the company's delay."""
    return schedule.remind_unread()
