"""The bots' runtime (apps.core.bot_runtime): different people's Django calls run at the same
time on a bounded pool, one person's updates stay in order."""

import asyncio
import threading
from datetime import datetime

import pytest
from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser
from asgiref.sync import sync_to_async

from apps.core import bot_runtime
from apps.core.bot_runtime import DatabaseContext, OrderedDispatcher, person_of


class Database(BaseMiddleware):
    """What both bots' DjangoConnectionMiddleware does around every update."""

    async def __call__(self, handler, event, data):
        async with DatabaseContext():
            return await handler(event, data)


def update(number: int, person: int) -> Update:
    return Update(
        update_id=number,
        message=Message(
            message_id=number,
            date=datetime.now(),
            chat=Chat(id=person, type="private"),
            from_user=TgUser(id=person, is_bot=False, first_name="Test"),
            text="hi",
        ),
    )


def dispatcher(handler, *, ordered=True, database=True) -> Dispatcher:
    dp = OrderedDispatcher() if ordered else Dispatcher()
    if database:
        dp.update.outer_middleware(Database())
    router = Router()
    router.message()(handler)
    dp.include_router(router)
    return dp


@pytest.fixture
def bot():
    return Bot("42:TEST")


@pytest.fixture(autouse=True)
def fresh_pool(settings):
    settings.BOT_DB_THREADS = 4
    bot_runtime.close_database_threads()
    yield
    bot_runtime.close_database_threads()


async def test_different_people_reach_the_database_at_the_same_time(bot):
    """Each handler waits in a Django call until the other one is in its own: only possible
    when the two calls run at once (asgiref alone runs them one after the other)."""
    both_inside = threading.Barrier(2, timeout=5)

    async def handler(message: Message):
        await sync_to_async(both_inside.wait)()

    dp = dispatcher(handler)

    await asyncio.gather(dp.feed_update(bot, update(1, 7)), dp.feed_update(bot, update(2, 8)))

    assert not both_inside.broken


async def test_without_the_context_the_calls_queue_on_one_thread(bot):
    """The old behaviour, for contrast: the second call can't start while the first waits."""
    both_inside = threading.Barrier(2, timeout=0.5)

    async def handler(message: Message):
        await sync_to_async(both_inside.wait)()

    dp = dispatcher(handler, database=False)

    with pytest.raises(threading.BrokenBarrierError):
        await asyncio.gather(dp.feed_update(bot, update(1, 7)), dp.feed_update(bot, update(2, 8)))


async def test_the_pool_is_bounded(bot, settings):
    settings.BOT_DB_THREADS = 3
    bot_runtime.close_database_threads()
    inside = 0
    most = 0
    lock = threading.Lock()

    def work():
        nonlocal inside, most
        with lock:
            inside += 1
            most = max(most, inside)
        threading.Event().wait(0.05)
        with lock:
            inside -= 1

    async def handler(message: Message):
        await sync_to_async(work)()

    dp = dispatcher(handler)

    await asyncio.gather(*(dp.feed_update(bot, update(n, 100 + n)) for n in range(12)))

    assert most == 3


async def test_one_persons_updates_run_one_after_another_in_order(bot):
    events = []

    async def handler(message: Message):
        events.append(("start", message.message_id))
        await asyncio.sleep(0.05 if message.message_id == 1 else 0)
        events.append(("end", message.message_id))

    dp = dispatcher(handler)

    await asyncio.gather(
        dp.feed_update(bot, update(1, 7)),
        dp.feed_update(bot, update(2, 7)),
        dp.feed_update(bot, update(3, 8)),
    )

    # Person 7's second message waits for the first; person 8 doesn't wait for anyone.
    assert events.index(("end", 1)) < events.index(("start", 2))
    assert events.index(("start", 3)) < events.index(("end", 1))
    assert not dp._turns  # nothing kept once everyone is done


def test_every_call_on_the_pool_starts_and_ends_like_a_request(monkeypatch):
    seen = []
    monkeypatch.setattr(
        bot_runtime,
        "close_old_connections",
        lambda: seen.append(("cleanup", threading.get_ident())),
    )

    def job():
        seen.append(("job", threading.get_ident()))
        return 42

    assert bot_runtime.database_threads().submit(job).result() == 42
    assert [step for step, _thread in seen] == ["cleanup", "job", "cleanup"]
    assert len({thread for _step, thread in seen}) == 1  # all on the job's own thread


def test_whose_update_it_is():
    assert person_of(update(1, 7)) == 7
    assert person_of(Update(update_id=2)) is None
