"""Notification buttons pressed in the Davomat bot run the module's registered handler."""

import pytest
from asgiref.sync import sync_to_async

from apps.core.exceptions import DomainError
from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.inbox.registry import register_action, register_kind
from apps.inbox.services import NotificationAction, notify
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def calls(isolated_registries):
    calls = []

    def approve(notification, by, reason):
        calls.append((notification.pk, by.pk))
        return "Correction approved"

    def refuse(notification, by, reason):
        raise DomainError("This correction was already decided.")

    register_kind("davomattest.fix", label="Fix", audience="owner", default_telegram=False)
    register_action("davomattest.fix", "approve", approve)
    register_action("davomattest.fix", "reject", refuse)
    return calls


@sync_to_async
def fix_for(*people) -> list[Notification]:
    return notify(
        people,
        "davomattest.fix",
        title="Correction",
        actions=[NotificationAction("approve", "Approve"), NotificationAction("reject", "Reject")],
    )


def press(item: Notification, key: str) -> str:
    return InboxAction(notification_id=item.pk, key=key).pack()


async def test_the_recipient_approves_from_the_bot(dp, bot, linked, calls):
    boss = await sync_to_async(linked)("Manager", 8301)
    [item] = await fix_for(boss)

    await dp.feed_update(bot, updates.callback(updates.tg_user(8301), press(item, "approve")))

    assert calls == [(item.pk, boss.pk)]
    [answer] = bot.answers()
    assert (answer.text, answer.show_alert) == ("Correction approved", False)
    await item.arefresh_from_db()
    assert item.acted_at is not None


async def test_a_refusal_is_shown_and_strangers_are_turned_away(dp, bot, linked, calls):
    boss = await sync_to_async(linked)("Manager", 8302)
    [item] = await fix_for(boss)

    await dp.feed_update(bot, updates.callback(updates.tg_user(8302), press(item, "reject")))
    await dp.feed_update(bot, updates.callback(updates.tg_user(8399), press(item, "approve")))

    refused, stranger = bot.answers()
    assert (refused.text, refused.show_alert) == ("This correction was already decided.", True)
    assert (stranger.text, stranger.show_alert) == ("You don't have access to this.", True)
    assert calls == []
