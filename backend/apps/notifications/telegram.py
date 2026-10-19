"""Sends Telegram messages from backend code (Celery workers), through either bot."""

import asyncio
import logging
from enum import StrEnum
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
) -> None:
    """Send `text`, as the caption of `photo` (a storage path) when there is one."""
    token = _token(BotName(bot))
    if not token:
        logger.warning("No token for the %s bot; dropping a message to %s", bot, chat_id)
        return
    image = None
    if photo:
        with default_storage.open(photo, "rb") as file:
            image = BufferedInputFile(file.read(), filename=Path(photo).name)
    asyncio.run(_send(token, chat_id, text, _deserialize_markup(reply_markup), image))


def _token(bot: BotName) -> str:
    if bot == BotName.EMPLOYEE:
        return settings.EMPLOYEE_BOT_TOKEN
    return settings.OWNER_BOT_TOKEN


async def _send(
    token: str, chat_id: int, text: str, markup: Markup | None, image: BufferedInputFile | None
) -> None:
    async with Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        if image is None:
            await bot.send_message(chat_id, text, reply_markup=markup)
        elif len(text) <= CAPTION_LIMIT:
            await bot.send_photo(chat_id, image, caption=text, reply_markup=markup)
        else:
            await bot.send_photo(chat_id, image)
            await bot.send_message(chat_id, text, reply_markup=markup)


def _deserialize_markup(data: dict | None) -> Markup | None:
    if data is None:
        return None
    if "inline_keyboard" in data:
        return InlineKeyboardMarkup.model_validate(data)
    return ReplyKeyboardMarkup.model_validate(data)
