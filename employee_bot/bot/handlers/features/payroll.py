"""Employee bot, Package H. Payroll: `/pay` (this month so far, the estimate, the last payslip
and a button to the wallet).

Bonuses, fines, advance decisions and published payslips (with the PDF) arrive as inbox
notifications; "I received it" is an inbox action (apps.payroll.actions).

Registered inside the member router, after the state-bound tasks and announcements routers
and before the home router (docs/PLAN-OWNER.md §10.2, rule 20).
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from asgiref.sync import sync_to_async

from apps.members.models import Membership
from bot.filters.membership import IsRegistered

router = Router(name="feature_payroll")
# Members who finished registering; home asks the others to register first.
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@router.message(Command("pay"))
async def my_pay(message: Message, membership: Membership) -> None:
    text, markup = await _my_pay(membership)
    await message.answer(text, reply_markup=markup)


@sync_to_async
def _my_pay(membership: Membership):
    from apps.payroll import bot_messages, earnings
    from apps.payroll.models import Payslip

    if not membership.company.has_feature("payroll"):
        return bot_messages.module_off()
    current = earnings.current(membership)
    last = (
        Payslip.objects.filter(membership=membership, published_at__isnull=False)
        .exclude(status=Payslip.Status.DRAFT)
        .select_related("run")
        .order_by("-run__period", "-pk")
        .first()
    )
    return bot_messages.my_pay(membership, current, last)
