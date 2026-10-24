"""The command menus Telegram shows: personal commands in private chats, group ones in groups,
and the bot's profile texts.

The lists themselves live in `apps.accounts.telegram_chat`, which a backend job also uses to
relabel a person's chat after a language change in the mini app. Picking a command from the
menu in a group adds the bot's @username, so the command still reaches the bot when other bots
are in the group too.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from django.utils import translation

from apps.accounts.telegram_chat import (
    EMPLOYEE_PROFILE,
    group_commands,
    menu_button,
    private_commands,
    set_profile,
)
from apps.core.models import Language

__all__ = ["group_commands", "menu_button", "private_commands", "set_commands"]

logger = logging.getLogger(__name__)


async def set_commands(bot: Bot) -> None:
    """Best effort: without menus the bot still works, so a failure only gets logged.

    No language code is the list for every other Telegram language (Kazakh, Turkish…): it is in
    Uzbek, like the bot's replies to those people (research R1 L5)."""
    try:
        for language in (None, *Language.values):
            with translation.override(language or "uz"):
                await bot.set_my_commands(
                    private_commands(),
                    scope=BotCommandScopeAllPrivateChats(),
                    language_code=language,
                )
                await bot.set_my_commands(
                    group_commands(), scope=BotCommandScopeAllGroupChats(), language_code=language
                )
        # One menu button for every chat, so in the bot's first language.
        with translation.override("uz"):
            await bot.set_chat_menu_button(menu_button=menu_button())
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the command menus: %s", exc)
    await set_profile(bot, EMPLOYEE_PROFILE)
