import fakeredis
import pytest
import redis

from apps.core import redis as core_redis


@pytest.fixture
def fake():
    server = core_redis.use_fake()
    yield server
    core_redis.reset()


def test_keys_carry_the_run_prefix(settings):
    settings.REDIS_KEY_PREFIX = "t:pkg:"

    assert core_redis.key("ai", "turn", 12) == "t:pkg:ai:turn:12"
    assert core_redis.key("pulse") == "t:pkg:pulse"


def test_a_key_needs_a_part():
    with pytest.raises(ValueError):
        core_redis.key()


def test_test_settings_prefix_keys_per_run(settings):
    # PYTEST_DB=<name> gives every run its own prefix, for the cache and for Redis alike.
    assert settings.REDIS_KEY_PREFIX.startswith("t:")
    cache_prefix = settings.CACHES["default"]["KEY_PREFIX"]
    assert cache_prefix == settings.REDIS_KEY_PREFIX


def test_the_real_client_is_built_from_settings(settings):
    settings.REDIS_URL = "redis://localhost:6390/3"
    core_redis.reset()
    try:
        client = core_redis.get_redis()
        assert isinstance(client, redis.Redis)
        assert client.connection_pool.connection_kwargs["db"] == 3
        assert core_redis.get_redis() is client  # one per process
    finally:
        core_redis.reset()


def test_use_fake_swaps_every_client(fake):
    client = core_redis.get_redis()
    client.set(core_redis.key("hello"), "world")

    assert isinstance(client, fakeredis.FakeRedis)
    assert client.get(core_redis.key("hello")) == "world"  # replies are strings


async def test_async_clients_share_the_fake_server(fake):
    core_redis.get_redis().xadd(core_redis.key("stream"), {"kind": "step"})
    client = core_redis.get_async_redis()
    try:
        entries = await client.xrange(core_redis.key("stream"))
    finally:
        await client.aclose()

    assert [fields for _, fields in entries] == [{"kind": "step"}]


def test_reset_forgets_the_fake(fake):
    core_redis.get_redis().set("left-over", "1")
    core_redis.use_fake()

    assert core_redis.get_redis().get("left-over") is None
