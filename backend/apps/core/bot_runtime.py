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

And on each bot's session: `WaitOnFloodLimit` (past Telegram's rate for one bot, a reply waits
the seconds Telegram asks for and goes, instead of being dropped) and `FitTelegramLimits` (a
text past Telegram's length is cut to fit, instead of refused). Both bots register `on_error`
for a handler that fails.
"""

import asyncio
import contextlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

from aiogram import Dispatcher
from aiogram.client.default import Default
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.methods import (
    EditMessageCaption,
    EditMessageText,
    SendDocument,
    SendMessage,
    SendPhoto,
    SendVideo,
)
from aiogram.types import ErrorEvent, Update
from asgiref.sync import SyncToAsync, ThreadSensitiveContext
from django.conf import settings
from django.db import close_old_connections, connections
from django.utils import translation
from django.utils.translation import gettext as _

from apps.notifications.html_limits import CAPTION_LIMIT, ELLIPSIS, TEXT_LIMIT, fit

if TYPE_CHECKING:
    from apps.accounts.models import User

logger = logging.getLogger(__name__)


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

    for future in [ThreadPoolExecutor.submit(pool, close) for _each in range(size)]:
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


class WaitOnFloodLimit(BaseRequestMiddleware):
    """Telegram's flood limit ("Too Many Requests: retry after N"): wait the N seconds it asks
    for and send again, a few times, instead of dropping the reply. Hundreds of people tapping
    in the same minute can pass Telegram's rate for one bot; their replies then come a little
    later, not never. Only this person's next update waits meanwhile (`OrderedDispatcher`).
    A wait longer than `ceiling` seconds gives up at once, as before (the error is logged)."""

    def __init__(self, attempts: int = 3, ceiling: float = 20, sleep=asyncio.sleep) -> None:
        self.attempts = attempts
        self.ceiling = ceiling
        self.sleep = sleep

    async def __call__(self, make_request, bot, method):
        attempt = 1
        while True:
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as exc:
                if attempt >= self.attempts or exc.retry_after > self.ceiling:
                    raise
                attempt += 1
                await self.sleep(exc.retry_after)


CAPTIONED = (SendPhoto, SendDocument, SendVideo, EditMessageCaption)


class FitTelegramLimits(BaseRequestMiddleware):
    """Telegram refuses a message over 4096 characters and a caption over 1024 (a long list,
    a long description on a photo card): such a text is cut to fit, at a line end and with its
    HTML tags closed (`html_limits.fit`), and goes. Texts that fit are left alone."""

    async def __call__(self, make_request, bot, method):
        if isinstance(method, SendMessage | EditMessageText):
            method.text = _fit(method.text, TEXT_LIMIT, method.parse_mode)
        elif isinstance(method, CAPTIONED) and method.caption:
            method.caption = _fit(method.caption, CAPTION_LIMIT, method.parse_mode)
        return await make_request(bot, method)


def _fit(text: str, limit: int, parse_mode) -> str:
    # Both bots default to HTML; a method sent with parse_mode=None is plain text.
    if isinstance(parse_mode, Default) or (parse_mode or "").upper() == "HTML":
        return fit(text, limit)
    return text if len(text) <= limit else text[: limit - len(ELLIPSIS)] + ELLIPSIS


async def on_error(event: ErrorEvent, user: User | None = None) -> bool:
    """When a handler fails, in either bot (research R1 F1): every button tap still gets an
    answer, so no spinner runs forever, and every private message a reply. The failure is
    logged with its traceback."""
    logger.error("Update %s failed", event.update.update_id, exc_info=event.exception)
    with translation.override(user.language if user is not None else "uz"):
        text = _("Something went wrong. Please try again in a moment.")
    update = event.update
    with contextlib.suppress(TelegramAPIError):
        if update.callback_query is not None:
            await update.callback_query.answer(text)
        elif update.message is not None and update.message.chat.type == ChatType.PRIVATE:
            await update.message.answer(text)
    return True
