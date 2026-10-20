"""`/start` and the block/unblock notices Telegram sends about private chats.

Starting the bot is what lets owner notifications come here instead of through the employee
bot (`OwnerUserMiddleware` records it). Package A grows `/start` (sign-in links, `new_` codes).
"""

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import CommandStart
from aiogram.types import ChatMemberUpdated, Message
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.accounts.models import User
from ownerbot import bot_messages

router = Router(name="start")


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, user: User) -> None:
    text, markup = bot_messages.welcome(user)
    await message.answer(text, reply_markup=markup)


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
