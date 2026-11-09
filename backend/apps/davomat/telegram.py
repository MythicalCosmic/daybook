"""Talking to Telegram about the organization's bot: whether a token works (`getMe`).

Tests never reach Telegram: they replace `get_me` (or `check_token`).
"""

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramUnauthorizedError
from aiogram.utils.token import TokenValidationError, validate_token

logger = logging.getLogger(__name__)

TIMEOUT_S = 10


@dataclass(frozen=True)
class BotInfo:
    id: int
    username: str
    name: str


class TokenRefused(Exception):
    """Telegram says the token is no bot's (or it isn't shaped like a token at all)."""


class TelegramUnreachable(Exception):
    """Telegram couldn't be asked (network, timeout, an error on its side): try again."""


def get_me(token: str) -> BotInfo:
    """The bot behind `token`, as Telegram's `getMe` tells it."""

    async def ask() -> BotInfo:
        async with Bot(token) as bot:
            me = await bot.get_me(request_timeout=TIMEOUT_S)
            return BotInfo(id=me.id, username=me.username or "", name=me.full_name or "")

    return asyncio.run(ask())


def check_token(token: str) -> BotInfo:
    """`get_me`, with Telegram's answers sorted: raises TokenRefused or TelegramUnreachable."""
    try:
        validate_token(token)
    except TokenValidationError as exc:
        raise TokenRefused(str(exc)) from exc
    try:
        info = get_me(token)
    except TelegramUnauthorizedError as exc:
        raise TokenRefused(str(exc)) from exc
    except (TelegramAPIError, OSError, TimeoutError) as exc:
        logger.warning("getMe failed: %s", exc)
        raise TelegramUnreachable(str(exc)) from exc
    if not info.username:
        raise TokenRefused("The bot has no username.")
    return info
