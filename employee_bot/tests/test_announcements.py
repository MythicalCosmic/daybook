import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
)
from asgiref.sync import sync_to_async

from apps.announcements.callbacks import AnnounceAction, AnnounceCallback
from apps.announcements.models import Announcement, Receipt
from apps.members.tests.factories import PositionFactory
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

make_position = sync_to_async(PositionFactory)


def press(action: AnnounceAction, **fields) -> str:
    return AnnounceCallback(action=action, **fields).pack()


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def labels(markup) -> list[str]:
    return [row[0].text for row in markup.inline_keyboard]


async def test_a_manager_announces_to_one_position(dp, bot, company, member, sent_messages):
    cashier = await make_position(company=company, name="Cashier")
    await make_position(company=company, name="Courier")
    manager = await member.aregistered(company, "Manager")
    reader = await member.aregistered(company, position=cashier, first_name="Ali")
    other = await member.aregistered(company)
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/announce"))
    assert "one message" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.message(tg, "Inventory on Friday at 8:00."))
    preview = sent(bot)[-1]
    assert "Inventory on Friday at 8:00." in preview.text
    assert labels(preview.reply_markup) == [
        "▫️ Cashier",
        "▫️ Courier",
        "📤 Send to everyone",
        "✖️ Cancel",
    ]

    await dp.feed_update(
        bot, updates.callback(tg, press(AnnounceAction.PICK, position_id=cashier.pk))
    )
    [picked] = [r for r in bot.requests if isinstance(r, EditMessageReplyMarkup)]
    assert labels(picked.reply_markup)[:3] == [
        "✅ Cashier",
        "▫️ Courier",
        "📤 Send to the chosen positions",
    ]

    await dp.feed_update(bot, updates.callback(tg, press(AnnounceAction.SEND)))

    announcement = await Announcement.objects.aget()
    assert "Recipients: 1." in [r for r in bot.requests if isinstance(r, EditMessageText)][-1].text
    assert [m["chat_id"] for m in sent_messages] == [reader.user.telegram_id]
    assert other.user.telegram_id not in [m["chat_id"] for m in sent_messages]

    reader_tg = updates.tg_user(reader.user.telegram_id)
    await dp.feed_update(
        bot,
        updates.callback(reader_tg, press(AnnounceAction.READ, announcement_id=announcement.pk)),
    )
    receipt = await Receipt.objects.aget(membership=reader)
    assert receipt.read_at is not None
    assert (
        "You have read this" in [r for r in bot.requests if isinstance(r, EditMessageText)][-1].text
    )

    await dp.feed_update(
        bot, updates.callback(tg, press(AnnounceAction.WHO, announcement_id=announcement.pk))
    )
    assert sent(bot)[-1].text == "📣 Read by 1 of 1."


async def test_only_managers_announce(dp, bot, company, member):
    worker = await member.aregistered(company)

    await dp.feed_update(
        bot, updates.message(updates.tg_user(worker.user.telegram_id), "/announce")
    )

    assert sent(bot)[-1].text == "Only managers can send announcements."


async def test_an_old_draft_cannot_be_sent(dp, bot, company, member):
    manager = await member.aregistered(company, "Manager")

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(manager.user.telegram_id), press(AnnounceAction.SEND))
    )

    alerts = [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]
    assert alerts and "/announce" in alerts[0]
    assert not await Announcement.objects.aexists()


async def test_the_draft_can_be_dropped(dp, bot, company, member):
    manager = await member.aregistered(company, "Manager")
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/announce"))
    await dp.feed_update(bot, updates.callback(tg, press(AnnounceAction.CANCEL)))
    await dp.feed_update(bot, updates.message(tg, "just chatting"))

    assert not await Announcement.objects.aexists()
    assert "cancelled" in [r for r in bot.requests if isinstance(r, EditMessageText)][-1].text
