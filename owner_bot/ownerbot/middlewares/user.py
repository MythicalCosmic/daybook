from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TelegramUser
from asgiref.sync import sync_to_async
from django.utils import timezone, translation

from apps.accounts.models import User
from apps.accounts.services import sync_telegram_user


class OwnerUserMiddleware(BaseMiddleware):
    """Loads (or creates) the User behind every private update and activates their language.

    A private message or button press means the person has started the owner bot (and not
    blocked it), so owner notifications may now come through here: `owner_bot_started_at`.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if tg_user is None or tg_user.is_bot or chat is None or chat.type != ChatType.PRIVATE:
            return await handler(event, data)
        user = await sync_to_async(load_user)(tg_user, talking=_is_talking(event))
        data["user"] = user
        with translation.override(user.language):
            return await handler(event, data)


def load_user(tg_user: TelegramUser, *, talking: bool) -> User:
    user = sync_telegram_user(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        language_code=None,  # a new person starts in Uzbek (the owner's "uzbek first")
    )
    if talking and (user.owner_bot_started_at is None or user.owner_bot_blocked_at is not None):
        user.owner_bot_started_at = user.owner_bot_started_at or timezone.now()
        user.owner_bot_blocked_at = None
        user.save(update_fields=["owner_bot_started_at", "owner_bot_blocked_at"])
    return user


def _is_talking(event: TelegramObject) -> bool:
    """A message or a button press (not a block or unblock notice)."""
    return isinstance(event, Update) and (
        event.message is not None or event.callback_query is not None
    )
