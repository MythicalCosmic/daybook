"""Labels lost their emoji on 25.10.2026 (the owner: "clear messages without emojis"), but the
keyboards on people's phones keep the old labels until the bot sends a new one: the old buttons
still work, in every language, and the answer brings today's keyboard. The app's helper message
stays one (audit B-15)."""

import pytest
from aiogram.methods import DeleteMessage, SendMessage
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from asgiref.sync import sync_to_async
from django.core.cache import cache

from apps.accounts.models import User
from apps.companies.tests.factories import CompanyFactory
from apps.notifications.emoji import has_emoji
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

APP = "https://app.example.com/app/"


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


async def speaking(worker, language: str):
    await sync_to_async(User.objects.filter(pk=worker.user_id).update)(language=language)
    return updates.tg_user(worker.user.telegram_id)


@pytest.mark.parametrize(
    ("language", "old", "new"),
    [
        ("uz", "📋 Vazifalarim", "Vazifalarim"),
        ("ru", "📋 Мои задачи", "Мои задачи"),
        ("en", "📋 My tasks", "My tasks"),
    ],
)
async def test_an_old_button_still_works_and_brings_the_new_keyboard(
    dp, bot, company, member, language, old, new
):
    worker = await member.aregistered(company)
    tg = await speaking(worker, language)

    await dp.feed_update(bot, updates.message(tg, old))
    answered_old = sent(bot)
    await dp.feed_update(bot, updates.message(tg, new))
    answered_new = sent(bot)[len(answered_old) :]

    # The old label did what the new one does, plus one message with today's keyboard.
    assert [m.text for m in answered_old[:-1]] == [m.text for m in answered_new]
    menu = answered_old[-1]
    assert isinstance(menu.reply_markup, ReplyKeyboardMarkup)
    labels = [button.text for row in menu.reply_markup.keyboard for button in row]
    assert labels[0] == new
    assert not any(has_emoji(label) for label in labels)


async def test_the_new_keyboard_has_no_emoji_anywhere(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = APP
    worker = await member.aregistered(company, "Owner")
    tg = await speaking(worker, "uz")

    await dp.feed_update(bot, updates.message(tg, "/start"))

    home = sent(bot)[-1]
    labels = [button.text for row in home.reply_markup.keyboard for button in row]
    assert labels[:2] == ["Vazifalarim", "Yangi vazifa"]
    assert not any(has_emoji(label) for label in labels)
    assert not has_emoji(home.text)


async def test_the_old_company_button_still_switches(dp, bot, company, member):
    worker = await member.aregistered(company)
    other = await sync_to_async(CompanyFactory)(name="Ikkinchi Dorixona")
    await member.aregistered(other, user=worker.user)
    tg = await speaking(worker, "uz")

    await dp.feed_update(bot, updates.message(tg, f"🏢 {company.name} ▸"))

    picker = sent(bot)[-1]
    assert isinstance(picker.reply_markup, InlineKeyboardMarkup)
    names = [row[0].text for row in picker.reply_markup.inline_keyboard]
    assert sorted(names) == sorted([company.name, "Ikkinchi Dorixona"])


async def test_the_new_company_button_reads_in_words(dp, bot, company, member):
    worker = await member.aregistered(company)
    other = await sync_to_async(CompanyFactory)(name="Ikkinchi Dorixona")
    await member.aregistered(other, user=worker.user)
    tg = await speaking(worker, "uz")

    await dp.feed_update(bot, updates.message(tg, "/start"))
    labels = [b.text for row in sent(bot)[-1].reply_markup.keyboard for b in row]
    [switch] = [label for label in labels if label.startswith("Kompaniya: ")]

    await dp.feed_update(bot, updates.message(tg, switch))
    picker = sent(bot)[-1]
    assert "Hozir: " in picker.text  # the current company in words, its button coloured
    assert [row[0].style for row in picker.reply_markup.inline_keyboard].count("success") == 1


async def test_the_app_keeps_one_helper_message(dp, bot, company, member, settings):
    settings.EMPLOYEE_MINIAPP_URL = APP
    worker = await member.aregistered(company)
    tg = await speaking(worker, "uz")

    await dp.feed_update(bot, updates.message(tg, "Ilovani ochish"))
    first = sent(bot)[-1]
    assert first.reply_markup.inline_keyboard[0][0].web_app.url == APP
    assert "«Ilovani ochish»" in first.text  # the chat's own menu button, one tap next time
    first_id = bot.requests.index(first) + 1  # the mocked bot numbers messages by request
    assert not [r for r in bot.requests if isinstance(r, DeleteMessage)]

    await dp.feed_update(bot, updates.message(tg, "📱 Ilovani ochish"))  # an old keyboard

    [deleted] = [r for r in bot.requests if isinstance(r, DeleteMessage)]
    assert deleted.message_id == first_id
    helper, menu = sent(bot)[-2:]
    assert helper.reply_markup.inline_keyboard[0][0].web_app.url == APP
    assert isinstance(menu.reply_markup, ReplyKeyboardMarkup)  # and today's keyboard, once
