"""Starting the owner bot routes owner notifications to it; blocking it routes them back."""

import pytest
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.telegram_chat import LANGUAGE_BUTTON
from ownerbot.tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def user_of(telegram_id: int) -> User:
    return User.objects.get(telegram_id=telegram_id)


async def test_start_records_that_the_owner_bot_was_started(dp, bot):
    person = updates.tg_user(7001)

    await dp.feed_update(bot, updates.message(person, "/start"))

    user = await user_of(7001)
    assert user.owner_bot_started_at is not None
    assert user.owner_bot_blocked_at is None
    [reply] = bot.sent()
    assert "/new" in reply.text  # nobody has a company yet: the bot offers to create one
    # No https dashboard address in tests: only the language button.
    assert [[b.text for b in row] for row in reply.reply_markup.inline_keyboard] == [
        [LANGUAGE_BUTTON]
    ]


async def test_start_offers_the_dashboard_when_it_has_an_https_address(dp, bot, settings):
    settings.DASHBOARD_URL = "https://app.example.uz/dashboard/"

    await dp.feed_update(bot, updates.message(updates.tg_user(7002), "/start"))

    [reply] = bot.sent()
    [[button], [language]] = reply.reply_markup.inline_keyboard
    assert button.web_app.url == "https://app.example.uz/dashboard/"
    assert language.text == LANGUAGE_BUTTON


async def test_someone_new_starts_in_uzbek_whatever_telegram_says(dp, bot):
    await dp.feed_update(bot, updates.message(updates.tg_user(7003, language_code="ru"), "/start"))

    assert (await user_of(7003)).language == "uz"


async def test_blocking_and_unblocking_the_bot_is_recorded(dp, bot):
    person = updates.tg_user(7004)
    await dp.feed_update(bot, updates.message(person, "/start"))
    started = (await user_of(7004)).owner_bot_started_at

    await dp.feed_update(bot, updates.blocked(person))
    assert (await user_of(7004)).owner_bot_blocked_at is not None

    await dp.feed_update(bot, updates.unblocked(person))
    user = await user_of(7004)
    assert user.owner_bot_blocked_at is None
    assert user.owner_bot_started_at == started


async def test_any_message_after_a_block_counts_as_unblocked(dp, bot):
    person = updates.tg_user(7005)
    await dp.feed_update(bot, updates.blocked(person))
    assert (await user_of(7005)).owner_bot_started_at is None  # a block notice isn't a start

    await dp.feed_update(bot, updates.message(person, "hello"))

    user = await user_of(7005)
    assert user.owner_bot_started_at is not None and user.owner_bot_blocked_at is None
