"""Celery tasks of owner sign-in, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from celery import shared_task

from apps.signin import housekeeping


@shared_task
def flush_expired_tokens() -> None:
    """Daily: expired refresh tokens and sessions that can never be used again."""
    housekeeping.flush_expired_tokens()
