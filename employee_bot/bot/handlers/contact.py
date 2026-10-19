from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.types import Contact, Message
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.services import save_verified_phone
from apps.members import bot_messages, services
from apps.members.models import Membership

# Before the member gate: people still creating their account share their phone too.
router = Router(name="contact")


@router.message(F.contact, F.chat.type == ChatType.PRIVATE)
async def save_phone(message: Message, user: User) -> None:
    reply = await _save(user, message.contact)
    if reply is not None:
        text, markup = reply
        await message.answer(text, reply_markup=markup)


@sync_to_async
def _save(user: User, contact: Contact) -> bot_messages.BotMessage | None:
    membership = services.current_membership(user)
    if membership is None or membership.status not in (
        Membership.Status.PENDING,
        Membership.Status.APPROVED,
    ):
        return bot_messages.status(membership)
    saved = save_verified_phone(
        user, contact_user_id=contact.user_id, phone_number=contact.phone_number
    )
    if not saved:
        return bot_messages.foreign_contact()
    membership.user = user  # same person, now with the phone the next step depends on
    return bot_messages.phone_saved(membership)
