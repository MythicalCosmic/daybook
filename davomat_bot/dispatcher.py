"""Builds the Davomat bot and its dispatcher (used by `__main__` and by the tests)."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from apps.core.bot_runtime import FitTelegramLimits, OrderedDispatcher, WaitOnFloodLimit
from davomat_bot.config import Settings, load_settings
from davomat_bot.handlers import register_all_handlers
from davomat_bot.middlewares import register_all_middlewares


def create_bot(token: str) -> Bot:
    # No link previews: a URL in a notification would push its buttons down.
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    # Past Telegram's rate replies wait and go, not get dropped.
    bot.session.middleware(WaitOnFloodLimit())
    # A text past Telegram's length is cut to fit rather than refused.
    bot.session.middleware(FitTelegramLimits())
    return bot


def create_storage(settings: Settings | None = None) -> BaseStorage:
    settings = settings or load_settings()
    if settings.FSM_REDIS_URL:
        # Its own key prefix, should it share a Redis with other bots.
        return RedisStorage.from_url(
            settings.FSM_REDIS_URL,
            key_builder=DefaultKeyBuilder(prefix="fsm_davomat", with_bot_id=True),
        )
    return MemoryStorage()


def create_dispatcher(settings: Settings | None = None) -> Dispatcher:
    # Many people's updates at once, each person's in order (apps.core.bot_runtime).
    dp = OrderedDispatcher(storage=create_storage(settings))
    register_all_middlewares(dp)
    register_all_handlers(dp)
    return dp
