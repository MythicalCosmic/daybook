"""Employee bot, Package Q. Knowledge base: "new page to read" and "I've read it".

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).

- `/kb`: the pages the person still has to confirm, one button each.
- A page button (and the notification's "📖 Read", through the inbox) sends the page into the
  chat as text, with "✅ I've read it" when the page asks for it.
- `/start kb_<id>` opens a page from a link.
"""

from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.knowledge import bot_messages, queries, services
from apps.knowledge.callbacks import KbAction, KbCallback
from apps.knowledge.models import Page
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.members.services import current_membership
from bot.deeplinks import register_start_param
from bot.filters.membership import IsRegistered

router = Router(name="feature_knowledge")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@router.message(Command("kb"))
async def to_read(message: Message, membership: Membership) -> None:
    text, markup = await _to_read(membership)
    await message.answer(text, reply_markup=markup)


@router.callback_query(KbCallback.filter())
async def on_button(callback: CallbackQuery, callback_data: KbCallback, membership: Membership):
    if callback_data.action == KbAction.LIST:
        text, markup = await _to_read(membership)
        await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    page = await _page(membership, callback_data.page_id)
    if page is None:
        await callback.answer(bot_messages.not_found(), show_alert=True)
        return
    if callback_data.action == KbAction.OPEN:
        text, markup = await _page_message(membership, page)
        await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    # "I've read it": only for the version on the screen; a newer one is sent instead.
    if callback_data.version and callback_data.version != page.version:
        await callback.answer(_("This page has changed. Here is the new version."), show_alert=True)
        text, markup = await _page_message(membership, page)
        await callback.message.answer(text, reply_markup=markup)
        return
    try:
        text, markup = await _acknowledge(membership, page)
    except PermissionDenied as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    with suppress(TelegramBadRequest):
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer(bot_messages.thanks())


async def open_from_link(message: Message, payload: str, *, user: User, state: FSMContext):
    """`/start kb_12`: the page, when the person may read it."""
    membership = await sync_to_async(current_membership)(user)
    if (
        membership is None
        or membership.status != Membership.Status.APPROVED
        or not membership.is_onboarded
        or not payload.isdigit()
    ):
        await message.answer(bot_messages.not_found())
        return
    page = await _page(membership, int(payload))
    if page is None:
        await message.answer(bot_messages.not_found())
        return
    text, markup = await _page_message(membership, page)
    await message.answer(text, reply_markup=markup)


register_start_param("kb_", open_from_link)


@sync_to_async
def _to_read(membership: Membership) -> BotMessage:
    return bot_messages.to_read(queries.to_read(membership))


@sync_to_async
def _page(membership: Membership, page_id: int) -> Page | None:
    return queries.reader_pages(membership).select_related("space").filter(pk=page_id).first()


@sync_to_async
def _page_message(membership: Membership, page: Page) -> BotMessage:
    ack = queries.my_ack(membership, page)
    return bot_messages.page_message(
        page, read=ack is not None and queries.is_read(ack.version, page)
    )


@sync_to_async
def _acknowledge(membership: Membership, page: Page) -> BotMessage:
    services.acknowledge(page, by=membership)
    page.refresh_from_db()
    return bot_messages.acked(page)
