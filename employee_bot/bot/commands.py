"""The command menus Telegram shows: personal commands in private chats, group ones in groups.

Picking a command from the menu in a group adds the bot's @username, so the command still
reaches the bot when other bots are in the group too.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.models import Language

logger = logging.getLogger(__name__)


def private_commands() -> list[BotCommand]:
    return [
        BotCommand(command="start", description=_("Home")),
        BotCommand(command="tasks", description=_("My tasks")),
        BotCommand(command="new", description=_("New task")),
    ]


def group_commands() -> list[BotCommand]:
    return [
        BotCommand(command="connect", description=_("Link this group to your company")),
        BotCommand(command="settings", description=_("Choose what gets posted here")),
        BotCommand(command="disconnect", description=_("Stop posting here")),
    ]


async def set_commands(bot: Bot) -> None:
    """Best effort: without menus the bot still works, so a failure only gets logged."""
    try:
        # No language code is the fallback for languages without their own menu.
        for language in (None, *Language.values):
            with translation.override(language or "en"):
                await bot.set_my_commands(
                    private_commands(),
                    scope=BotCommandScopeAllPrivateChats(),
                    language_code=language,
                )
                await bot.set_my_commands(
                    group_commands(), scope=BotCommandScopeAllGroupChats(), language_code=language
                )
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the command menus: %s", exc)
