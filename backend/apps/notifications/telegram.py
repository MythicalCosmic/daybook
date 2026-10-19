"""Sends Telegram messages from backend code (Celery workers), through either bot."""

import asyncio
import logging
from enum import StrEnum

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup
from django.conf import settings

logger = logging.getLogger(__name__)


class BotName(StrEnum):
    EMPLOYEE = "employee"
    OWNER = "owner"


def serialize_markup(markup: InlineKeyboardMarkup | None) -> dict | None:
    """Celery arguments must be JSON, so keyboards travel as dicts."""
    return markup.model_dump(mode="json", exclude_none=True) if markup else None


def send_message(bot: str, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    token = _token(BotName(bot))
    if not token:
        logger.warning("No token for the %s bot; dropping a message to %s", bot, chat_id)
        return
    asyncio.run(_send(token, chat_id, text, reply_markup))


def _token(bot: BotName) -> str:
    if bot == BotName.EMPLOYEE:
        return settings.EMPLOYEE_BOT_TOKEN
    return settings.OWNER_BOT_TOKEN


async def _send(token: str, chat_id: int, text: str, reply_markup: dict | None) -> None:
    markup = InlineKeyboardMarkup.model_validate(reply_markup) if reply_markup else None
    async with Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        await bot.send_message(chat_id, text, reply_markup=markup)
