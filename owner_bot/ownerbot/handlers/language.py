"""/language in the owner bot (research R1 L8): the same three-language picker as the employee
bot. The choice is the person's, so both bots and the apps follow it."""

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
    LANGUAGE_NAMES,
    LANGUAGES,
    PICK_TITLE,
    language_of,
)
from ownerbot.commands import menu_button, private_commands

router = Router(name="language")
router.message.filter(F.chat.type == ChatType.PRIVATE)


class OwnerLanguage(CallbackData, prefix="olang"):
    code: str


def picker(current: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✓ {LANGUAGE_NAMES[code]}" if code == current else LANGUAGE_NAMES[code],
                    callback_data=OwnerLanguage(code=code).pack(),
                )
                for code in LANGUAGES
            ]
        ]
    )


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
    await callback.answer(f"✅ {LANGUAGE_NAMES[code]}")
    with suppress(TelegramAPIError):
        await callback.message.delete()
    chat_id = callback.message.chat.id
    with translation.override(code):
        commands, button = private_commands(), menu_button()
    with suppress(TelegramAPIError):
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    with suppress(TelegramAPIError):
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
    await callback.message.answer(CHANGED_SHORT[code])
