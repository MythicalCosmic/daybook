"""`/start` and the block/unblock notices Telegram sends about private chats.

Starting the bot is what lets owner notifications come here instead of through the employee
bot (`OwnerUserMiddleware` records it). Deep links:

    /start login_<code>   confirm a dashboard sign-in (number matching)
    /start new_<code>     create a company with that signup code
"""

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatMemberUpdated, Message
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.accounts.models import User
from ownerbot import bot_messages, brief
from ownerbot.handlers import language, new_company, signin

router = Router(name="start")


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(
    message: Message, user: User, state: FSMContext, command: CommandObject | None = None
) -> None:
    payload = (command.args or "").strip() if command else ""
    if payload.startswith(signin.START_PREFIX):
        await signin.start_login(
            message, payload.removeprefix(signin.START_PREFIX), user=user, state=state
        )
        return
    if payload.startswith(new_company.START_PREFIX):
        await new_company.begin(
            message, user, state, code=payload.removeprefix(new_company.START_PREFIX)
        )
        return
    await state.clear()
    companies = await sync_to_async(brief.companies_summary)(user)
    if not companies and await sync_to_async(brief.works_elsewhere)(user):
        text, markup = bot_messages.not_for_you(), None  # a manager, not an owner or top manager
    else:
        text, markup = bot_messages.welcome(user, companies)
    # Everyone starts in Uzbek; this one small button offers the other languages.
    await message.answer(text, reply_markup=language.with_language_button(markup))


@router.my_chat_member(F.chat.type == ChatType.PRIVATE)
async def chat_member_changed(update: ChatMemberUpdated, user: User | None = None) -> None:
    if user is None:
        return
    blocked = update.new_chat_member.status == ChatMemberStatus.KICKED
    await sync_to_async(_record_block)(user, blocked)


def _record_block(user: User, blocked: bool) -> None:
    if blocked:
        User.objects.filter(pk=user.pk).update(owner_bot_blocked_at=timezone.now())
    else:
        User.objects.filter(pk=user.pk).update(
            owner_bot_blocked_at=None,
            owner_bot_started_at=user.owner_bot_started_at or timezone.now(),
        )
