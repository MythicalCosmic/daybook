import logging
from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.services import bot_membership, set_language
from apps.accounts.telegram_chat import FIRST_PICK, LANGUAGE_NAMES, LANGUAGES, relabel
from apps.companies.services import find_by_invite
from apps.core.exceptions import DomainError
from apps.members import bot_messages, services
from apps.members.models import Membership
from bot import deeplinks
from bot.callbacks import LangCallback
from bot.commands import menu_button
from bot.handlers.language import picker
from bot.states.tasks import PickLanguage

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
    first_contact: bool = False,
    telegram_language: str = "",
) -> None:
    # First contact from someone whose Telegram isn't in Uzbek: ask once, in all three
    # languages (research R1 L2). Telegram's language is a weak hint in Uzbekistan. Sign-in and
    # other deep links never wait for it.
    if first_contact and telegram_language != "uz" and deeplinks.resolve(command.args) is None:
        await state.set_state(PickLanguage.first)
        await state.update_data(start_args=command.args)
        order = await sync_to_async(_language_order)(command.args)
        await message.answer(FIRST_PICK, reply_markup=picker("", mode="first", order=order))
        return
    await _answer_start(message, command, user, state, offer_languages=first_contact)
    # After the answer, so it never waits on this.
    membership = await sync_to_async(bot_membership)(user)
    await relabel(bot, message.chat.id, user, membership, confirm=False)


async def _answer_start(
    message: Message,
    command: CommandObject,
    user: User,
    state: FSMContext,
    *,
    offer_languages: bool = False,
) -> None:
    # Deep links features registered (login_…, job_…) first; their handlers decide what happens
    # to a conversation in progress. Anything else is an invite or "home", which ends it.
    if await deeplinks.dispatch(message, command.args, user=user, state=state):
        return
    await state.clear()
    reply = await _handle_start(user, command.args)
    if reply is not None:
        text, markup = reply
        if offer_languages:
            markup = _with_other_languages(markup, user.language)
        await message.answer(text, reply_markup=markup)


@router.callback_query(LangCallback.filter(F.mode == "first"))
async def first_language(
    callback: CallbackQuery, callback_data: LangCallback, user: User, state: FSMContext, bot: Bot
) -> None:
    """The first contact's choice: save it, then the welcome the /start was for, in it."""
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    await sync_to_async(set_language)(user, code)
    args = (await state.get_data()).get("start_args")
    await state.clear()
    await callback.answer(f"✅ {LANGUAGE_NAMES[code]}")
    with suppress(TelegramAPIError):
        await callback.message.delete()
    with translation.override(code):
        reply = await _handle_start(user, args)
    if reply is not None:
        text, markup = reply
        await callback.message.answer(text, reply_markup=markup)
    membership = await sync_to_async(bot_membership)(user)
    await relabel(bot, callback.message.chat.id, user, membership, confirm=False)


@router.callback_query(LangCallback.filter(F.mode == "welcome"))
async def welcome_language(
    callback: CallbackQuery, callback_data: LangCallback, user: User, bot: Bot
) -> None:
    """The Uzbek welcome's [Русский] [English] row: the welcome again, in place, in that one."""
    code = callback_data.code if callback_data.code in LANGUAGES else "uz"
    await sync_to_async(set_language)(user, code)
    await callback.answer(f"✅ {LANGUAGE_NAMES[code]}")
    membership = await sync_to_async(bot_membership)(user)
    with translation.override(code):
        reply = await sync_to_async(bot_messages.status)(membership)
    if reply is not None:
        text, markup = reply
        if markup is None or isinstance(markup, InlineKeyboardMarkup):
            with suppress(TelegramAPIError):
                await callback.message.edit_text(text, reply_markup=markup)
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


def _with_other_languages(markup, current: str):
    """The Uzbek welcome gets a last row with the other two languages (R1 L2). A message whose
    keyboard is the main menu can't carry inline buttons, so it goes without."""
    if markup is not None and not isinstance(markup, InlineKeyboardMarkup):
        return markup
    row = [
        InlineKeyboardButton(
            text=LANGUAGE_NAMES[code], callback_data=LangCallback(code=code, mode="welcome").pack()
        )
        for code in LANGUAGES
        if code != current
    ]
    rows = list(markup.inline_keyboard) if markup is not None else []
    return InlineKeyboardMarkup(inline_keyboard=[*rows, row])


def _language_order(start_param: str | None) -> list[str]:
    """The invite's company language first, then the others in the usual order."""
    first = None
    if start_param:
        try:
            first = find_by_invite(start_param).default_language
        except DomainError:
            first = None
    if first not in LANGUAGES:
        return list(LANGUAGES)
    return [first, *(code for code in LANGUAGES if code != first)]


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
