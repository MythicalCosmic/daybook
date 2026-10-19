from aiogram import F, Router
from aiogram.types import Contact, Message
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.services import save_verified_phone
from apps.members import bot_messages
from apps.members.models import Membership

router = Router(name="member_contact")


@router.message(F.contact)
async def save_phone(message: Message, membership: Membership, user: User) -> None:
    text, markup = await _save(user, membership, message.contact)
    await message.answer(text, reply_markup=markup)


@sync_to_async
def _save(user: User, membership: Membership, contact: Contact) -> bot_messages.BotMessage:
    saved = save_verified_phone(
        user, contact_user_id=contact.user_id, phone_number=contact.phone_number
    )
    if not saved:
        return bot_messages.foreign_contact()
    membership.user = user  # same person, now with the phone the next step depends on
    return bot_messages.phone_saved(membership)
