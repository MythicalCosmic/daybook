"""Voice notes become tasks from the owner bot too (v0.2 AI contract §6).

The same flow as the staff bot (apps.ai.bot_flow) in the company the owner runs: with several
companies the bot asks which one first. The card's "Edit" opens the dashboard's voice notes
(only when DASHBOARD_URL is https). In the middle of /new a voice note is left to that
conversation, which answers it.
"""

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.ai import bot_flow, bot_messages
from apps.ai.callbacks import AIDraftCallback
from apps.notifications.telegram import BotName
from ownerbot import bot_messages as owner_messages
from ownerbot import brief
from ownerbot.callbacks import VoicePick
from ownerbot.states import VoiceNote

router = Router(name="voice")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)


@router.message(StateFilter(None, VoiceNote.company), F.voice | F.audio | F.video_note)
async def voice_message(message: Message, user: User, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    members = await sync_to_async(brief.memberships)(user)
    if not members:
        await message.answer(owner_messages.no_companies())
        return
    if len(members) == 1:
        await bot_flow.take_voice(message, members[0], bot, bot_name=BotName.OWNER)
        return
    media = message.voice or message.audio or message.video_note
    await state.set_state(VoiceNote.company)
    await state.update_data(
        file_id=media.file_id, seconds=media.duration or 0, size=media.file_size or 0
    )
    rows = [
        [
            InlineKeyboardButton(
                text=member.company.name, callback_data=VoicePick(company=member.company_id).pack()
            )
        ]
        for member in members
    ]
    await message.answer(
        _("Which company is this voice note for?"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(VoiceNote.company, VoicePick.filter())
async def company_picked(
    callback: CallbackQuery, callback_data: VoicePick, user: User, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    member = await sync_to_async(brief.membership)(user, callback_data.company)
    await callback.answer()
    if member is None or "file_id" not in data:
        await bot_flow.edit(callback.message, (bot_messages.gone(), None))
        return
    seconds = int(data.get("seconds") or 0)
    if refusal := await bot_flow.refused(member, seconds=seconds, size=data.get("size") or 0):
        await bot_flow.edit(callback.message, (refusal, None))
        return
    await bot_flow.edit(callback.message, (bot_messages.listening(), None))
    await bot_flow.start_from_telegram(
        callback.message, member, bot, data["file_id"], seconds=seconds, bot_name=BotName.OWNER
    )


@router.callback_query(AIDraftCallback.filter())
async def draft_button(callback: CallbackQuery, callback_data: AIDraftCallback, user: User) -> None:
    member = await bot_flow.member_for_draft(user, callback_data.id)
    if member is None:
        await callback.answer(bot_messages.gone(), show_alert=True)
        return
    card, note = await bot_flow.act_on_draft(member, callback_data)
    await bot_flow.edit(callback.message, card)
    await callback.answer(note[:200] or None, show_alert=bool(note))
