from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from apps.core.bot_runtime import DatabaseContext


class DjangoConnectionMiddleware(BaseMiddleware):
    """Runs the update's Django calls on the bots' shared pool of threads, so many people's
    updates are handled at once, each call with a healthy connection as Django gives each
    request (apps.core.bot_runtime)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with DatabaseContext():
            return await handler(event, data)
