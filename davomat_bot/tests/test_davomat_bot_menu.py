"""The button beside the message field: the web app as a Mini App for the people who use it, the
command menu for everyone else; set when a link is claimed, on /start and a language change, and
once per token version for everyone linked when the bot starts."""

import pytest
from aiogram.methods import SetChatMenuButton
from aiogram.types import MenuButtonCommands, MenuButtonWebApp
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import User
from apps.davomat import conf as davomat_conf
from apps.davomat import services as davomat_services
from davomat_bot import bot_messages, commands
from davomat_bot.callbacks import PickLanguage
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)

APP = "https://davomat.example.uz/dashboard/"


@pytest.fixture(autouse=True)
def https(settings):
    settings.DASHBOARD_URL = APP
    cache.clear()
    yield settings
    cache.clear()


@pytest.fixture
def link_for(org):
    row = davomat_conf.get_settings(org)
    row.bot_username = "davomat_test_bot"
    row.save(update_fields=["bot_username"])
    return lambda membership: davomat_services.make_link(membership, by=None).code


def menus(bot) -> list[SetChatMenuButton]:
    return [r for r in bot.requests if isinstance(r, SetChatMenuButton)]


async def test_an_admin_who_links_gets_the_web_app_beside_the_message_field(
    dp, bot, linked, link_for, org
):
    admin = await sync_to_async(linked)("Owner", first_name="Dilnoza")
    code = await sync_to_async(link_for)(admin)

    await dp.feed_update(bot, updates.message(updates.tg_user(9101), f"/start link_{code}"))

    [menu] = menus(bot)
    assert menu.chat_id == 9101
    assert isinstance(menu.menu_button, MenuButtonWebApp)
    assert menu.menu_button.text == "Davomat"
    assert menu.menu_button.web_app.url == f"{APP}c/{org.pk}"
    # The linked message's own button opens it the same way.
    [[web], _language] = bot.sent()[0].reply_markup.inline_keyboard
    assert web.text == "Open Davomat" and web.web_app.url == f"{APP}c/{org.pk}"


async def test_an_employee_keeps_the_command_menu(dp, bot, linked, link_for):
    aziz = await sync_to_async(linked)("Employee", first_name="Aziz")
    code = await sync_to_async(link_for)(aziz)

    await dp.feed_update(bot, updates.message(updates.tg_user(9102), f"/start link_{code}"))

    [menu] = menus(bot)
    assert isinstance(menu.menu_button, MenuButtonCommands)


async def test_start_puts_the_button_right(dp, bot, linked, settings):
    await sync_to_async(linked)("Manager", 9103)

    await dp.feed_update(bot, updates.message(updates.tg_user(9103), "/start"))
    assert isinstance(menus(bot)[-1].menu_button, MenuButtonWebApp)

    # Without an https address Telegram can't open the web app: the commands again.
    settings.DASHBOARD_URL = "http://10.0.0.5/dashboard/"
    await dp.feed_update(bot, updates.message(updates.tg_user(9103), "/start"))
    assert isinstance(menus(bot)[-1].menu_button, MenuButtonCommands)


async def test_a_stranger_gets_no_menu_calls(dp, bot, org):
    await dp.feed_update(bot, updates.message(updates.tg_user(9104), "/start"))

    assert menus(bot) == []


async def test_a_language_change_keeps_the_button(dp, bot, linked):
    await sync_to_async(linked)("Manager", 9105, language="uz")

    await dp.feed_update(
        bot, updates.callback(updates.tg_user(9105), PickLanguage(code="ru").pack())
    )

    [menu] = menus(bot)
    assert isinstance(menu.menu_button, MenuButtonWebApp) and menu.chat_id == 9105


async def test_the_button_is_named_as_the_organization_named_the_app(dp, bot, linked, org):
    await sync_to_async(linked)("Manager", 9106)
    row = await sync_to_async(davomat_conf.get_settings)(org)
    row.product_name = "Namuna Davomat"
    await row.asave(update_fields=["product_name"])

    await dp.feed_update(bot, updates.message(updates.tg_user(9106), "/start"))

    assert menus(bot)[-1].menu_button.text == "Namuna Davomat"


async def test_help_tells_web_app_users_where_the_button_is(dp, bot, linked, settings):
    await sync_to_async(linked)("Manager", 9107)

    await dp.feed_update(bot, updates.message(updates.tg_user(9107), "/help"))
    assert "button next to the message field" in bot.sent()[-1].text

    settings.DASHBOARD_URL = ""
    await dp.feed_update(bot, updates.message(updates.tg_user(9107), "/help"))
    assert "button" not in bot.sent()[-1].text


async def test_today_opens_attendance_inside_telegram(dp, bot, linked, org):
    await sync_to_async(linked)("Manager", 9108)

    await dp.feed_update(bot, updates.message(updates.tg_user(9108), "/today"))

    [web] = bot.sent()[-1].reply_markup.inline_keyboard[-1]
    assert web.text == "Open in Davomat"
    assert web.web_app.url == f"{APP}c/{org.pk}/attendance"


# When the bot starts --------------------------------------------------------------------------


async def test_the_bot_start_gives_every_linked_web_app_user_the_button_once(bot, linked, org):
    owner = await sync_to_async(linked)("Owner", 9201)
    manager = await sync_to_async(linked)("Manager", 9202)
    await sync_to_async(linked)("Employee", 9203)
    await sync_to_async(linked)("Manager")  # not linked
    blocked = await sync_to_async(linked)("Manager", 9205)
    await User.objects.filter(pk=blocked.user_id).aupdate(owner_bot_blocked_at=timezone.now())

    assert await commands.sync_menu_buttons(bot, "3") == 2

    sent = menus(bot)
    assert [m.chat_id for m in sent] == [owner.user.telegram_id, manager.user.telegram_id]
    assert all(m.menu_button.web_app.url == f"{APP}c/{org.pk}" for m in sent)
    # A restart with the same token sends nothing again; a new token (another bot) does.
    assert await commands.sync_menu_buttons(bot, "3") == 0
    assert await commands.sync_menu_buttons(bot, "4") == 2


async def test_the_bot_start_sends_nothing_without_an_https_address(bot, linked, settings):
    await sync_to_async(linked)("Owner", 9211)
    settings.DASHBOARD_URL = "http://10.0.0.5/dashboard/"

    assert await commands.sync_menu_buttons(bot, "1") == 0
    assert menus(bot) == []


async def test_a_refused_chat_doesnt_stop_the_others(bot, linked):
    await sync_to_async(linked)("Owner", 9221)
    await sync_to_async(linked)("Manager", 9222)
    bot.session.refuse = True

    assert await commands.sync_menu_buttons(bot, "1") == 0
    assert len(menus(bot)) == 2


def test_the_menu_button_of_nobody_is_the_commands():
    assert isinstance(bot_messages.menu_button(None), MenuButtonCommands)
