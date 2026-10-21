"""`/today` (a company's day in one message) and `/dashboard` (open the console).

Both end a conversation in progress, like every menu command.
"""

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils import translation

from apps.accounts.models import User
from ownerbot import bot_messages, brief
from ownerbot.callbacks import TodayPick

router = Router(name="today")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


@sync_to_async
def _today_for(user: User, company_id: int | None) -> bot_messages.BotMessage:
    members = brief.memberships(user)
    if not members:
        return bot_messages.no_companies(), None
    if company_id is None and len(members) > 1:
        return bot_messages.pick_company([(m.company_id, m.company.name) for m in members])
    member = members[0] if company_id is None else brief.membership(user, company_id)
    if member is None:
        return bot_messages.no_companies(), None
    with translation.override(user.language):
        return brief.today(member)


@router.message(Command("today"))
async def cmd_today(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _today_for(user, None)
    await message.answer(text, reply_markup=markup)


@router.callback_query(TodayPick.filter())
async def picked(callback: CallbackQuery, callback_data: TodayPick, user: User) -> None:
    text, markup = await _today_for(user, callback_data.company)
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = bot_messages.open_dashboard()
    await message.answer(text, reply_markup=markup)
