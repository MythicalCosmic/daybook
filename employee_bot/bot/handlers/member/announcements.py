from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.announcements import bot_messages, services
from apps.announcements.callbacks import AnnounceAction, AnnounceCallback
from apps.core.exceptions import DomainError
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership, Position
from apps.members.permissions import Perm
from bot.filters.membership import IsRegistered
from bot.states.tasks import Announce

router = Router(name="member_announcements")
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@router.message(Command("announce"))
async def start(message: Message, membership: Membership, state: FSMContext) -> None:
    if not membership.has_perm(Perm.ANNOUNCE):
        await message.answer(_("Only managers can send announcements."))
        return
    await state.set_state(Announce.text)
    text, markup = bot_messages.ask_text()
    await message.answer(text, reply_markup=markup)


@router.message(Announce.text, F.text)
async def got_text(message: Message, membership: Membership, state: FSMContext) -> None:
    draft = message.html_text  # keeps the author's bold, italics and links
    if len(draft) > services.MAX_LENGTH:
        limit = _("That's too long for one message: %(limit)d characters at most.")
        await message.answer(limit % {"limit": services.MAX_LENGTH})
        return
    await state.update_data(text=draft, positions=[])
    await state.set_state(Announce.audience)
    text, markup = await _preview(membership, draft, set())
    await message.answer(text, reply_markup=markup)


@router.callback_query(Announce.audience, AnnounceCallback.filter(F.action == AnnounceAction.PICK))
async def pick(
    callback: CallbackQuery,
    callback_data: AnnounceCallback,
    membership: Membership,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    chosen = set(data["positions"]) ^ {callback_data.position_id}
    await state.update_data(positions=sorted(chosen))
    # The text too: its "Chosen positions: …" line says what the green buttons are.
    text, markup = await _preview(membership, data["text"], chosen)
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(Announce.audience, AnnounceCallback.filter(F.action == AnnounceAction.SEND))
async def send(callback: CallbackQuery, membership: Membership, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        text, markup = await _publish(membership, data["text"], data["positions"])
    except (PermissionDenied, DomainError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await state.clear()
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(
    AnnounceCallback.filter(F.action.in_({AnnounceAction.PICK, AnnounceAction.SEND}))
)
async def stale_draft(callback: CallbackQuery) -> None:
    await callback.answer(
        _("This draft has expired. Send /announce to start again."), show_alert=True
    )


@router.callback_query(AnnounceCallback.filter(F.action == AnnounceAction.CANCEL))
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(_("Okay, cancelled."))
    await callback.answer()


@router.callback_query(AnnounceCallback.filter(F.action == AnnounceAction.READ))
async def read(callback: CallbackQuery, callback_data: AnnounceCallback, user: User) -> None:
    message = await _mark_read(callback_data.announcement_id, user)
    if message is not None:
        text, markup = message
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(_("Thank you!") if message else None)


@router.callback_query(AnnounceCallback.filter(F.action == AnnounceAction.WHO))
async def who(callback: CallbackQuery, callback_data: AnnounceCallback, user: User) -> None:
    try:
        text, markup = await _who(callback_data.announcement_id, user)
    except (PermissionDenied, DomainError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@sync_to_async
def _preview(membership: Membership, draft: str, chosen: set[int]) -> BotMessage:
    positions = list(
        Position.objects.for_company(membership.company_id).filter(is_active=True).order_by("order")
    )
    return bot_messages.preview(draft, positions, chosen)


@sync_to_async
def _publish(membership: Membership, draft: str, position_ids: list[int]) -> BotMessage:
    announcement = services.publish(membership, draft, position_ids)
    return bot_messages.sent(announcement, announcement.receipts.count())


@sync_to_async
def _mark_read(announcement_id: int, user: User) -> BotMessage | None:
    receipt = services.mark_read(announcement_id, user)
    return bot_messages.read_copy(receipt.announcement) if receipt else None


@sync_to_async
def _who(announcement_id: int, user: User) -> BotMessage:
    read, unread = services.readers(announcement_id, user)
    return bot_messages.who(read, unread)
