"""Employee bot, Package E. Sales and cash: "your till is still open", handover
confirmations ([Received] [Not received]) and shift results for cashiers.

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).

- The "Kassa" menu button (registered by `apps.sales.hooks` for people who run a till) opens
  the mini app's Kassa when the bot has an https mini app address; otherwise its text arrives
  here and gets a summary: the open till (never the expected cash: the count is blind), or how
  to open one, plus the handovers waiting for this person with [Received] [Not received].
- Those buttons, like the ones on handover notifications (the shared inbox handler), call the
  same services: the cash moves in the ledger only when its receiver confirms.
- Everything else (till left open, shift verified or disputed) arrives as notifications.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.sales import bot_messages, services
from apps.sales.callbacks import HandoverAnswer, SalesHandover
from apps.sales.models import CashMovement
from bot.filters.membership import IsRegistered
from bot.filters.menu import MenuButton

router = Router(name="feature_sales")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@router.message(F.text, MenuButton(bot_messages.KASSA_BUTTON))
async def kassa(message: Message, membership: Membership) -> None:
    text, markup = await sync_to_async(_status)(membership)
    await message.answer(text, reply_markup=markup)


def _status(membership: Membership):
    if not membership.company.has_feature("sales"):
        return _("Sales aren't switched on in this company."), None
    return bot_messages.kassa_status(membership)


@router.callback_query(SalesHandover.filter())
async def answer_handover(
    query: CallbackQuery, callback_data: SalesHandover, membership: Membership
) -> None:
    try:
        text = await sync_to_async(_answer)(membership, callback_data)
    except DomainError as exc:
        await query.answer(str(exc), show_alert=True)
        return
    await query.answer()
    if query.message is not None:
        await query.message.edit_text(text, reply_markup=None)


def _answer(membership: Membership, data: SalesHandover) -> str:
    movement = CashMovement.objects.filter(
        pk=data.movement_id, company_id=membership.company_id, receiver=membership
    ).first()
    if movement is None:
        raise DomainError(_("Only the person receiving the cash can answer this."))
    if data.answer == HandoverAnswer.RECEIVED:
        movement = services.confirm_handover(movement, by=membership)
    else:
        movement = services.decline_handover(movement, by=membership)
    return bot_messages.handover_answered(data.answer, movement.amount, movement.currency)
