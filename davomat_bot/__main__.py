"""`python -m davomat_bot` (from the repository root): the bot in polling mode.

Exits with code 0 when the token changes (see runtime.py); Docker starts it again.
"""

import asyncio
import logging

from davomat_bot.setup import setup_django

setup_django()

from aiogram.exceptions import TelegramUnauthorizedError  # noqa: E402

from davomat_bot import runtime  # noqa: E402
from davomat_bot.commands import set_commands  # noqa: E402
from davomat_bot.config import load_settings  # noqa: E402
from davomat_bot.dispatcher import create_bot, create_dispatcher  # noqa: E402

logger = logging.getLogger("davomat_bot")


async def _exit() -> None:
    """A refused token changed: nothing to stop, main() simply returns."""


async def main() -> None:
    settings = load_settings()
    token = await runtime.wait_for_token(settings)
    version = await runtime.read_version()
    bot = create_bot(token)
    dp = create_dispatcher(settings)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        logger.error("Telegram refused the bot token: paste a new one in Settings › Telegram.")
        await bot.session.close()
        await runtime.watch_token(settings, token=token, version=version, on_change=_exit)
        return
    logger.info("Davomat bot @%s starting in polling mode", me.username)
    watcher = asyncio.create_task(
        runtime.watch_token(settings, token=token, version=version, on_change=dp.stop_polling)
    )
    try:
        await bot.delete_webhook()
        await set_commands(bot)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        watcher.cancel()


if __name__ == "__main__":
    asyncio.run(main())  # logging: the backend's LOGGING (root at LOG_LEVEL, INFO by default)
