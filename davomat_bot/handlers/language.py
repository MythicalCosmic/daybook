"""/language: the same three-language picker as the other bots, O‘zbekcha first.

A linked person's choice is theirs for good (both the bot and the web app follow it). Someone
not linked yet has nowhere to keep it: their pick redraws the message in that language.
The home message carries one small "Til / Язык / Language" button that shows the three
languages in its place."""

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.utils import translation

from apps.accounts.services import set_language
from apps.accounts.telegram_chat import (
    ALREADY,
    CHANGED_SHORT,
    LANGUAGE_NAMES,
    LANGUAGES,
    PICK_TITLE,
)
from davomat_bot import bot_messages, commands
from davomat_bot.callbacks import HomeLanguage, PickLanguage
from davomat_bot.middlewares.person import Person

router = Router(name="language")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


def picker(current: str, data=PickLanguage) -> list[InlineKeyboardButton]:
    """One row of native names; the current one coloured (no tick marks)."""
    return [
        InlineKeyboardButton(
            text=LANGUAGE_NAMES[code],
            callback_data=data(code=code).pack(),
            style="success" if code == current else None,
        )
        for code in LANGUAGES
    ]


@router.message(Command("language", "til", "lang"))
async def ask_language(message: Message, person: Person) -> None:
    await message.answer(
        PICK_TITLE[person.language],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[picker(person.language)]),
    )


@router.callback_query(PickLanguage.filter())
async def pick_language(
    callback: CallbackQuery, callback_data: PickLanguage, person: Person, bot: Bot
) -> None:
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    if person.user is None:
        await callback.answer(LANGUAGE_NAMES[code])
        with translation.override(code):
            text, markup = bot_messages.home(None, person.company, callback.from_user.first_name)
        with suppress(TelegramAPIError):
            await callback.message.edit_text(text, reply_markup=markup)
        return
    if not await sync_to_async(set_language)(person.user, code):
        await callback.answer(ALREADY[code])
        return
    await callback.answer(LANGUAGE_NAMES[code])
    with suppress(TelegramAPIError):
        await callback.message.delete()
    await commands.relabel(
        bot,
        callback.message.chat.id,
        language=code,
        manager=bot_messages.sees_attendance(person.member),
    )
    await callback.message.answer(CHANGED_SHORT[code])


@router.callback_query(HomeLanguage.filter(F.code == ""))
async def home_languages(callback: CallbackQuery, person: Person) -> None:
    """The three languages take the button's place, in the same message."""
    markup = callback.message.reply_markup
    prefix = f"{HomeLanguage.__prefix__}:"
    rows = [
        row
        for row in (markup.inline_keyboard if markup else [])
        if not any((button.callback_data or "").startswith(prefix) for button in row)
    ]
    rows.append(picker(person.language, HomeLanguage))
    with suppress(TelegramAPIError):
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    await callback.answer()


@router.callback_query(HomeLanguage.filter(F.code != ""))
async def home_language(
    callback: CallbackQuery, callback_data: HomeLanguage, person: Person, bot: Bot
) -> None:
    """A language picked on the home message: the home message again, in place, in it."""
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    if person.user is not None:
        await sync_to_async(set_language)(person.user, code)
    await callback.answer(LANGUAGE_NAMES[code])
    first_name = (person.member.first_name if person.member else "") or (
        callback.from_user.first_name or ""
    )
    with translation.override(code):
        text, markup = bot_messages.home(person.member, person.company, first_name)
    with suppress(TelegramAPIError):
        await callback.message.edit_text(text, reply_markup=markup)
    if person.user is not None:
        await commands.relabel(
            bot,
            callback.message.chat.id,
            language=code,
            manager=bot_messages.sees_attendance(person.member),
        )
