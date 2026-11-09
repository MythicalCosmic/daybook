"""`/start` for strangers and linked people, `/start link_<code>`, `/help`, anything else, and
block notices."""

from datetime import timedelta

import pytest
from aiogram.methods import SetMyCommands
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from apps.davomat import conf as davomat_conf
from apps.davomat import services as davomat_services
from apps.davomat.models import TelegramLink
from apps.notifications.emoji import has_emoji
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def link_for(org):
    """`link_for(membership)`: a fresh one-time link code (apps.davomat), as an admin makes
    it in the web app (the organization's bot connected)."""
    row = davomat_conf.get_settings(org)
    row.bot_username = "davomat_test_bot"
    row.save(update_fields=["bot_username"])

    def make(membership) -> str:
        return davomat_services.make_link(membership, by=None).code

    return make


def buttons(message) -> list[list[str]]:
    return [[button.text for button in row] for row in message.reply_markup.inline_keyboard]


async def test_a_stranger_learns_how_to_link_and_leaves_no_trace(dp, bot, org):
    await dp.feed_update(bot, updates.message(updates.tg_user(9001, "Aziz"), "/start"))

    [reply] = bot.sent()
    assert "Hello, Aziz!" in reply.text
    assert "attendance bot of <b>Namuna MChJ</b>" in reply.text
    assert "ask your administrator" in reply.text
    assert buttons(reply) == [[LANGUAGE_BUTTON]]
    assert not has_emoji(reply.text)
    assert not await User.objects.filter(telegram_id=9001).aexists()


async def test_a_link_code_links_this_telegram(dp, bot, linked, link_for):
    aziz = await sync_to_async(linked)(first_name="Aziz", last_name="Rahimov")
    code = await sync_to_async(link_for)(aziz)

    await dp.feed_update(bot, updates.message(updates.tg_user(9002, "Aziz"), f"/start link_{code}"))

    [reply] = bot.sent()
    assert "linked to <b>Aziz Rahimov</b> at Namuna MChJ" in reply.text
    assert "/me" in reply.text and "/today" not in reply.text  # an employee: no board
    user = await User.objects.aget(pk=aziz.user_id)
    assert user.telegram_id == 9002
    assert user.owner_bot_started_at is not None and user.owner_bot_blocked_at is None
    # The chat's own menu: /me, no /today.
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert [c.command for c in menu.commands] == ["me", "language", "help", "start"]

    # The same account opening the same link again is fine; anyone else is told it's used.
    await dp.feed_update(bot, updates.message(updates.tg_user(9002, "Aziz"), f"/start link_{code}"))
    assert "linked to <b>Aziz Rahimov</b>" in bot.sent()[-1].text
    await dp.feed_update(bot, updates.message(updates.tg_user(9020), f"/start link_{code}"))
    assert bot.sent()[-1].text == "This link was used already. Ask for a new one."
    assert not await User.objects.filter(telegram_id=9020).aexists()


async def test_a_manager_who_links_gets_the_board_too(dp, bot, linked, link_for):
    boss = await sync_to_async(linked)("Manager", first_name="Bekzod")
    code = await sync_to_async(link_for)(boss)

    await dp.feed_update(
        bot, updates.message(updates.tg_user(9003, "Bekzod"), f"/start link_{code}")
    )

    assert "/today" in bot.sent()[0].text
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert "today" in [c.command for c in menu.commands]


async def test_an_unknown_or_expired_link_says_so(dp, bot, linked, link_for):
    aziz = await sync_to_async(linked)(first_name="Aziz")
    code = await sync_to_async(link_for)(aziz)
    await TelegramLink.objects.filter(membership=aziz).aupdate(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    await dp.feed_update(bot, updates.message(updates.tg_user(9004), "/start link_nonsense"))
    await dp.feed_update(bot, updates.message(updates.tg_user(9004), f"/start link_{code}"))

    unknown, expired = bot.sent()
    assert unknown.text == "This link doesn't work. Ask for a new one."
    assert expired.text == "This link has expired. Ask for a new one."
    assert not await User.objects.filter(telegram_id=9004).aexists()


async def test_a_linked_person_is_greeted_with_their_commands(dp, bot, linked):
    await sync_to_async(linked)("Manager", 9006, first_name="Bekzod")

    await dp.feed_update(bot, updates.message(updates.tg_user(9006), "/start"))

    [reply] = bot.sent()
    assert "Hello, Bekzod!" in reply.text
    assert "You are linked to <b>Namuna MChJ</b>." in reply.text
    assert "/today" in reply.text and "/me" in reply.text
    assert (await User.objects.aget(telegram_id=9006)).owner_bot_started_at is not None


async def test_the_web_app_button_needs_https_and_dashboard_access(dp, bot, linked, settings):
    await sync_to_async(linked)("Manager", 9007)
    await sync_to_async(linked)("Employee", 9008)

    await dp.feed_update(bot, updates.message(updates.tg_user(9007), "/start"))
    assert buttons(bot.sent()[-1]) == [[LANGUAGE_BUTTON]]  # http: no button

    settings.DASHBOARD_URL = "https://davomat.example.uz/dashboard/"
    await dp.feed_update(bot, updates.message(updates.tg_user(9007), "/start"))
    [[web], [language]] = bot.sent()[-1].reply_markup.inline_keyboard
    assert web.url.startswith("https://davomat.example.uz/dashboard/c/")
    assert language.text == LANGUAGE_BUTTON

    await dp.feed_update(bot, updates.message(updates.tg_user(9008), "/start"))
    assert buttons(bot.sent()[-1]) == [[LANGUAGE_BUTTON]]  # an employee: no web app


async def test_help_and_anything_else(dp, bot, linked):
    await sync_to_async(linked)("Employee", 9009)

    await dp.feed_update(bot, updates.message(updates.tg_user(9010), "/help"))
    assert "isn't linked to anyone yet" in bot.sent()[-1].text

    await dp.feed_update(bot, updates.message(updates.tg_user(9009), "/help"))
    assert "/me" in bot.sent()[-1].text

    await dp.feed_update(bot, updates.message(updates.tg_user(9009), "salom"))
    assert "You are linked to" in bot.sent()[-1].text


async def test_before_setup_the_bot_says_so(dp, bot, db):
    await dp.feed_update(bot, updates.message(updates.tg_user(9011), "/start"))

    # In Uzbek, the edition's language until an organization picks its own.
    assert "hali sozlanmagan" in bot.sent()[0].text


async def test_blocking_and_unblocking_is_recorded(dp, bot, linked):
    await sync_to_async(linked)("Employee", 9012)
    person = updates.tg_user(9012)

    await dp.feed_update(bot, updates.blocked(person))
    assert (await User.objects.aget(telegram_id=9012)).owner_bot_blocked_at is not None

    await dp.feed_update(bot, updates.unblocked(person))
    user = await User.objects.aget(telegram_id=9012)
    assert user.owner_bot_blocked_at is None and user.owner_bot_started_at is not None


async def test_a_button_nobody_knows_still_gets_an_answer(dp, bot, linked):
    await sync_to_async(linked)("Employee", 9013)

    await dp.feed_update(bot, updates.callback(updates.tg_user(9013), "task:open:12"))

    [answer] = bot.answers()
    assert answer.text == "This message is too old. Open it again from the menu."
