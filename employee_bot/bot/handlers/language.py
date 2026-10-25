"""The bot's language, help and settings (research R1 L1, L3, F10), for anyone who writes to the
bot: members, newcomers and people waiting for approval alike.

    /language (also /til, /lang)  the picker: O‘zbekcha · Русский · English
    /settings                     language (and company, for someone in several)
    /help                         what the bot does

A new language is saved at once, and the chat follows: its command menu, menu button and
reply keyboard are relabelled (`apps.accounts.telegram_chat.relabel`). Old messages keep their
words; any card tapped again is drawn in the new language.
"""

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import approved_memberships, bot_membership, set_language
from apps.accounts.telegram_chat import (
    ALREADY,
    CURRENT,
    LANGUAGE_NAMES,
    LANGUAGES,
    PICK_TITLE,
    language_of,
    relabel,
)
from apps.members.bot_messages import company_button
from bot.callbacks import LangCallback

router = Router(name="language")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


def picker(current: str, *, mode: str = "set", order=LANGUAGES) -> InlineKeyboardMarkup:
    """One row of native names, O‘zbekcha first. The current one is coloured and the text above
    names it in words (PICK_TITLE); no tick marks."""
    return InlineKeyboardMarkup(inline_keyboard=[language_row(current, mode=mode, order=order)])


def language_row(current: str, *, mode: str, order=LANGUAGES) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=LANGUAGE_NAMES[code],
            callback_data=LangCallback(code=code, mode=mode).pack(),
            style="success" if code == current else None,
        )
        for code in order
    ]


@router.message(Command("language", "til", "lang"))
async def ask_language(message: Message, user: User) -> None:
    current = language_of(user.language)
    await message.answer(PICK_TITLE[current], reply_markup=picker(current))


@router.callback_query(LangCallback.filter(F.mode == "open"))
async def open_picker(callback: CallbackQuery, user: User) -> None:
    current = language_of(user.language)
    with suppress(TelegramAPIError):
        await callback.message.edit_text(PICK_TITLE[current], reply_markup=picker(current))
    await callback.answer()


@router.callback_query(LangCallback.filter(F.mode == "set"))
async def pick_language(
    callback: CallbackQuery, callback_data: LangCallback, user: User, bot: Bot
) -> None:
    code = callback_data.code
    if code not in LANGUAGES:
        await callback.answer()
        return
    if not await sync_to_async(set_language)(user, code):
        await callback.answer(ALREADY[code])
        return
    await callback.answer(LANGUAGE_NAMES[code])
    with suppress(TelegramAPIError):  # under 48 hours old, so it can go
        await callback.message.delete()
    membership = await sync_to_async(bot_membership)(user)
    await relabel(bot, callback.message.chat.id, user, membership)


@router.message(Command("help"))
async def show_help(message: Message) -> None:
    lines = [
        f"<b>{_("Here's what I can do:")}</b>",
        _("/tasks: your tasks"),
        _("/new: add a task (or just type it)"),
        _("/check: work waiting for your check"),
        _("The button next to the message field opens the app"),
        _("/language: change the language"),
    ]
    await message.answer("\n".join(lines))


@router.message(Command("settings"))
async def show_settings(message: Message, user: User) -> None:
    current = language_of(user.language)
    rows = [
        [
            InlineKeyboardButton(
                text=CURRENT[current],
                callback_data=LangCallback(code=current, mode="open").pack(),
            )
        ]
    ]
    with translation.override(user.language):
        if len(await sync_to_async(approved_memberships)(user)) > 1:
            membership = await sync_to_async(bot_membership)(user)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=company_button(membership.company), callback_data="co_open"
                    )
                ]
            )
        text = _("<b>Settings</b>")
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
