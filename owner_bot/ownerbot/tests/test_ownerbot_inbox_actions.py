"""Notification buttons pressed in the owner bot run the module's registered handler."""

import pytest
from asgiref.sync import sync_to_async

from apps.core.exceptions import DomainError
from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.inbox.registry import register_action, register_kind
from apps.inbox.services import NotificationAction, notify
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def calls(isolated_registries):
    calls = []

    def approve(notification, by, reason):
        calls.append((notification.pk, by.pk))
        return "Claim approved"

    def pay(notification, by, reason):
        raise DomainError("Pick an account first.")

    register_kind("ownertest.claim", label="Claim", audience="owner", default_telegram=False)
    register_action("ownertest.claim", "approve", approve)
    register_action("ownertest.claim", "pay", pay)
    return calls


@sync_to_async
def claim_for(*people) -> list[Notification]:
    return notify(
        people,
        "ownertest.claim",
        title="Claim",
        actions=[NotificationAction("approve", "Approve"), NotificationAction("pay", "Pay")],
    )


def press(item: Notification, key: str) -> str:
    return InboxAction(notification_id=item.pk, key=key).pack()


async def test_the_recipient_approves_from_the_owner_bot(dp, bot, company, member, calls):
    owner = await member.acreate(company, "Owner")
    [item] = await claim_for(owner)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(owner.user.telegram_id), press(item, "approve"))
    )

    assert calls == [(item.pk, owner.pk)]
    [answer] = bot.answers()
    assert (answer.text, answer.show_alert) == ("Claim approved", False)
    await item.arefresh_from_db()
    assert item.acted_at is not None


async def test_someone_else_gets_an_alert(dp, bot, company, member, calls):
    owner = await member.acreate(company, "Owner")
    stranger = await member.acreate(company, "Owner")
    [item] = await claim_for(owner)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(stranger.user.telegram_id), press(item, "approve"))
    )

    assert calls == []
    [answer] = bot.answers()
    assert answer.show_alert is True
    assert answer.text == "You don't have access to this."


async def test_a_refusal_from_the_module_is_shown(dp, bot, company, member, calls):
    owner = await member.acreate(company, "Owner")
    [item] = await claim_for(owner)

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(owner.user.telegram_id), press(item, "pay"))
    )

    [answer] = bot.answers()
    assert (answer.text, answer.show_alert) == ("Pick an account first.", True)
