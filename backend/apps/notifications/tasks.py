import logging

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from celery import shared_task

from apps.notifications import telegram

logger = logging.getLogger(__name__)

RETRY = {
    "bind": True,
    "autoretry_for": (TelegramNetworkError, TelegramServerError),
    "retry_backoff": True,
    "max_retries": 5,
}


@shared_task(**RETRY)
def send_telegram_message(
    self, bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"
):
    try:
        telegram.send_message(bot, chat_id, text, reply_markup, photo, photo_storage)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramForbiddenError:
        logger.info("Chat %s blocked the %s bot or never started it", chat_id, bot)


@shared_task(**RETRY)
def send_telegram_document(
    self, bot, chat_id, path, storage="private", caption="", filename=None, reply_markup=None
):
    try:
        telegram.send_document(
            bot,
            chat_id,
            path,
            storage=storage,
            caption=caption,
            filename=filename,
            reply_markup=reply_markup,
        )
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramForbiddenError:
        logger.info("Chat %s blocked the %s bot or never started it", chat_id, bot)


@shared_task(**RETRY)
def edit_telegram_message(self, bot, chat_id, message_id, text, reply_markup=None):
    try:
        telegram.edit_message(bot, chat_id, message_id, text, reply_markup)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        logger.info("Message %s in chat %s not edited: %s", message_id, chat_id, exc)
