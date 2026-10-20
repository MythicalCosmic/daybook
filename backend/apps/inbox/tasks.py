"""Celery tasks of the inbox, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from celery import shared_task

from apps.inbox import delivery


@shared_task(
    bind=True,
    autoretry_for=(TelegramNetworkError, TelegramServerError),
    retry_backoff=True,
    max_retries=5,
)
def deliver_telegram(self, notification_id, photo=None, photo_storage="default"):
    """The Telegram copy of a notification, through the right bot, with its buttons."""
    try:
        delivery.deliver(notification_id, photo=photo, photo_storage=photo_storage)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
