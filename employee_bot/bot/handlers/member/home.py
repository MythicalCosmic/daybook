from aiogram import Router
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.members import bot_messages
from apps.members.models import Membership

router = Router(name="member_home")


@router.message()
async def home(message: Message, membership: Membership) -> None:
    text, markup = await sync_to_async(bot_messages.member_home)(membership)
    await message.answer(text, reply_markup=markup)
