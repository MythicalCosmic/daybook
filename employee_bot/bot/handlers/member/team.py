"""\"My team\": a department head's people and their work (apps.members.departments)."""

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.members.bot_messages import MENU_MY_TEAM
from apps.members.departments import leads
from apps.members.models import Membership
from apps.tasks import bot_messages as task_messages
from bot.filters.menu import MenuButton

router = Router(name="team")


@router.message(MenuButton(MENU_MY_TEAM))
async def show_team(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _team(membership)
    await message.answer(text, reply_markup=markup)


@sync_to_async
def _team(membership: Membership):
    if not leads(membership):
        return _("You don't head a department."), None
    return task_messages.team_summary(membership)
