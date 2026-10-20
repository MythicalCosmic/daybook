"""`python -m ownerbot`: the owner bot in polling mode."""

import asyncio
import logging

from ownerbot.setup import setup_django

setup_django()

from ownerbot.commands import set_commands  # noqa: E402
from ownerbot.config import load_settings  # noqa: E402
from ownerbot.dispatcher import create_bot, create_dispatcher  # noqa: E402

logger = logging.getLogger("ownerbot")


async def main() -> None:
    settings = load_settings()
    if not settings.BOT_TOKEN:
        raise SystemExit("OWNER_BOT_TOKEN is not set")
    bot = create_bot(settings)
    dp = create_dispatcher(settings)
    logger.info("Owner bot starting in polling mode")
    await bot.delete_webhook()
    await set_commands(bot)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
