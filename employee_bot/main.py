import asyncio
import logging

from core.django_setup import setup_django

setup_django()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.handlers import register_all_handlers
from bot.middlewares import register_all_middlewares
from core.config import settings

logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    return Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_storage() -> BaseStorage:
    if settings.FSM_REDIS_URL:
        return RedisStorage.from_url(settings.FSM_REDIS_URL)
    return MemoryStorage()


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=create_storage())
    register_all_middlewares(dp)
    register_all_handlers(dp)
    return dp


async def main() -> None:
    if not settings.BOT_TOKEN:
        raise SystemExit("EMPLOYEE_BOT_TOKEN is not set")

    bot = create_bot()
    dp = create_dispatcher()

    logger.info("Employee bot starting in polling mode")
    await bot.delete_webhook()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
