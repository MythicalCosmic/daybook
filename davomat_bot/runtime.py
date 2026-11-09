"""The bot's life around polling: wait for a token, then restart when it changes.

The token lives in the database and an admin can paste a new one at any time. aiogram can't
swap a running bot's token, so the bot exits (code 0) when the token changes and Docker starts
it again (`restart: unless-stopped`) with the new one:

- no token yet: log it and look again every `TOKEN_WAIT_SECONDS`;
- running: every `VERSION_CHECK_SECONDS`, the version apps.davomat writes to Redis; every
  `TOKEN_CHECK_SECONDS`, the stored token itself (Redis may be flushed or down);
- a token Telegram refuses: no polling, the same watch until it changes.

The heartbeat file is touched at every look, so the health check sees a live process.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from asgiref.sync import sync_to_async

from apps.core.bot_runtime import DatabaseContext
from davomat_bot import edition, health
from davomat_bot.config import Settings

logger = logging.getLogger("davomat_bot")


async def read_token() -> str:
    # Like an update's Django calls: on the bots' threads, each with a healthy connection.
    async with DatabaseContext():
        return await sync_to_async(edition.stored_token)()


async def read_version() -> str | None:
    async with DatabaseContext():
        return await sync_to_async(edition.token_version)()


async def wait_for_token(settings: Settings) -> str:
    """The stored token, once there is one."""
    warned = False
    while True:
        health.beat(settings.HEARTBEAT_PATH)
        token = await read_token()
        if token:
            return token
        if not warned:
            logger.warning(
                "No Telegram bot token yet: paste one in Settings › Telegram. "
                "Looking again every %s s.",
                int(settings.TOKEN_WAIT_SECONDS),
            )
            warned = True
        await asyncio.sleep(settings.TOKEN_WAIT_SECONDS)


async def watch_token(
    settings: Settings,
    *,
    token: str,
    version: str | None,
    on_change: Callable[[], Awaitable[object]],
) -> str:
    """Returns (after awaiting `on_change`) once the token or its version differs from the
    ones the bot started with: "version" or "token", whichever noticed it."""
    every = max(1, round(settings.TOKEN_CHECK_SECONDS / settings.VERSION_CHECK_SECONDS))
    tick = 0
    while True:
        await asyncio.sleep(settings.VERSION_CHECK_SECONDS)
        health.beat(settings.HEARTBEAT_PATH)
        tick += 1
        reason = None
        now = await read_version()
        if now is not None and now != version:
            reason = "version"
        elif tick % every == 0 and await read_token() != token:
            reason = "token"
        if reason:
            logger.info("The bot token changed (%s): restarting with the new one", reason)
            await on_change()
            return reason
