from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.core.exceptions import DomainError
from apps.members.bot_messages import BotMessage
from apps.timeoff import bot_messages, services
from apps.timeoff.callbacks import TimeOffAction, TimeOffDecision

router = Router(name="time_off")


@router.callback_query(TimeOffDecision.filter())
async def decide_time_off(
    callback: CallbackQuery, callback_data: TimeOffDecision, user: User
) -> None:
    alert, request_message = await _decide(user, callback_data)
    if request_message is not None and isinstance(callback.message, Message):
        text, markup = request_message
        # Unchanged or too old to edit: the alert still tells the approver what happened.
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(alert, show_alert=alert is not None)


@sync_to_async
def _decide(user: User, callback_data: TimeOffDecision) -> tuple[str | None, BotMessage | None]:
    """Return an alert to show, if any, and the refreshed request message."""
    approve = callback_data.action == TimeOffAction.APPROVE
    try:
        services.decide(callback_data.time_off_id, approve, by=user)
    except PermissionDenied as exc:
        return str(exc), None
    except DomainError as exc:
        # Decided already, or cancelled: show the approver where it stands now.
        current = services.get(callback_data.time_off_id)
        return str(exc), bot_messages.request(current) if current else None
    return None, bot_messages.request(services.get(callback_data.time_off_id))
