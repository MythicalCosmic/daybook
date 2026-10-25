"""The knowledge base in the employee bot: /kb, reading a page in the chat, "I've read it"."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from asgiref.sync import sync_to_async

from apps.knowledge.callbacks import KbAction, KbCallback
from apps.knowledge.models import Page, PageAck
from apps.knowledge.tests.factories import PageFactory, SpaceFactory
from apps.members.tests.factories import PositionFactory
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

make_page = sync_to_async(PageFactory)
make_space = sync_to_async(SpaceFactory)
make_position = sync_to_async(PositionFactory)


def press(action: KbAction, **fields) -> str:
    return KbCallback(action=action, **fields).pack()


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def answers(bot) -> list[AnswerCallbackQuery]:
    return [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]


async def test_kb_lists_the_pages_to_read(dp, bot, company, member):
    worker = await member.aregistered(company)
    space = await make_space(company=company)
    await make_page(space=space, title="Ish tartibi", require_ack=True)
    await make_page(space=space, title="Just info")

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/kb"))

    reply = sent(bot)[-1]
    assert "Pages to read" in reply.text
    assert [row[0].text for row in reply.reply_markup.inline_keyboard] == ["Ish tartibi"]


async def test_nothing_to_read(dp, bot, company, member):
    worker = await member.aregistered(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "/kb"))

    assert "read everything" in sent(bot)[-1].text


async def test_read_a_page_in_the_chat_and_confirm(dp, bot, company, member):
    worker = await member.aregistered(company)
    space = await make_space(company=company)
    page = await make_page(
        space=space,
        title="Kassa",
        body="<h2>Ochish</h2><p>Razmenni <strong>sanang</strong></p>",
        require_ack=True,
    )
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(KbAction.OPEN, page_id=page.pk)))
    shown = sent(bot)[-1]
    assert "<b>Ochish</b>" in shown.text and "<b>sanang</b>" in shown.text
    [[ack_button]] = shown.reply_markup.inline_keyboard
    assert ack_button.text == "I've read it"

    await dp.feed_update(bot, updates.callback(tg, ack_button.callback_data))

    assert await PageAck.objects.filter(page=page, membership=worker, version=1).aexists()
    edited = [r for r in bot.requests if isinstance(r, EditMessageText)][-1]
    assert "You've confirmed reading this version" in edited.text
    assert answers(bot)[-1].text == "Thank you! Marked as read."


async def test_confirming_an_outdated_version_sends_the_new_one(dp, bot, company, member):
    worker = await member.aregistered(company)
    page = await make_page(space=await make_space(company=company), require_ack=True)
    await Page.objects.filter(pk=page.pk).aupdate(version=2, ack_version=2)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(KbAction.ACK, page_id=page.pk, version=1)))

    assert not await PageAck.objects.filter(page=page).aexists()
    assert answers(bot)[-1].show_alert is True
    assert sent(bot)[-1].reply_markup.inline_keyboard[0][0].text == "I've read it"


async def test_a_page_for_other_positions_isnt_shown(dp, bot, company, member):
    cashier = await make_position(company=company, name="Cashier")
    worker = await member.aregistered(company)
    space = await make_space(company=company, audience_all=False, positions=[cashier])
    page = await make_page(space=space)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(worker.user.telegram_id), press(KbAction.OPEN, page_id=page.pk)
        ),
    )

    assert answers(bot)[-1].show_alert is True
    assert "isn't available" in answers(bot)[-1].text


async def test_open_a_page_from_a_link(dp, bot, company, member):
    worker = await member.aregistered(company)
    page = await make_page(space=await make_space(company=company), title="Telefonlar")
    draft = await make_page(space=await make_space(company=company), published=False)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, f"/start kb_{page.pk}"))
    assert "Telefonlar" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.message(tg, f"/start kb_{draft.pk}"))
    assert "isn't available" in sent(bot)[-1].text
