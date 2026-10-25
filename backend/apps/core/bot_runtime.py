"""How both bots run Django code: many people at once, each person's updates in order.

aiogram handles every update in a task of its own, but the handlers reach Django through
`sync_to_async`, and asgiref runs every such call of the whole process on ONE thread unless
told otherwise: with 300 people tapping at the same minute, each waited for everyone before
them. Two pieces fix that, and neither changes a handler:

- `DatabaseContext` (entered around each update by the bots' database middleware): inside it,
  asgiref's thread-sensitive calls run on a shared, bounded pool of threads (BOT_DB_THREADS),
  each call with a healthy connection, as Django gives each request (close_old_connections
  before and after). Each thread keeps its own connection, so the bots hold at most
  BOT_DB_THREADS connections each.
- `OrderedDispatcher`: one person's updates are handled one at a time, in the order Telegram
  sent them, so a quick second tap or message never overtakes the first; different people's
  run side by side.
"""

import asyncio
import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from weakref import WeakValueDictionary

from aiogram import Dispatcher
from aiogram.types import Update
from asgiref.sync import SyncToAsync, ThreadSensitiveContext
from django.conf import settings
from django.db import close_old_connections, connections


class DatabaseThreads(ThreadPoolExecutor):
    """Threads for the bots' Django calls; every call starts and ends like a request."""

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(_like_a_request, fn, *args, **kwargs)


def _like_a_request(fn, *args, **kwargs):
    close_old_connections()
    try:
        return fn(*args, **kwargs)
    finally:
        close_old_connections()


_lock = threading.Lock()
_threads: DatabaseThreads | None = None


def database_threads() -> DatabaseThreads:
    global _threads
    with _lock:
        if _threads is None:
            _threads = DatabaseThreads(
                max_workers=settings.BOT_DB_THREADS, thread_name_prefix="bot-db"
            )
        return _threads


def close_database_threads() -> None:
    """Close every thread's connection and stop the pool (tests; a new one starts on demand).
    Blocking: call it outside the event loop's thread."""
    global _threads
    with _lock:
        pool, _threads = _threads, None
    if pool is None:
        return
    # One closing job per thread: the barrier keeps each on a thread of its own.
    size = pool._max_workers
    barrier = threading.Barrier(size, timeout=10)

    def close() -> None:
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        connections.close_all()

    for future in [ThreadPoolExecutor.submit(pool, close) for _ in range(size)]:
        future.result()
    pool.shutdown(wait=True)


class DatabaseContext(ThreadSensitiveContext):
    """Inside it (in the outermost one), `sync_to_async` calls run on `database_threads()`."""

    async def __aenter__(self):
        await super().__aenter__()
        if self.token is not None:
            SyncToAsync.context_to_thread_executor[self] = database_threads()
        return self

    async def __aexit__(self, exc, value, tb):
        # The pool is shared: never let asgiref shut it down along with this context.
        SyncToAsync.context_to_thread_executor.pop(self, None)
        await super().__aexit__(exc, value, tb)


def person_of(update: Update) -> int | None:
    """Whose update it is: the Telegram user, else the chat (a channel post)."""
    try:
        event = update.event
    except Exception:  # an update type this aiogram doesn't know
        return None
    user = getattr(event, "from_user", None)
    if user is not None:
        return user.id
    chat = getattr(event, "chat", None)
    return chat.id if chat is not None else None


class OrderedDispatcher(Dispatcher):
    """A dispatcher that handles one person's updates one after another, in order."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A lock lives while some update of that person holds or awaits it.
        self._turns: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()

    async def feed_update(self, bot, update: Update, **kwargs):
        person = person_of(update)
        if person is None:
            return await super().feed_update(bot, update, **kwargs)
        turn = self._turns.get(person)
        if turn is None:
            turn = self._turns[person] = asyncio.Lock()
        async with turn:
            return await super().feed_update(bot, update, **kwargs)
