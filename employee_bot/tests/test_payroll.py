"""Payroll in the employee bot: /pay (this month so far, the estimate, the last payslip), the
module switched off, and "I received it" on a paid payslip's message."""

from datetime import date
from decimal import Decimal

import pytest
from aiogram.methods import SendMessage
from asgiref.sync import sync_to_async
from django.core.cache import cache

from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.payroll import services
from apps.payroll.models import PayrollRun, Payslip
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


@sync_to_async
def setup_pay(company, worker):
    company.features = ["payroll"]
    company.save(update_fields=["features"])
    cache.clear()
    services.set_pay(worker, by=None, effective_from=date(2026, 1, 1), amount=Decimal("5200000"))


@sync_to_async
def paid_payslip(company, worker, owner):
    run = PayrollRun.objects.create(company=company, period=date(2026, 9, 1), status="finalized")
    payslip = Payslip.objects.create(
        company=company,
        run=run,
        membership=worker,
        pay_type="monthly",
        net=Decimal("4350000"),
        status=Payslip.Status.PAID,
    )
    from django.utils import timezone

    payslip.published_at = payslip.paid_at = timezone.now()
    payslip.save()
    from apps.payroll import notify

    notify._payslips_paid([payslip.pk])
    return payslip


async def test_pay_shows_the_month_so_far(dp, bot, company, member):
    worker = await member.aregistered(company)
    await setup_pay(company, worker)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/pay"))

    text = sent(bot)[-1].text
    assert "My pay" in text and "Estimate for the month" in text
    assert "5 200 000" in text.replace("\xa0", " ")


async def test_pay_when_the_module_is_off(dp, bot, company, member):
    worker = await member.aregistered(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/pay"))

    assert "Payroll isn't switched on" in sent(bot)[-1].text


async def test_pay_without_a_pay_setup(dp, bot, company, member):
    worker = await member.aregistered(company)
    company.features = ["payroll"]
    await sync_to_async(company.save)(update_fields=["features"])
    await sync_to_async(cache.clear)()

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/pay"))

    assert "isn't set up yet" in sent(bot)[-1].text


async def test_i_received_it_button(dp, bot, company, member):
    worker = await member.aregistered(company)
    owner = await member.aregistered(company, "Owner")
    await setup_pay(company, worker)
    payslip = await paid_payslip(company, worker, owner)
    notification = await sync_to_async(
        lambda: Notification.objects.get(kind="payroll.payslip", recipient=worker)
    )()

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(worker.user.telegram_id),
            InboxAction(notification_id=notification.pk, key="received").pack(),
        ),
    )

    await sync_to_async(payslip.refresh_from_db)()
    assert payslip.received_at is not None
