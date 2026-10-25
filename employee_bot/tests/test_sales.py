"""Sales in the employee bot: the Kassa menu button, handover answers from its summary and
from the notification buttons, and the open-till nudge."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.inbox.callbacks import InboxAction
from apps.inbox.models import Notification
from apps.members.bot_menu import registered
from apps.members.bot_messages import main_menu
from apps.notifications.emoji import has_emoji
from apps.sales import bot_messages, services
from apps.sales.callbacks import HandoverAnswer, SalesHandover
from apps.sales.models import CashMovement
from apps.sales.tests.factories import make_shop
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def shop_with_handover():
    shop = make_shop()
    for person in (shop.cashier, shop.manager, shop.owner, shop.colleague):
        person.onboarded_at = person.created_at
        person.save(update_fields=["onboarded_at"])
    services.open_shift(by=shop.cashier, register=shop.register, opening_float="200000")
    services.record_movement(
        by=shop.cashier, register=shop.register, kind="payout", amount="50000", reason="Water"
    )
    movement = services.record_movement(
        by=shop.cashier,
        register=shop.register,
        kind="handover",
        amount="3500000",
        receiver=shop.manager,
    )
    return shop, movement


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def test_the_kassa_button_is_registered_for_till_runners():
    [button] = [b for b in registered() if b.msgid == bot_messages.KASSA_BUTTON]
    assert button.web_app_screen == "kassa"


async def test_cashiers_see_the_button_in_their_menu(company, member):
    @sync_to_async
    def menus():
        shop = make_shop()
        texts = lambda m: [b.text for row in main_menu(m).keyboard for b in row]  # noqa: E731
        return texts(shop.cashier), texts(shop.manager)

    cashier, manager = await menus()
    assert "Kassa" in cashier
    assert "Kassa" not in manager  # managers don't run a till by default


async def test_the_summary_shows_the_open_till_without_expected_cash(dp, bot):
    shop, _movement = await shop_with_handover()
    await dp.feed_update(
        bot, updates.message(updates.tg_user(shop.cashier.user.telegram_id), "Kassa")
    )
    [reply] = sent(bot)
    assert "CHL-1" in reply.text and "is open" in reply.text
    assert "200 000" in reply.text  # the float the cashier counted
    assert "50 000" in reply.text  # payouts
    assert "3 500 000" in reply.text  # handed over
    # Nothing that tells how much cash there should be (opening + sales - movements).
    assert "expected" not in reply.text.lower()


async def test_the_receiver_confirms_from_the_summary(dp, bot):
    shop, movement = await shop_with_handover()
    user = updates.tg_user(shop.manager.user.telegram_id)
    await dp.feed_update(bot, updates.message(user, "Kassa"))
    [reply] = sent(bot)
    assert "Cash handed to you" in reply.text and "Madina" in reply.text
    buttons = [b.callback_data for row in reply.reply_markup.inline_keyboard for b in row]
    assert SalesHandover(answer=HandoverAnswer.RECEIVED, movement_id=movement.pk).pack() in buttons

    await dp.feed_update(
        bot,
        updates.callback(
            user, SalesHandover(answer=HandoverAnswer.RECEIVED, movement_id=movement.pk).pack()
        ),
    )
    await movement.arefresh_from_db()
    assert movement.confirmed_at is not None and movement.transfer_id is not None
    [edit] = [r for r in bot.requests if isinstance(r, EditMessageText)]
    assert "Received" in edit.text and edit.reply_markup is None


async def test_the_receivers_buttons_say_it_in_their_words(dp, bot):
    shop, _movement = await shop_with_handover()
    await User.objects.filter(pk=shop.manager.user_id).aupdate(language="uz")
    user = updates.tg_user(shop.manager.user.telegram_id)

    await dp.feed_update(bot, updates.message(user, "Kassa"))

    [reply] = sent(bot)
    received, not_received = reply.reply_markup.inline_keyboard[-1]
    assert received.text.endswith(" oldim") and not_received.text == "Olmadim"
    assert not has_emoji(reply.text)


async def test_someone_else_cannot_answer(dp, bot):
    shop, movement = await shop_with_handover()
    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(shop.owner.user.telegram_id),
            SalesHandover(answer=HandoverAnswer.NOT_RECEIVED, movement_id=movement.pk).pack(),
        ),
    )
    [alert] = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert alert.show_alert
    await movement.arefresh_from_db()
    assert movement.declined_at is None


async def test_the_notification_buttons_decline_through_the_inbox(dp, bot):
    shop, movement = await shop_with_handover()

    @sync_to_async
    def notify():
        from apps.sales import alerts

        alerts.handover_sent(movement.pk)  # already sent after commit: never twice
        return Notification.objects.get(kind="sales.handover", recipient=shop.manager)

    note = await notify()
    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(shop.manager.user.telegram_id),
            InboxAction(notification_id=note.pk, key="not_received").pack(),
        ),
    )
    refreshed = await CashMovement.objects.aget(pk=movement.pk)
    assert refreshed.declined_at is not None
    owners_told = await sync_to_async(
        Notification.objects.filter(kind="sales.handover_declined", recipient=shop.owner).exists
    )()
    assert owners_told


async def test_without_a_till_the_summary_says_how_to_open_one(dp, bot):
    @sync_to_async
    def cashier():
        shop = make_shop()
        shop.colleague.onboarded_at = shop.colleague.created_at
        shop.colleague.save(update_fields=["onboarded_at"])
        return shop.colleague

    person = await cashier()
    await dp.feed_update(bot, updates.message(updates.tg_user(person.user.telegram_id), "Kassa"))
    [reply] = sent(bot)
    assert "No till is open" in reply.text
