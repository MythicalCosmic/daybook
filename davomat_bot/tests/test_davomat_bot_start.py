"""`/start` for strangers and linked people, `/start link_<code>`, `/help`, anything else, and
block notices."""

import pytest
from aiogram.methods import SetMyCommands
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.notifications.emoji import has_emoji
from davomat_bot import edition
from davomat_bot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


class Codes(dict[str, Membership]):
    """Valid link codes, and every claim the bot made."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple] = []


@pytest.fixture
def codes(monkeypatch):
    """apps.davomat's `claim_link`, faked: `codes["abc"] = membership` makes a valid code."""
    valid = Codes()

    def claim(code, *, telegram_id, username, first_name):
        valid.calls.append((code, telegram_id, username, first_name))
        membership = valid.pop(code, None)
        if membership is None:
            raise DomainError("This link has expired. Ask for a new one.")
        User.objects.filter(pk=membership.user_id).update(telegram_id=telegram_id)
        return membership

    monkeypatch.setattr(edition, "claim_link", claim)
    return valid


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


async def test_a_link_code_links_this_telegram(dp, bot, linked, codes):
    aziz = await sync_to_async(linked)(first_name="Aziz", last_name="Rahimov")
    codes["k7Qm2x"] = aziz

    await dp.feed_update(bot, updates.message(updates.tg_user(9002, "Aziz"), "/start link_k7Qm2x"))

    assert codes.calls == [("k7Qm2x", 9002, "user9002", "Aziz")]
    [reply] = bot.sent()
    assert "linked to <b>Aziz Rahimov</b> at Namuna MChJ" in reply.text
    assert "/me" in reply.text and "/today" not in reply.text  # an employee: no board
    user = await User.objects.aget(pk=aziz.user_id)
    assert user.telegram_id == 9002
    assert user.owner_bot_started_at is not None and user.owner_bot_blocked_at is None
    # The chat's own menu: /me, no /today.
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert [c.command for c in menu.commands] == ["me", "language", "help", "start"]


async def test_a_manager_who_links_gets_the_board_too(dp, bot, linked, codes):
    boss = await sync_to_async(linked)("Manager", first_name="Bekzod")
    codes["boss1"] = boss

    await dp.feed_update(bot, updates.message(updates.tg_user(9003, "Bekzod"), "/start link_boss1"))

    assert "/today" in bot.sent()[0].text
    [menu] = [r for r in bot.requests if isinstance(r, SetMyCommands)]
    assert "today" in [c.command for c in menu.commands]


async def test_a_used_or_expired_link_says_so(dp, bot, org, codes):
    await dp.feed_update(bot, updates.message(updates.tg_user(9004), "/start link_old"))

    [reply] = bot.sent()
    assert reply.text == "This link has expired. Ask for a new one."
    assert not await User.objects.filter(telegram_id=9004).aexists()


async def test_without_the_edition_core_a_link_fails_politely(dp, bot, org, monkeypatch):
    def missing(*args, **kwargs):
        raise ImportError("apps.davomat")

    monkeypatch.setattr(edition, "claim_link", missing)

    await dp.feed_update(bot, updates.message(updates.tg_user(9005), "/start link_abc"))

    assert "doesn't work any more" in bot.sent()[0].text


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

    assert "isn't set up yet" in bot.sent()[0].text


async def test_blocking_and_unblocking_is_recorded(dp, bot, linked):
    await sync_to_async(linked)("Employee", 9012)
    person = updates.tg_user(9012)

    await dp.feed_update(bot, updates.blocked(person))
    assert (await User.objects.aget(telegram_id=9012)).owner_bot_blocked_at is not None

    await dp.feed_update(bot, updates.unblocked(person))
    user = await User.objects.aget(telegram_id=9012)
    assert user.owner_bot_blocked_at is None and user.owner_bot_started_at is not None
