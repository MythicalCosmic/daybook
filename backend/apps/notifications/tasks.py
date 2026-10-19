import logging

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from celery import shared_task

from apps.notifications import telegram

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(TelegramNetworkError, TelegramServerError),
    retry_backoff=True,
    max_retries=5,
)
def send_telegram_message(self, bot, chat_id, text, reply_markup=None, photo=None):
    try:
        telegram.send_message(bot, chat_id, text, reply_markup, photo)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramForbiddenError:
        logger.info("Chat %s blocked the %s bot or never started it", chat_id, bot)
