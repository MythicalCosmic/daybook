"""Employee bot, Package R. Recognition: `/kudos` and "Madina thanked you" messages.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).

- `/kudos`: how many colleagues the person can still thank today, and the button that opens the
  mini app's "Say thanks" sheet (a Mini App button needs the app's https address).
- The receiver's message ("Madina thanked you: careful work.") goes out from the backend
  (`apps.recognition.notify.kudos`, a Celery job after commit); its "Say thanks back" opens the
  same sheet with the giver picked, so no callback lands here. Plain words, no emoji.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.recognition import bot_messages, conf, services
from bot.filters.membership import IsRegistered

router = Router(name="feature_recognition")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@router.message(Command("kudos"))
async def kudos(message: Message, membership: Membership) -> None:
    text, markup = await _kudos_command(membership)
    await message.answer(text, reply_markup=markup)


@sync_to_async
def _kudos_command(membership: Membership) -> BotMessage:
    company = membership.company
    enabled = conf.is_on(company) and conf.get_settings(company).kudos_enabled
    left = services.kudos_left(membership) if enabled else None
    return bot_messages.kudos_command(enabled=enabled, left=left)
