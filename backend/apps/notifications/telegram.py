"""Sends Telegram messages from backend code (Celery workers), through either bot.

    send_message(bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default")
    send_document(bot, chat_id, path, *, storage="private", caption="", filename=None,
                  reply_markup=None)
    edit_message(bot, chat_id, message_id, text, reply_markup=None)
    delete_message(bot, chat_id, message_id)

Files are read from storage by path: "default" is public media (proof photos), "private" is
`apps.core.storage.private_storage` (receipts, Z-reports, payslip PDFs), so approval messages
can carry private pictures and documents without ever giving them a URL. Each function has a
Celery wrapper in apps.notifications.tasks.
"""

import asyncio
import logging
from contextlib import suppress
from enum import StrEnum
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from django.conf import settings
from django.core.files.storage import Storage, default_storage

from apps.core.storage import private_storage

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
# What Telegram answers when edit_message_text is used on a message that only has a caption.
NO_TEXT_TO_EDIT = "there is no text in the message to edit"
STORAGES: dict[str, Storage] = {"default": default_storage, "private": private_storage}


class BotName(StrEnum):
    EMPLOYEE = "employee"
    OWNER = "owner"


type Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove


def serialize_markup(markup: Markup | None) -> dict | None:
    """Celery arguments must be JSON, so keyboards travel as dicts."""
    return markup.model_dump(mode="json", exclude_none=True) if markup else None


def send_message(
    bot: str,
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    photo: str | None = None,
    photo_storage: str = "default",
) -> int | None:
    """Send `text`, as the caption of `photo` (a path in `photo_storage`) when there is one.

    Returns the id of the message holding the keyboard, or None when nothing was sent.
    """
    if settings.TELEGRAM_DRY_RUN:
        logger.info("Dry run, not sent to %s via the %s bot: %s", chat_id, bot, text)
        return None
    token = _token(BotName(bot))
    if not token:
        logger.warning("No token for the %s bot; dropping a message to %s", bot, chat_id)
        return None
    image = _read(photo, photo_storage) if photo else None
    return asyncio.run(_send(token, chat_id, text, _deserialize_markup(reply_markup), image))


def send_document(
    bot: str,
    chat_id: int,
    path: str,
    *,
    storage: str = "private",
    caption: str = "",
    filename: str | None = None,
    reply_markup: dict | None = None,
) -> int | None:
    """Send the file at `path` in `storage` as a document (a PDF payslip, an export).

    Returns the id of the message holding the keyboard, or None when nothing was sent.
    """
    if settings.TELEGRAM_DRY_RUN:
        logger.info("Dry run, document %s not sent to %s via the %s bot", path, chat_id, bot)
        return None
    token = _token(BotName(bot))
    if not token:
        logger.warning("No token for the %s bot; dropping a document to %s", bot, chat_id)
        return None
    document = _read(path, storage, filename=filename)
    markup = _deserialize_markup(reply_markup)
    return asyncio.run(_send_document(token, chat_id, document, caption, markup))


def edit_message(
    bot: str, chat_id: int, message_id: int, text: str, reply_markup: dict | None = None
) -> None:
    """Replace a message's text and keyboard, e.g. once an approval was decided elsewhere.
    A message that is gone or already says this is left alone."""
    token = _token(BotName(bot))
    if settings.TELEGRAM_DRY_RUN or not token:
        logger.info("Not editing message %s in %s via the %s bot", message_id, chat_id, bot)
        return
    asyncio.run(_edit(token, chat_id, message_id, text, _deserialize_markup(reply_markup)))


def delete_message(bot: str, chat_id: int, message_id: int) -> None:
    """Best effort: Telegram refuses to delete messages older than 48 hours."""
    token = _token(BotName(bot))
    if settings.TELEGRAM_DRY_RUN or not token:
        return
    asyncio.run(_delete(token, chat_id, message_id))


def _read(path: str, storage: str, *, filename: str | None = None) -> BufferedInputFile:
    if storage not in STORAGES:
        raise ValueError(f"Unknown storage {storage!r}; use 'default' or 'private'.")
    with STORAGES[storage].open(path, "rb") as file:
        return BufferedInputFile(file.read(), filename=filename or Path(path).name)


def _bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


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
    async with _bot(token) as bot:
        if image is None:
            sent = await bot.send_message(chat_id, text, reply_markup=markup)
        elif len(text) <= CAPTION_LIMIT:
            sent = await bot.send_photo(chat_id, image, caption=text, reply_markup=markup)
        else:
            await bot.send_photo(chat_id, image)
            sent = await bot.send_message(chat_id, text, reply_markup=markup)
        return sent.message_id


async def _send_document(
    token: str, chat_id: int, document: BufferedInputFile, caption: str, markup: Markup | None
) -> int:
    async with _bot(token) as bot:
        if len(caption) <= CAPTION_LIMIT:
            sent = await bot.send_document(
                chat_id, document, caption=caption or None, reply_markup=markup
            )
        else:
            await bot.send_document(chat_id, document)
            sent = await bot.send_message(chat_id, caption, reply_markup=markup)
        return sent.message_id


async def _edit(
    token: str, chat_id: int, message_id: int, text: str, markup: Markup | None
) -> None:
    async with _bot(token) as bot:
        try:
            try:
                await bot.edit_message_text(
                    text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup
                )
            except TelegramBadRequest as exc:
                if NO_TEXT_TO_EDIT not in str(exc).lower():
                    raise
                # A photo or document with a caption (send_message with a photo): edit that.
                await bot.edit_message_caption(
                    caption=text[:CAPTION_LIMIT],
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                )
        except TelegramBadRequest as exc:
            # Already says this, or gone (deleted, too old): nothing left to do.
            logger.info("Message %s in %s not edited: %s", message_id, chat_id, exc)


def _deserialize_markup(data: dict | None) -> Markup | None:
    if data is None:
        return None
    if "inline_keyboard" in data:
        return InlineKeyboardMarkup.model_validate(data)
    if "remove_keyboard" in data:
        return ReplyKeyboardRemove.model_validate(data)
    return ReplyKeyboardMarkup.model_validate(data)
