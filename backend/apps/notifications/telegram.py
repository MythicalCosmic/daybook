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


class BotName(StrEnum):
    EMPLOYEE = "employee"
    OWNER = "owner"


type Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove


def serialize_markup(markup: Markup | None) -> dict | None:
    """Celery arguments must be JSON, so keyboards travel as dicts."""
    return markup.model_dump(mode="json", exclude_none=True) if markup else None


def storage_named(name: str) -> Storage:
    """ "default" (public media: proof photos) or "private" (receipts, documents, exports)."""
    if name == "default":
        return default_storage
    if name == "private":
        return private_storage
    raise ValueError(f"Unknown storage {name!r}; use 'default' or 'private'.")


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
    """Send the file at `path` in `storage` as a document (an export, a payslip PDF).

    `filename` is what the recipient sees (the stored name is a random one). Returns the
    message id, or None when nothing was sent."""
    if settings.TELEGRAM_DRY_RUN:
        logger.info("Dry run, document %s not sent to %s via the %s bot", path, chat_id, bot)
        return None
    token = _token(BotName(bot))
    if not token:
        logger.warning("No token for the %s bot; dropping a document to %s", bot, chat_id)
        return None
    document = _read(path, storage, filename=filename)
    return asyncio.run(
        _send_document(
            token, chat_id, document, caption[:CAPTION_LIMIT], _deserialize_markup(reply_markup)
        )
    )


def edit_message(
    bot: str,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> None:
    """Replace a sent message's text (or caption, for a photo) and keyboard; `None` removes
    the keyboard. Best effort: a message that is gone or unchanged is left alone."""
    token = _token(BotName(bot))
    if settings.TELEGRAM_DRY_RUN or not token:
        return
    markup = _deserialize_markup(reply_markup)
    if markup is not None and not isinstance(markup, InlineKeyboardMarkup):
        raise ValueError("Only inline keyboards can be edited into a message.")
    asyncio.run(_edit(token, chat_id, message_id, text, markup))


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


def _read(path: str, storage: str, *, filename: str | None = None) -> BufferedInputFile:
    with storage_named(storage).open(path, "rb") as file:
        return BufferedInputFile(file.read(), filename=filename or Path(path).name)


def _bot(token: str) -> Bot:
    return Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


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
    token: str,
    chat_id: int,
    document: BufferedInputFile,
    caption: str,
    markup: Markup | None,
) -> int:
    async with _bot(token) as bot:
        sent = await bot.send_document(
            chat_id, document, caption=caption or None, reply_markup=markup
        )
        return sent.message_id


# What Telegram answers when an edit has nothing to do; anything else is a real error.
HARMLESS_EDIT_ERRORS = ("message is not modified", "message to edit not found")


async def _edit(
    token: str, chat_id: int, message_id: int, text: str, markup: InlineKeyboardMarkup | None
) -> None:
    async with _bot(token) as bot:
        try:
            await bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup
            )
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if "there is no text in the message" in message:
                # A photo: its text is the caption.
                with suppress(TelegramBadRequest):
                    await bot.edit_message_caption(
                        caption=text[:CAPTION_LIMIT],
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=markup,
                    )
            elif not any(harmless in message for harmless in HARMLESS_EDIT_ERRORS):
                raise


def _deserialize_markup(data: dict | None) -> Markup | None:
    if data is None:
        return None
    if "inline_keyboard" in data:
        return InlineKeyboardMarkup.model_validate(data)
    if "remove_keyboard" in data:
        return ReplyKeyboardRemove.model_validate(data)
    return ReplyKeyboardMarkup.model_validate(data)
