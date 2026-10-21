"""Celery tasks of accounts. Thin wrappers over plain modules."""

from celery import shared_task

from apps.accounts import photos


@shared_task
def refresh_telegram_photos() -> int:
    """Weekly: cache everyone's Telegram profile photo as their avatar (sanitized)."""
    return photos.refresh()
