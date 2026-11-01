"""Voice messages become tasks (v0.2 AI contract §6).

A registered member sends a voice message, an audio file or a video note: the bot answers
"Eshitayapman…" at once and the ai worker edits that message into the card of the tasks it
understood (apps.ai.bot_flow). The card's buttons land here too: Create, Cancel, and Undo
after an automatic create. A voice message ends whatever the bot was asking for, the "New
task" title included (this router comes before that one); a task waiting for its proof photo
keeps its own handler, which comes first.
"""

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from apps.ai import bot_flow
from apps.ai.callbacks import AIDraftCallback
from apps.members.models import Membership
from apps.notifications.telegram import BotName
from bot.filters.membership import IsRegistered
from bot.handlers.member import cards

router = Router(name="member_voice")
router.message.filter(IsRegistered(), F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(IsRegistered())


@router.message(F.voice | F.audio | F.video_note)
async def voice_message(
    message: Message, membership: Membership, state: FSMContext, bot: Bot
) -> None:
    if await state.get_state() is not None:
        await state.clear()  # dictating replaces whatever was being typed
    await bot_flow.take_voice(message, membership, bot, bot_name=BotName.EMPLOYEE)


@router.callback_query(AIDraftCallback.filter())
async def draft_button(
    callback: CallbackQuery, callback_data: AIDraftCallback, membership: Membership
) -> None:
    card, note = await bot_flow.act_on_draft(membership, callback_data)
    await cards.edit(callback, card)
    await callback.answer(note[:200] or None, show_alert=bool(note))
