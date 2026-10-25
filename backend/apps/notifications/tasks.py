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

RETRYING = {
    "bind": True,
    "autoretry_for": (TelegramNetworkError, TelegramServerError),
    "retry_backoff": True,
    "max_retries": 5,
}


@shared_task(**RETRYING)
def send_telegram_message(
    self, bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"
):
    # The storage only travels when it isn't the usual one, so callers and test doubles of
    # telegram.send_message that predate it keep working.
    extra = {"photo_storage": photo_storage} if photo_storage != "default" else {}
    try:
        telegram.send_message(bot, chat_id, text, reply_markup, photo, **extra)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramForbiddenError:
        logger.info("Chat %s blocked the %s bot or never started it", chat_id, bot)
    except TelegramBadRequest as exc:
        # E.g. "chat not found": nobody with that id ever opened the bot. Sending again won't help.
        logger.warning("Message to chat %s not delivered: %s", chat_id, exc)


@shared_task(**RETRYING)
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
    except TelegramBadRequest as exc:
        logger.warning("Document to chat %s not delivered: %s", chat_id, exc)


@shared_task(**RETRYING)
def edit_telegram_message(self, bot, chat_id, message_id, text, reply_markup=None):
    try:
        telegram.edit_message(bot, chat_id, message_id, text, reply_markup)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramForbiddenError:
        logger.info("Chat %s blocked the %s bot or never started it", chat_id, bot)
