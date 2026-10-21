from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.conf import settings

from apps.accounts.models import User
from apps.companies.services import find_by_invite
from apps.core.exceptions import DomainError
from apps.members import bot_messages, services
from apps.members.models import Membership
from bot import deeplinks

router = Router(name="start")

# What the mini app sends when a keyboard button opened it (miniapp/src/screens/Gate.tsx,
# OPEN_APP_REQUEST): Telegram signs nobody in from such a button, so the app asks for one that does.
OPEN_APP_REQUEST = "open_app"


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(
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
        await message.answer(text, reply_markup=markup)


@router.message(F.web_app_data, F.chat.type == ChatType.PRIVATE)
async def app_asks_for_a_button(message: Message, user: User, state: FSMContext) -> None:
    """The mini app, opened from a keyboard button of an old main menu, couldn't sign the person
    in and asked for a way that does (Telegram closed it and sent us its data). Answer with where
    they stand, which for a member also replaces that old keyboard with today's menu, then a
    button that opens the app signed in."""
    if message.web_app_data.data != OPEN_APP_REQUEST:
        return
    await state.clear()  # like any menu button, it ends a conversation in progress
    for text, markup in await _open_app_replies(user):
        await message.answer(text, reply_markup=markup)


@sync_to_async
def _handle_start(user: User, start_param: str | None) -> bot_messages.BotMessage | None:
    if not start_param:
        return bot_messages.status(services.current_membership(user))
    try:
        company = find_by_invite(start_param)
    except DomainError as exc:
        return str(exc), None
    membership, _ = services.request_access(user, company)
    return bot_messages.status(membership)


@sync_to_async
def _open_app_replies(user: User) -> list[bot_messages.BotMessage]:
    membership = services.current_membership(user)
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
