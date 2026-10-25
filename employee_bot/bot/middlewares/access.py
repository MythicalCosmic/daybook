from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, html
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.accounts.services import bot_membership, membership_in, remember_company
from apps.members import bot_messages
from apps.members.models import Membership
from apps.tasks.models import Task
from bot.task_refs import task_id_of_event


class MemberAccessMiddleware(BaseMiddleware):
    """Hard gate: only approved members of an active company get past this point.

    Everyone else gets the answer for their status: how to join, "waiting for approval",
    "declined", and for a suspended member "Your access is paused until …" on every message
    and every button. Blocked people get silence.

    Which membership: a button or a reply about a task acts in that task's company (someone
    in two companies taps a push from either, audit X-1), which then becomes the company their
    lists show; anything else uses the company they work in through the bot
    (`apps.accounts.services.bot_membership`).
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

        membership, reply, switched = await _resolve(user, task_id_of_event(event))
        if membership is not None and membership.status == Membership.Status.APPROVED:
            data["membership"] = membership
            result = await handler(event, data)
            if switched:
                # The lists now show the task's company: say so, and bring that company's menu
                # (its name on the switch button, its modules), or the old one stays on screen.
                text, markup = await _switched(membership)
                await data["bot"].send_message(chat.id, text, reply_markup=markup)
            return result

        if reply is not None:
            if isinstance(event, Message):
                text, markup = reply
                await event.answer(text, reply_markup=markup)
            elif isinstance(event, CallbackQuery):
                await event.answer(await _alert(membership), show_alert=True)
        return None


@sync_to_async
def _resolve(
    user: User, task_id: int | None
) -> tuple[Membership | None, bot_messages.BotMessage | None, bool]:
    """The membership to act with, the answer for someone who may not, and whether a task of
    another company just became the company the person's lists show."""
    membership, switched = None, False
    if task_id is not None:
        company_id = Task.objects.filter(pk=task_id).values_list("company_id", flat=True).first()
        if company_id is not None:
            membership = membership_in(user, company_id)
            if membership is not None:
                if user.bot_company_id != company_id:
                    current = bot_membership(user)
                    switched = current is not None and current.company_id != company_id
                remember_company(user, company_id)
    if membership is None:
        membership = bot_membership(user)
    if membership is not None and membership.status == Membership.Status.APPROVED:
        return membership, None, switched
    return membership, bot_messages.status(membership), False


@sync_to_async
def _switched(membership: Membership) -> bot_messages.BotMessage:
    text = _("Now working in <b>%(company)s</b>.") % {
        "company": html.quote(membership.company.name)
    }
    return text, bot_messages.main_menu(membership)


@sync_to_async
def _alert(membership: Membership | None) -> str:
    if membership is not None and membership.status == Membership.Status.SUSPENDED:
        return bot_messages.paused_text(membership)
    return _("You don't have access to this.")
