"""The bot process (`app.run`): it polls until the token changes, also when the change comes
before polling has started, and a token Telegram refuses shows in Settings and waits for a new
one. Each run returns, so the process exits with code 0 and Docker starts it with the new token."""

import asyncio

import pytest
from aiogram.methods import DeleteWebhook, GetUpdates, SetMyCommands
from asgiref.sync import sync_to_async
from django.db import connections

from apps.core.bot_runtime import close_database_threads
from davomat_bot import app, edition, runtime
from davomat_bot.config import Settings
from davomat_bot.tests.mocked_bot import MockedBot

TOKEN = "123456:ABC-davomat"


@pytest.fixture(autouse=True)
async def threads(dp):
    # The dispatcher outlives each test's event loop; aiogram makes its stop events once, bound
    # to the loop that first polled (the process has one loop, so only the tests need this).
    dp._stop_signal = dp._stopped_signal = None
    yield
    dp._stop_signal = dp._stopped_signal = None
    await asyncio.to_thread(close_database_threads)
    await sync_to_async(connections.close_all)()


@pytest.fixture
def quick(tmp_path) -> Settings:
    return Settings(
        FSM_REDIS_URL="",
        DASHBOARD_URL="",
        HEARTBEAT_PATH=str(tmp_path / "heartbeat"),
        TOKEN_WAIT_SECONDS=0.01,
        VERSION_CHECK_SECONDS=0.01,
        TOKEN_CHECK_SECONDS=0.03,
    )


@pytest.fixture
def stored(monkeypatch):
    """The stored token and its version, as apps.davomat would give them."""
    state = {"token": TOKEN, "version": "1"}
    monkeypatch.setattr(edition, "stored_token", lambda: state["token"])
    monkeypatch.setattr(edition, "token_version", lambda: state["version"])
    return state


def watch_then_change(after: float):
    """A token watch that reports a change `after` seconds in."""

    async def watch(settings, *, token, version, on_change):
        await asyncio.sleep(after)
        await on_change()
        return "version"

    return watch


async def test_it_polls_until_the_token_changes(dp, quick, stored, monkeypatch):
    monkeypatch.setattr(runtime, "watch_token", watch_then_change(0.2))
    bot = MockedBot()

    result = await asyncio.wait_for(app.run(quick, make_bot=lambda token: bot, dispatcher=dp), 5)

    assert result == app.CHANGED
    kinds = [type(request) for request in bot.requests]
    assert DeleteWebhook in kinds and SetMyCommands in kinds
    assert kinds.count(GetUpdates) >= 2  # it was polling


async def test_a_change_at_startup_stops_it_all_the_same(dp, quick, stored, monkeypatch):
    monkeypatch.setattr(runtime, "watch_token", watch_then_change(0))
    bot = MockedBot()

    result = await asyncio.wait_for(app.run(quick, make_bot=lambda token: bot, dispatcher=dp), 5)

    assert result == app.CHANGED


async def test_the_real_watch_sees_a_new_version(dp, quick, stored):
    bot = MockedBot()
    running = asyncio.create_task(app.run(quick, make_bot=lambda token: bot, dispatcher=dp))
    await asyncio.sleep(0.2)
    assert not running.done()

    stored["version"] = "2"

    assert await asyncio.wait_for(running, 5) == app.CHANGED


@pytest.mark.django_db(transaction=True)
async def test_a_refused_token_is_shown_and_waits_for_a_new_one(dp, quick, stored, org, settings):
    from apps.davomat import conf as davomat_conf
    from apps.davomat.models import DavomatSettings

    settings.EDITION = "davomat"
    row = await sync_to_async(davomat_conf.get_settings)(org)
    bot = MockedBot()
    bot.session.refuse = True
    running = asyncio.create_task(app.run(quick, make_bot=lambda token: bot, dispatcher=dp))
    await asyncio.sleep(0.2)
    assert not running.done()
    await row.arefresh_from_db()
    assert row.bot_status == DavomatSettings.BotStatus.INVALID

    stored["version"] = "2"  # a new token pasted

    assert await asyncio.wait_for(running, 5) == app.CHANGED
    assert [type(request) for request in bot.requests] == [type(bot.requests[0])]  # getMe only
