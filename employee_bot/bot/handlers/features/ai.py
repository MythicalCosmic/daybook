"""Employee bot, Package K. AI: the agents' buttons (the deadline watcher's "+1 hour").

Voice messages and the voice-note card are the `member_voice` router's (before "New task").
Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.ai import bot_messages, services
from apps.ai.callbacks import AILateCallback, LateAction
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from bot.filters.membership import IsRegistered
from bot.handlers.member import cards

router = Router(name="feature_ai")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@sync_to_async
def _give_an_hour(member: Membership, task_id: int) -> tuple[str, bool]:
    try:
        task = services.give_an_hour(task_id, by=member)
    except (DomainError, PermissionDenied) as exc:
        return str(exc), False
    return bot_messages.hour_more_done(task, timezone.now()), True


@router.callback_query(AILateCallback.filter(F.action == LateAction.HOUR_MORE))
async def hour_more(
    callback: CallbackQuery, callback_data: AILateCallback, membership: Membership
) -> None:
    text, done = await _give_an_hour(membership, callback_data.task_id)
    if done and callback.message is not None:
        await cards.edit(callback, (f"{callback.message.html_text}\n\n{text}", None))
    await callback.answer(text if not done else None, show_alert=not done)
