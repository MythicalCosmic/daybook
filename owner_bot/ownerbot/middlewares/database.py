from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from asgiref.sync import sync_to_async
from django.db import close_old_connections


class DjangoConnectionMiddleware(BaseMiddleware):
    """Drops stale or broken DB connections around each update, as Django does per request."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        await sync_to_async(close_old_connections)()
        try:
            return await handler(event, data)
        finally:
            await sync_to_async(close_old_connections)()
