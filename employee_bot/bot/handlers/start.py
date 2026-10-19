from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.companies.services import find_by_invite
from apps.core.exceptions import DomainError
from apps.members import bot_messages, services

router = Router(name="start")


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, command: CommandObject, user: User) -> None:
    reply = await _handle_start(user, command.args)
    if reply is not None:
        text, markup = reply
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
