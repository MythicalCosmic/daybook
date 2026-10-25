#!/usr/bin/env python3
"""A burst of updates through the real employee bot dispatcher, without Telegram.

N load test people (manage.py loadtest_people) each send the bot /tasks at the same moment;
the real dispatcher, middlewares and handlers run against the database in the environment,
and every Bot API call is answered by a stand-in after --latency ms (Telegram's own round
trip). It prints how long each update took and how long the whole burst took.

    uv run python scripts/loadtest/bot_burst.py --people 300            # as the bot runs now
    uv run python scripts/loadtest/bot_burst.py --people 300 --one-thread
        # as before apps.core.bot_runtime: every Django call on asgiref's single thread

Use a development or package database (deploy/dev-packages.mk), never production: nothing is
sent anywhere (TELEGRAM_DRY_RUN is forced on), but the handlers do write to the database.
"""

import argparse
import asyncio
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "employee_bot"), str(ROOT / "backend")]
os.environ["TELEGRAM_DRY_RUN"] = "true"
os.environ["BOT_FSM_REDIS_URL"] = ""
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

from core.django_setup import setup_django  # noqa: E402

setup_django()

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.methods import GetMe, SendMessage, SendPhoto  # noqa: E402
from aiogram.types import Chat, Message, Update  # noqa: E402
from aiogram.types import User as TgUser  # noqa: E402

FIRST_ID = 990_000_000_001


class TelegramStandIn(BaseSession):
    """Answers every Bot API call after `latency` seconds, as Telegram would."""

    def __init__(self, latency: float):
        super().__init__()
        self.latency = latency
        self.calls = 0

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
        self.calls += 1
        await asyncio.sleep(self.latency)
        if isinstance(method, SendMessage | SendPhoto):
            return Message(
                message_id=self.calls,
                date=datetime.now(),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=getattr(method, "text", None) or "",
            )
        if isinstance(method, GetMe):
            return TgUser(id=42, is_bot=True, first_name="Daybook", username="daybook_bot")
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""


def update_from(telegram_id: int, number: int, text: str) -> Update:
    return Update(
        update_id=number,
        message=Message(
            message_id=number,
            date=datetime.now(),
            chat=Chat(id=telegram_id, type="private"),
            from_user=TgUser(id=telegram_id, is_bot=False, first_name="Test", language_code="uz"),
            text=text,
        ),
    )


def dispatcher(one_thread: bool) -> Dispatcher:
    import main  # employee_bot/main.py
    from bot.middlewares import database

    if one_thread:
        # As before: no per-update context, so asgiref runs every call on its one thread.
        class NoContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

        database.DatabaseContext = NoContext
        main.OrderedDispatcher = Dispatcher
    return main.create_dispatcher()


async def burst(args) -> dict:
    dp = dispatcher(args.one_thread)
    session = TelegramStandIn(args.latency / 1000)
    bot = Bot(
        "42:LOADTEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    people = [args.first_id + n for n in range(args.people)]
    # Warm up: imports, translations, one connection.
    await dp.feed_update(bot, update_from(people[0], 1, args.text))
    took: list[float] = []

    async def one(number: int, telegram_id: int) -> None:
        started = time.perf_counter()
        await dp.feed_update(bot, update_from(telegram_id, number, args.text))
        took.append(time.perf_counter() - started)

    calls_before = session.calls
    started = time.perf_counter()
    await asyncio.gather(*(one(10 + n, person) for n, person in enumerate(people)))
    elapsed = time.perf_counter() - started
    took.sort()
    return {
        "mode": "one thread (before)" if args.one_thread else "thread pool (after)",
        "updates": len(took),
        "bot_api_calls": session.calls - calls_before,
        "elapsed_s": round(elapsed, 2),
        "updates_per_s": round(len(took) / elapsed, 1),
        "p50_ms": round(took[len(took) // 2] * 1000),
        "p95_ms": round(took[int(len(took) * 0.95) - 1] * 1000),
        "p99_ms": round(took[int(len(took) * 0.99) - 1] * 1000),
        "mean_ms": round(statistics.fmean(took) * 1000),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--people", type=int, default=300)
    parser.add_argument("--first-id", type=int, default=FIRST_ID)
    parser.add_argument("--text", default="/tasks", help="what everyone sends")
    parser.add_argument("--latency", type=float, default=40.0, help="Bot API round trip, ms")
    parser.add_argument("--one-thread", action="store_true", help="the old behaviour")
    args = parser.parse_args()
    result = asyncio.run(burst(args))
    print(" ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
