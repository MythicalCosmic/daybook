from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.members import bot_messages, services
from apps.members.models import Membership


class MemberAccessMiddleware(BaseMiddleware):
    """Hard gate: only approved members of an active company get past this point.

    Everyone else gets the answer for their status: how to join, "waiting for approval",
    "declined", and for a suspended member "Your access is paused until …" on every message
    and every button. Blocked people get silence.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        chat = data.get("event_chat")
        if user is None or chat is None or chat.type != ChatType.PRIVATE:
            return None

        membership, reply = await _resolve(user)
        if membership is not None and membership.status == Membership.Status.APPROVED:
            data["membership"] = membership
            return await handler(event, data)

        if reply is not None:
            if isinstance(event, Message):
                text, markup = reply
                await event.answer(text, reply_markup=markup)
            elif isinstance(event, CallbackQuery):
                await event.answer(await _alert(membership), show_alert=True)
        return None


@sync_to_async
def _resolve(user: User) -> tuple[Membership | None, bot_messages.BotMessage | None]:
    membership = services.current_membership(user)
    return membership, bot_messages.status(membership)


@sync_to_async
def _alert(membership: Membership | None) -> str:
    if membership is not None and membership.status == Membership.Status.SUSPENDED:
        return bot_messages.paused_text(membership)
    return _("You don't have access to this.")
