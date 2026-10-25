"""The mini app opens from inline buttons and the chat's menu button, never from the keyboard:
Telegram gives a Mini App opened from a keyboard button no initData, so it couldn't sign in."""

import pytest
from aiogram.methods import SendMessage, SetChatMenuButton
from aiogram.types import InlineKeyboardMarkup, MenuButtonCommands, MenuButtonWebApp

from apps.members import bot_menu
from apps.tasks.models import Task
from bot.commands import set_commands
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

APP = "https://app.example.com/app/"


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


async def test_the_app_button_answers_with_a_button_that_opens_the_app(
    dp, bot, company, member, settings
):
    settings.EMPLOYEE_MINIAPP_URL = APP
    worker = await member.aregistered(company)

    await dp.feed_update(
        bot, updates.message(updates.tg_user(worker.user.telegram_id), "Open app")
    )

    markup = sent(bot)[-1].reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard[0][0].web_app.url == APP


async def test_the_app_button_ends_the_conversation_it_interrupts(
    dp, bot, company, member, settings
):
    settings.EMPLOYEE_MINIAPP_URL = APP
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Open app"))

    assert sent(bot)[-1].reply_markup.inline_keyboard[0][0].web_app.url == APP
    assert not await Task.objects.filter(assignee=worker).aexists()  # not a task's title


async def test_a_modules_screen_button_opens_its_screen(
    dp, bot, company, member, settings, monkeypatch
):
    settings.EMPLOYEE_MINIAPP_URL = APP
    monkeypatch.setattr(bot_menu, "_buttons", {})
    bot_menu.register_menu_button(
        "Stock", order=10, visible=lambda member: True, web_app_screen="stock"
    )
    worker = await member.aregistered(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "Stock"))

    [[button]] = sent(bot)[-1].reply_markup.inline_keyboard
    assert button.text == "Stock"
    assert button.web_app.url == f"{APP}?screen=stock"


async def test_the_menu_button_opens_the_app_when_it_has_an_https_address(bot, settings):
    settings.EMPLOYEE_MINIAPP_URL = APP

    await set_commands(bot)

    [menu] = [r for r in bot.requests if isinstance(r, SetChatMenuButton)]
    assert isinstance(menu.menu_button, MenuButtonWebApp)
    assert menu.menu_button.web_app.url == APP

    settings.EMPLOYEE_MINIAPP_URL = "http://127.0.0.1:28173/app/"
    await set_commands(bot)
    last = [r for r in bot.requests if isinstance(r, SetChatMenuButton)][-1]
    assert isinstance(last.menu_button, MenuButtonCommands)
