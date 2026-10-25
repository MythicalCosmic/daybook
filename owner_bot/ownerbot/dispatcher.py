"""Builds the owner bot and its dispatcher (used by `__main__` and by the tests)."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from apps.core.bot_runtime import OrderedDispatcher
from ownerbot.config import Settings, load_settings
from ownerbot.handlers import register_all_handlers
from ownerbot.middlewares import register_all_middlewares


def create_bot(settings: Settings | None = None) -> Bot:
    settings = settings or load_settings()
    # No link previews: a URL in a notification would push its buttons down (research R1 F2).
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_storage(settings: Settings | None = None) -> BaseStorage:
    settings = settings or load_settings()
    if settings.FSM_REDIS_URL:
        # Its own key prefix: both bots may share one Redis, and a person talks to both.
        return RedisStorage.from_url(
            settings.FSM_REDIS_URL,
            key_builder=DefaultKeyBuilder(prefix="fsm_owner", with_bot_id=True),
        )
    return MemoryStorage()


def create_dispatcher(settings: Settings | None = None) -> Dispatcher:
    # Many people's updates at once, each person's in order (apps.core.bot_runtime).
    dp = OrderedDispatcher(storage=create_storage(settings))
    register_all_middlewares(dp)
    register_all_handlers(dp)
    return dp
