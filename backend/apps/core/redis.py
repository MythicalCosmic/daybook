"""Direct Redis access (AI turn streams, cancel flags), for what the Django cache can't do.

Counters, versions and budgets live in the Django cache instead, so they work on the in-memory
test cache. Every key goes through `key()`, which adds `settings.REDIS_KEY_PREFIX`, so parallel
test runs and package dev servers never share keys. Tests swap in fakeredis with `use_fake()`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import redis
import redis.asyncio
from django.conf import settings

if TYPE_CHECKING:
    import fakeredis

# Set by use_fake(): the in-memory server that every client below talks to instead.
_fake_server: fakeredis.FakeServer | None = None
_client: redis.Redis | None = None


def key(*parts: object) -> str:
    """`key("ai", "turn", 12)` -> `"<REDIS_KEY_PREFIX>ai:turn:12"`."""
    if not parts:
        raise ValueError("A Redis key needs at least one part.")
    return settings.REDIS_KEY_PREFIX + ":".join(str(part) for part in parts)


def get_redis() -> redis.Redis:
    """The process-wide synchronous client (string replies)."""
    global _client
    if _client is None:
        if _fake_server is not None:
            import fakeredis

            _client = fakeredis.FakeRedis(server=_fake_server, decode_responses=True)
        else:
            _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def get_async_redis() -> redis.asyncio.Redis:
    """A new asyncio client (string replies). Async clients are bound to the event loop that
    first uses them, so each caller makes its own and closes it with `await client.aclose()`."""
    if _fake_server is not None:
        import fakeredis

        return fakeredis.FakeAsyncRedis(server=_fake_server, decode_responses=True)
    return redis.asyncio.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def use_fake() -> fakeredis.FakeServer:
    """Point every client at a fresh in-memory server (tests only; needs fakeredis)."""
    import fakeredis

    global _fake_server
    reset()
    _fake_server = fakeredis.FakeServer()
    return _fake_server


def reset() -> None:
    """Forget the cached client and any fake server, so the next call connects afresh."""
    global _client, _fake_server
    if _client is not None:
        _client.close()
    _client = None
    _fake_server = None
