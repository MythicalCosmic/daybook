"""Celery tasks of accounts. Thin wrappers over plain modules."""

from celery import shared_task

from apps.accounts import photos, telegram_chat


@shared_task
def refresh_telegram_photos() -> int:
    """Weekly: cache everyone's Telegram profile photo as their avatar (sanitized)."""
    return photos.refresh()


@shared_task
def relabel_employee_chat(user_id: int) -> None:
    """A language changed in the mini app: the bot's menus and keyboard follow."""
    telegram_chat.relabel_employee_chat(user_id)
