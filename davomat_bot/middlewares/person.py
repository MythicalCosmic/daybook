from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Update
from asgiref.sync import sync_to_async
from django.utils import timezone, translation

from apps.accounts.models import User
from apps.accounts.telegram_chat import language_of
from apps.companies.models import Company
from apps.members.models import Membership
from davomat_bot import edition


@dataclass(frozen=True)
class Person:
    """Who sent an update: the linked user and their membership (None until they link their
    Telegram with a link code), the organization, and the language to answer in."""

    user: User | None
    member: Membership | None
    company: Company | None
    language: str


class PersonMiddleware(BaseMiddleware):
    """Finds the person behind every private update and answers in their language.

    The bot never creates users: a Telegram account belongs to someone only once they claim a
    link code (apps.davomat), so a stranger who starts the bot leaves no trace. A linked person
    who writes or taps has started the bot and not blocked it, which notifications through it
    rely on (`owner_bot_started_at`, `owner_bot_blocked_at`: the one bot is the "owner" bot of
    apps.notifications in this edition)."""

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
        person = await sync_to_async(load_person)(tg_user.id, talking=_is_talking(event))
        data["person"] = person
        data["user"] = person.user
        with translation.override(person.language):
            return await handler(event, data)


def load_person(telegram_id: int, *, talking: bool) -> Person:
    company = edition.organization()
    user = edition.linked_user(telegram_id)
    if user is not None and talking:
        _record_started(user)
    member = edition.membership(user, company)
    if user is not None:
        language = language_of(user.language)
    else:
        language = language_of(company.default_language if company else "uz")
    return Person(user, member, company, language)


def _record_started(user: User) -> None:
    if user.owner_bot_started_at is None or user.owner_bot_blocked_at is not None:
        user.owner_bot_started_at = user.owner_bot_started_at or timezone.now()
        user.owner_bot_blocked_at = None
        user.save(update_fields=["owner_bot_started_at", "owner_bot_blocked_at"])


def _is_talking(event: TelegramObject) -> bool:
    """A message or a button press (not a block or unblock notice)."""
    return isinstance(event, Update) and (
        event.message is not None or event.callback_query is not None
    )
