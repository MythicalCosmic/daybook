import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.services import bot_membership, set_language
from apps.accounts.telegram_chat import LANGUAGE_NAMES, LANGUAGES, language_of, relabel
from apps.companies.services import find_by_invite
from apps.core.exceptions import DomainError
from apps.members import bot_messages, services
from apps.members.models import Membership
from bot import deeplinks
from bot.callbacks import LangCallback
from bot.commands import menu_button
from bot.handlers.language import language_row
from bot.keyboards import is_language_row, with_language_button

logger = logging.getLogger(__name__)

router = Router(name="start")

# What the mini app sends when a keyboard button opened it (miniapp/src/screens/Gate.tsx,
# OPEN_APP_REQUEST): Telegram signs nobody in from such a button, so the app asks for one that does.
OPEN_APP_REQUEST = "open_app"


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(
    message: Message,
    command: CommandObject,
    user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    # Uzbek first (the owner, 25.10.2026): someone new is greeted in Uzbek, with one small
    # "Til / Язык / Language" button for whoever reads another language. No picker first.
    await _answer_start(message, command, user, state)
    # After the answer, so it never waits on this.
    membership = await sync_to_async(bot_membership)(user)
    await relabel(bot, message.chat.id, user, membership, confirm=False)


async def _answer_start(
    message: Message, command: CommandObject, user: User, state: FSMContext
) -> None:
    # Deep links features registered (login_…, job_…) first; their handlers decide what happens
    # to a conversation in progress. Anything else is an invite or "home", which ends it.
    if await deeplinks.dispatch(message, command.args, user=user, state=state):
        return
    await state.clear()
    reply = await _handle_start(user, command.args)
    if reply is not None:
        text, markup = reply
        await message.answer(text, reply_markup=with_language_button(markup))


@router.callback_query(LangCallback.filter(F.mode == "langs"))
async def show_languages(callback: CallbackQuery, user: User) -> None:
    """The greeting's "Til / Язык / Language": the three languages take the button's place, in
    the same message."""
    markup = callback.message.reply_markup
    rows = [row for row in (markup.inline_keyboard if markup else []) if not is_language_row(row)]
    rows.append(language_row(language_of(user.language), mode="welcome"))
    with suppress(TelegramAPIError):
        await callback.message.edit_reply_markup(
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    await callback.answer()


@router.callback_query(LangCallback.filter(F.mode == "welcome"))
async def welcome_language(
    callback: CallbackQuery, callback_data: LangCallback, user: User, bot: Bot
) -> None:
    """A language picked on the greeting: the greeting again, in place, in that language."""
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    await sync_to_async(set_language)(user, code)
    await callback.answer(LANGUAGE_NAMES[code])
    membership = await sync_to_async(bot_membership)(user)
    with translation.override(code):
        reply = await sync_to_async(bot_messages.status)(membership)
    if reply is not None:
        text, markup = reply
        if markup is None or isinstance(markup, InlineKeyboardMarkup):
            with suppress(TelegramAPIError):
                await callback.message.edit_text(text, reply_markup=with_language_button(markup))
        else:  # the main menu, which only a new message can carry
            await callback.message.answer(text, reply_markup=markup)
    await relabel(bot, callback.message.chat.id, user, membership, confirm=False)


@router.callback_query(LangCallback.filter(F.mode == "first"))
async def first_language(
    callback: CallbackQuery, callback_data: LangCallback, user: User, state: FSMContext, bot: Bot
) -> None:
    """A tap on the three-language picker the bot showed new people until 25.10.2026 (some are
    still in chats): save the choice, then the welcome the /start was for, in it."""
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    await sync_to_async(set_language)(user, code)
    args = (await state.get_data()).get("start_args")
    await state.clear()
    await callback.answer(LANGUAGE_NAMES[code])
    with suppress(TelegramAPIError):
        await callback.message.delete()
    with translation.override(code):
        reply = await _handle_start(user, args)
    if reply is not None:
        text, markup = reply
        await callback.message.answer(text, reply_markup=markup)
    membership = await sync_to_async(bot_membership)(user)
    await relabel(bot, callback.message.chat.id, user, membership, confirm=False)


@router.message(F.web_app_data, F.chat.type == ChatType.PRIVATE)
async def app_asks_for_a_button(message: Message, user: User, state: FSMContext, bot: Bot) -> None:
    """The mini app, opened from a keyboard button of an old main menu, couldn't sign the person
    in and asked for a way that does (Telegram closed it and sent us its data). Answer with where
    they stand, which for a member also replaces that old keyboard with today's menu, then a
    button that opens the app signed in."""
    if message.web_app_data.data != OPEN_APP_REQUEST:
        return
    await state.clear()  # like any menu button, it ends a conversation in progress
    for text, markup in await _open_app_replies(user):
        await message.answer(text, reply_markup=markup)
    await set_menu_button(bot, message.chat.id, user)


async def set_menu_button(bot: Bot, chat_id: int, user: User) -> None:
    """Label this chat's menu button, which opens the app, in the person's own language: the one
    every chat starts with is set once, in Uzbek (bot.commands.set_commands), and the app's "Open
    Daybook from the chat" screen names the button as it reads in their language. Best effort:
    the button works whatever its label, so a refusal only gets logged."""
    with translation.override(user.language):
        button = menu_button()
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
    except TelegramAPIError as exc:
        logger.warning("Couldn't label the menu button of chat %s: %s", chat_id, exc)


@sync_to_async
def _handle_start(user: User, start_param: str | None) -> bot_messages.BotMessage | None:
    if not start_param:
        return bot_messages.status(bot_membership(user))
    try:
        company = find_by_invite(start_param)
    except DomainError as exc:
        return str(exc), None
    membership, _ = services.request_access(user, company)
    return bot_messages.status(membership)


@sync_to_async
def _open_app_replies(user: User) -> list[bot_messages.BotMessage]:
    membership = bot_membership(user)
    status = bot_messages.status(membership)
    replies = [status] if status is not None else []
    member = (
        membership is not None
        and membership.status == Membership.Status.APPROVED
        and membership.is_onboarded
    )
    # Someone still creating their account already got the app's button with their status.
    if member and settings.EMPLOYEE_MINIAPP_URL:
        replies.append(bot_messages.open_app())
    return replies
