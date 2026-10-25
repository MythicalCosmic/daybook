"""/language in the owner bot (research R1 L8): the same three-language picker as the employee
bot, O‘zbekcha first. The choice is the person's, so both bots and the apps follow it.

Everyone starts in Uzbek (the owner's "uzbek first", 25.10.2026); the home message carries one
small "Til / Язык / Language" button that shows the three languages in its place, and a choice
there redraws the home message in that language."""

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from asgiref.sync import sync_to_async
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.services import set_language
from apps.accounts.telegram_chat import (
    ALREADY,
    CHANGED_SHORT,
    LANGUAGE_BUTTON,
    LANGUAGE_NAMES,
    LANGUAGES,
    PICK_TITLE,
    language_of,
)
from ownerbot import bot_messages, brief
from ownerbot.commands import menu_button, private_commands

router = Router(name="language")
router.message.filter(F.chat.type == ChatType.PRIVATE)


class OwnerLanguage(CallbackData, prefix="olang"):
    code: str


class OwnerLanguageHome(CallbackData, prefix="olh"):
    """The home message's "Til / Язык / Language" (no code), then the language picked there."""

    code: str


def picker(current: str) -> InlineKeyboardMarkup:
    """One row of native names. The current one is coloured and the text above names it in
    words (PICK_TITLE); no tick marks."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=LANGUAGE_NAMES[code],
                    callback_data=OwnerLanguage(code=code).pack(),
                    style="success" if code == current else None,
                )
                for code in LANGUAGES
            ]
        ]
    )


def with_language_button(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup:
    """The home message's last row: "Til / Язык / Language"."""
    button = InlineKeyboardButton(
        text=LANGUAGE_BUTTON, callback_data=OwnerLanguageHome(code="").pack()
    )
    return InlineKeyboardMarkup(inline_keyboard=[*_other_rows(markup), [button]])


def _other_rows(markup: InlineKeyboardMarkup | None) -> list:
    prefix = f"{OwnerLanguageHome.__prefix__}:"
    rows = markup.inline_keyboard if markup is not None else []
    return [
        row
        for row in rows
        if not any((button.callback_data or "").startswith(prefix) for button in row)
    ]


@router.message(Command("language", "til", "lang"))
async def ask_language(message: Message, user: User) -> None:
    current = language_of(user.language)
    await message.answer(PICK_TITLE[current], reply_markup=picker(current))


@router.callback_query(OwnerLanguage.filter())
async def pick_language(
    callback: CallbackQuery, callback_data: OwnerLanguage, user: User, bot: Bot
) -> None:
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    if not await sync_to_async(set_language)(user, code):
        await callback.answer(ALREADY[code])
        return
    await callback.answer(LANGUAGE_NAMES[code])
    with suppress(TelegramAPIError):
        await callback.message.delete()
    await _relabel(bot, callback.message.chat.id, code)
    await callback.message.answer(CHANGED_SHORT[code])


@router.callback_query(OwnerLanguageHome.filter(F.code == ""))
async def home_languages(callback: CallbackQuery, user: User) -> None:
    """The three languages take the button's place, in the same message."""
    current = language_of(user.language)
    row = [
        InlineKeyboardButton(
            text=LANGUAGE_NAMES[code],
            callback_data=OwnerLanguageHome(code=code).pack(),
            style="success" if code == current else None,
        )
        for code in LANGUAGES
    ]
    rows = [*_other_rows(callback.message.reply_markup), row]
    with suppress(TelegramAPIError):
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    await callback.answer()


@router.callback_query(OwnerLanguageHome.filter(F.code != ""))
async def home_language(
    callback: CallbackQuery, callback_data: OwnerLanguageHome, user: User, bot: Bot
) -> None:
    """A language picked on the home message: the home message again, in place, in it."""
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    await sync_to_async(set_language)(user, code)
    await callback.answer(LANGUAGE_NAMES[code])
    with translation.override(code):
        companies = await sync_to_async(brief.companies_summary)(user)
        text, markup = bot_messages.welcome(user, companies)
    with suppress(TelegramAPIError):
        await callback.message.edit_text(text, reply_markup=with_language_button(markup))
    await _relabel(bot, callback.message.chat.id, code)


async def _relabel(bot: Bot, chat_id: int, code: str) -> None:
    """The chat's command menu and menu button in the new language. Best effort."""
    with translation.override(code):
        commands, button = private_commands(), menu_button()
    with suppress(TelegramAPIError):
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    with suppress(TelegramAPIError):
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
