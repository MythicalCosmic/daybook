from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from apps.members import bot_messages, services
from apps.members.callbacks import JoinDecision

router = Router(name="approvals")


@router.callback_query(JoinDecision.filter())
async def decide_join_request(
    callback: CallbackQuery, callback_data: JoinDecision, user: User
) -> None:
    alert, request_message = await _decide(user, callback_data)
    if request_message is not None and isinstance(callback.message, Message):
        text, markup = request_message
        # Unchanged or too old to edit: the alert still tells the approver what happened.
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(alert, show_alert=alert is not None)


@sync_to_async
def _decide(
    user: User, callback_data: JoinDecision
) -> tuple[str | None, bot_messages.BotMessage | None]:
    """Return an alert to show, if any, and the refreshed request message, if it changed."""
    try:
        membership = services.decide(callback_data.membership_id, callback_data.action, by=user)
    except PermissionDenied as exc:
        return str(exc), None
    except DomainError as exc:
        # Someone else got there first: show the approver the current state.
        current = services.get_join_request(callback_data.membership_id)
        return str(exc), bot_messages.join_request(current) if current else None
    return None, bot_messages.join_request(membership)
