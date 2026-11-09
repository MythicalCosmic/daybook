"""/language and the home message's language button."""

import pytest
from aiogram.methods import DeleteMessage, EditMessageReplyMarkup, SetMyCommands
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.telegram_chat import CHANGED_SHORT, LANGUAGE_BUTTON, LANGUAGE_NAMES
from davomat_bot.callbacks import HomeLanguage, PickLanguage
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


async def test_the_picker_names_the_languages_uzbek_first(dp, bot, linked):
    await sync_to_async(linked)("Employee", 8201, language="uz")

    await dp.feed_update(bot, updates.message(updates.tg_user(8201), "/language"))

    [reply] = bot.sent()
    assert reply.text == "Tilni tanlang. Hozir: O‘zbekcha."
    [row] = reply.reply_markup.inline_keyboard
    assert [b.text for b in row] == [LANGUAGE_NAMES[c] for c in ("uz", "ru", "en")]
    assert row[0].style == "success"


async def test_picking_a_language_keeps_it_and_relabels_the_menu(dp, bot, linked):
    await sync_to_async(linked)("Manager", 8202, language="uz")

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8202), PickLanguage(code="ru").pack())
    )

    assert (await User.objects.aget(telegram_id=8202)).language == "ru"
    assert any(isinstance(r, DeleteMessage) for r in bot.requests)
    assert bot.sent()[-1].text == CHANGED_SHORT["ru"]
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert "today" in [c.command for c in menu.commands]


async def test_someone_not_linked_reads_the_home_message_in_their_pick(dp, bot, org):
    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8203, "Olim"), PickLanguage(code="en").pack())
    )

    [edit] = bot.edits()
    assert "attendance bot of <b>Namuna MChJ</b>" in edit.text
    assert not await User.objects.filter(telegram_id=8203).aexists()


async def test_the_home_button_shows_the_languages_in_place(dp, bot, linked):
    await sync_to_async(linked)("Employee", 8204)
    home = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=LANGUAGE_BUTTON, callback_data=HomeLanguage(code="").pack())]
        ]
    )

    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(8204), HomeLanguage(code="").pack(), markup=home),
    )

    [edit] = [r for r in bot.requests if isinstance(r, EditMessageReplyMarkup)]
    [row] = edit.reply_markup.inline_keyboard
    assert [b.text for b in row] == [LANGUAGE_NAMES[c] for c in ("uz", "ru", "en")]

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(8204), HomeLanguage(code="ru").pack())
    )

    assert (await User.objects.aget(telegram_id=8204)).language == "ru"
    assert bot.edits()[-1].reply_markup.inline_keyboard[-1][0].text == LANGUAGE_BUTTON
