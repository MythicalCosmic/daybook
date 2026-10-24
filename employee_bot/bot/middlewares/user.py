from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Update
from asgiref.sync import sync_to_async
from django.utils import translation

from apps.accounts.services import sync_telegram_user


class UserMiddleware(BaseMiddleware):
    """Loads (or creates) the User behind every update and activates their language.

    `first_contact` tells handlers that this update made the user: /start then asks for the
    language once, unless Telegram already says Uzbek (research R1 L2). `telegram_language` is
    the interface language Telegram reports, a weak hint in Uzbekistan."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot or _group_chatter(event):
            return await handler(event, data)

        user = await sync_to_async(sync_telegram_user)(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=tg_user.language_code,
        )
        data["user"] = user
        data["first_contact"] = getattr(user, "just_created", False)
        data["telegram_language"] = (tg_user.language_code or "")[:2].lower()
        with translation.override(user.language):
            return await handler(event, data)


def _group_chatter(update: Update) -> bool:
    """A plain message in a group: nothing for the bot, so nobody to look up or record."""
    message = update.message
    return (
        message is not None
        and message.chat.type != ChatType.PRIVATE
        and not (message.text or "").startswith("/")
    )
