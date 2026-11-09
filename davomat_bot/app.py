"""The bot process (`python -m davomat_bot` runs `run()`): wait for a token, check it with
Telegram, poll until the token changes (runtime.py), then return so the process exits with code 0
and Docker starts it again with the new token.

A token can change at any moment, also in the second or two before polling has started, when
aiogram can't stop it yet: the restart then waits until it can, and polling never starts at all
when the change came first.
"""

import asyncio
import logging
from collections.abc import Callable

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from asgiref.sync import sync_to_async

from apps.core.bot_runtime import DatabaseContext
from davomat_bot import edition, runtime
from davomat_bot.commands import set_commands
from davomat_bot.config import Settings, load_settings
from davomat_bot.dispatcher import create_bot, create_dispatcher

logger = logging.getLogger("davomat_bot")

CHANGED, STOPPED = "changed", "stopped"


async def _nothing() -> None:
    """A refused token changed: there is no polling to stop."""


async def run(
    settings: Settings | None = None,
    *,
    make_bot: Callable[[str], Bot] = create_bot,
    dispatcher: Dispatcher | None = None,
) -> str:
    """Returns CHANGED when the token changed (exit and come back with the new one) or STOPPED
    when polling ended otherwise (SIGTERM)."""
    settings = settings or load_settings()
    token = await runtime.wait_for_token(settings)
    version = await runtime.read_version()
    bot = make_bot(token)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        logger.error("Telegram refused the bot token: paste a new one in Settings › Telegram.")
        async with DatabaseContext():
            await sync_to_async(edition.mark_refused)()
        await bot.session.close()
        await runtime.watch_token(settings, token=token, version=version, on_change=_nothing)
        return CHANGED
    dp = dispatcher or create_dispatcher(settings)
    changed = asyncio.Event()

    async def restart() -> None:
        changed.set()
        while True:  # polling may be about to start: stop it as soon as aiogram can
            try:
                await dp.stop_polling()
                return
            except RuntimeError:
                await asyncio.sleep(0.1)

    logger.info("Davomat bot @%s starting in polling mode", me.username)
    watcher = asyncio.create_task(
        runtime.watch_token(settings, token=token, version=version, on_change=restart)
    )
    try:
        await bot.delete_webhook()
        await set_commands(bot)
        if not changed.is_set():
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        watcher.cancel()
        await bot.session.close()
    return CHANGED if changed.is_set() else STOPPED
