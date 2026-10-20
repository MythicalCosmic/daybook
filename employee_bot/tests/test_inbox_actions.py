"""Notification buttons in the employee bot (also the owner's fallback bot)."""

import pytest
from aiogram import Dispatcher
from aiogram.methods import AnswerCallbackQuery
from asgiref.sync import sync_to_async

from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.inbox.registry import register_action, register_kind
from apps.inbox.services import NotificationAction, notify
from bot.handlers.features import inbox_actions
from bot.middlewares import register_all_middlewares
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(scope="module")
def inbox_dp():
    """The handler on its own dispatcher (the main one gets it when W0-L3 wires the
    feature routers in)."""
    dp = Dispatcher()
    register_all_middlewares(dp)
    dp.include_router(inbox_actions.make_router())
    return dp


@pytest.fixture
def calls(isolated_registries):
    calls = []

    def seen(notification, by, reason):
        calls.append((notification.pk, by.pk))

    register_kind(
        "employeetest.payslip", label="Payslip", audience="employee", default_telegram=False
    )
    register_action("employeetest.payslip", "received", seen)
    return calls


@sync_to_async
def payslip_for(member) -> Notification:
    [item] = notify(
        [member],
        "employeetest.payslip",
        title="Your October payslip",
        actions=[NotificationAction("received", "I received it")],
    )
    return item


def answers(bot) -> list[AnswerCallbackQuery]:
    return [request for request in bot.requests if isinstance(request, AnswerCallbackQuery)]


def press(item: Notification) -> str:
    return InboxAction(notification_id=item.pk, key="received").pack()


def test_the_module_router_handles_inbox_buttons():
    assert inbox_actions.router.name == "feature_inbox_actions"
    assert inbox_actions.router.callback_query.handlers


async def test_the_recipient_confirms_from_the_employee_bot(inbox_dp, bot, company, member, calls):
    worker = await member.aregistered(company)
    item = await payslip_for(worker)

    await inbox_dp.feed_update(
        bot, updates.callback(updates.tg_user(worker.user.telegram_id), press(item))
    )

    assert calls == [(item.pk, worker.pk)]
    [answer] = answers(bot)
    assert (answer.text, answer.show_alert) == ("Done.", False)


async def test_pressing_twice_is_refused_politely(inbox_dp, bot, company, member, calls):
    worker = await member.aregistered(company)
    item = await payslip_for(worker)
    tg = updates.tg_user(worker.user.telegram_id)

    await inbox_dp.feed_update(bot, updates.callback(tg, press(item)))
    await inbox_dp.feed_update(bot, updates.callback(tg, press(item)))

    assert len(calls) == 1
    assert answers(bot)[-1].show_alert is True
    assert "already" in answers(bot)[-1].text


async def test_a_colleague_cant_press_my_button(inbox_dp, bot, company, member, calls):
    worker = await member.aregistered(company)
    colleague = await member.aregistered(company)
    item = await payslip_for(worker)

    await inbox_dp.feed_update(
        bot, updates.callback(updates.tg_user(colleague.user.telegram_id), press(item))
    )

    assert calls == []
    assert answers(bot)[0].text == "You don't have access to this."
