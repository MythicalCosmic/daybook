"""The bot's life around polling: waiting for a token, restarting when it changes, the
heartbeat the health check reads, and where the token and its version come from."""

import asyncio
import os
import time

import pytest

from apps.core import redis as core_redis
from apps.core.bot_runtime import close_database_threads
from davomat_bot import edition, health, runtime
from davomat_bot.config import Settings

TOKEN = "123456:ABC-davomat"


@pytest.fixture(autouse=True)
async def threads():
    yield
    await asyncio.to_thread(close_database_threads)


def quick(tmp_path, **overrides) -> Settings:
    values = {
        "FSM_REDIS_URL": "",
        "DASHBOARD_URL": "",
        "HEARTBEAT_PATH": str(tmp_path / "heartbeat"),
        "TOKEN_WAIT_SECONDS": 0.01,
        "VERSION_CHECK_SECONDS": 0.01,
        "TOKEN_CHECK_SECONDS": 0.03,
    }
    return Settings(**(values | overrides))


async def test_it_waits_for_a_token_and_stays_alive(monkeypatch, tmp_path):
    tokens = iter(["", "", TOKEN])
    monkeypatch.setattr(edition, "stored_token", lambda: next(tokens))
    settings = quick(tmp_path)

    assert await asyncio.wait_for(runtime.wait_for_token(settings), 2) == TOKEN
    assert health.is_alive(settings.HEARTBEAT_PATH)


async def test_a_new_version_stops_polling(monkeypatch, tmp_path, fake_redis):
    redis = core_redis.get_redis()
    key = core_redis.key(*edition.TOKEN_VERSION_KEY)
    redis.set(key, "3")
    monkeypatch.setattr(edition, "stored_token", lambda: TOKEN)
    stopped = []

    async def stop():
        stopped.append(True)

    watching = asyncio.create_task(
        runtime.watch_token(quick(tmp_path), token=TOKEN, version="3", on_change=stop)
    )
    await asyncio.sleep(0.1)
    assert not watching.done()

    redis.set(key, "4")

    assert await asyncio.wait_for(watching, 2) == "version"
    assert stopped == [True]


async def test_a_new_token_stops_polling_without_redis(monkeypatch, tmp_path, fake_redis):
    current = {"token": TOKEN}
    monkeypatch.setattr(edition, "stored_token", lambda: current["token"])

    async def stop():
        return None

    watching = asyncio.create_task(
        runtime.watch_token(quick(tmp_path), token=TOKEN, version=None, on_change=stop)
    )
    await asyncio.sleep(0.1)
    assert not watching.done()

    current["token"] = "999:NEW"

    assert await asyncio.wait_for(watching, 2) == "token"


def test_the_version_is_read_with_the_key_prefix(fake_redis, settings):
    settings.REDIS_KEY_PREFIX = "t:f:"
    assert edition.token_version() is None

    core_redis.get_redis().set("t:f:davomat:bot_token_version", 7)

    assert edition.token_version() == "7"


def test_redis_down_means_no_version(monkeypatch):
    def down():
        raise ConnectionError("no Redis")

    monkeypatch.setattr(core_redis, "get_redis", down)

    assert edition.token_version() is None


@pytest.mark.django_db
def test_the_setting_is_the_fallback_token(settings):
    settings.OWNER_BOT_TOKEN = "55:FALLBACK"

    assert edition.stored_token() == "55:FALLBACK"


def test_the_health_check_reads_the_heartbeat(tmp_path):
    path = str(tmp_path / "beat")
    assert not health.is_alive(path)

    health.beat(path)
    assert health.is_alive(path)

    stale = time.time() - health.STALE_AFTER_SECONDS - 5
    os.utime(path, (stale, stale))
    assert not health.is_alive(path)
