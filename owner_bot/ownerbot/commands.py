"""The command menu Telegram shows in private chats with the owner bot.

Package A adds `/new`, `/today` and `/dashboard` here together with their handlers.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.models import Language

logger = logging.getLogger(__name__)


def private_commands() -> list[BotCommand]:
    return [BotCommand(command="start", description=_("Home"))]


async def set_commands(bot: Bot) -> None:
    """Best effort: without menus the bot still works, so a failure only gets logged."""
    try:
        for language in (None, *Language.values):
            with translation.override(language or "en"):
                await bot.set_my_commands(
                    private_commands(),
                    scope=BotCommandScopeAllPrivateChats(),
                    language_code=language,
                )
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the owner bot's command menu: %s", exc)
