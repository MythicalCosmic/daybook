"""Sends Telegram messages from backend code (Celery workers), through either bot."""

import asyncio
import logging
from contextlib import suppress
from enum import StrEnum
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, ReplyKeyboardMarkup
from django.conf import settings
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


class BotName(StrEnum):
    EMPLOYEE = "employee"
    OWNER = "owner"


type Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup


def serialize_markup(markup: Markup | None) -> dict | None:
    """Celery arguments must be JSON, so keyboards travel as dicts."""
    return markup.model_dump(mode="json", exclude_none=True) if markup else None


def send_message(
    bot: str,
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    photo: str | None = None,
) -> int | None:
    """Send `text`, as the caption of `photo` (a storage path) when there is one.

    Returns the id of the message holding the keyboard, or None when nothing was sent.
    """
    if settings.TELEGRAM_DRY_RUN:
        logger.info("Dry run, not sent to %s via the %s bot: %s", chat_id, bot, text)
        return None
    token = _token(BotName(bot))
    if not token:
        logger.warning("No token for the %s bot; dropping a message to %s", bot, chat_id)
        return None
    image = None
    if photo:
        with default_storage.open(photo, "rb") as file:
            image = BufferedInputFile(file.read(), filename=Path(photo).name)
    return asyncio.run(_send(token, chat_id, text, _deserialize_markup(reply_markup), image))


def delete_message(bot: str, chat_id: int, message_id: int) -> None:
    """Best effort: Telegram refuses to delete messages older than 48 hours."""
    token = _token(BotName(bot))
    if settings.TELEGRAM_DRY_RUN or not token:
        return
    asyncio.run(_delete(token, chat_id, message_id))


async def _delete(token: str, chat_id: int, message_id: int) -> None:
    async with Bot(token) as bot:
        with suppress(TelegramBadRequest):
            await bot.delete_message(chat_id, message_id)


def _token(bot: BotName) -> str:
    if bot == BotName.EMPLOYEE:
        return settings.EMPLOYEE_BOT_TOKEN
    return settings.OWNER_BOT_TOKEN


async def _send(
    token: str, chat_id: int, text: str, markup: Markup | None, image: BufferedInputFile | None
) -> int:
    async with Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        if image is None:
            sent = await bot.send_message(chat_id, text, reply_markup=markup)
        elif len(text) <= CAPTION_LIMIT:
            sent = await bot.send_photo(chat_id, image, caption=text, reply_markup=markup)
        else:
            await bot.send_photo(chat_id, image)
            sent = await bot.send_message(chat_id, text, reply_markup=markup)
        return sent.message_id


def _deserialize_markup(data: dict | None) -> Markup | None:
    if data is None:
        return None
    if "inline_keyboard" in data:
        return InlineKeyboardMarkup.model_validate(data)
    return ReplyKeyboardMarkup.model_validate(data)
