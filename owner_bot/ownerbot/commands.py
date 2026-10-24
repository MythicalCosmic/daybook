"""The command menu and the menu button Telegram shows in private chats with the owner bot, and
the bot's profile texts (research R1 L5, L7, L8)."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.telegram_chat import OWNER_PROFILE, set_profile
from apps.core.models import Language

logger = logging.getLogger(__name__)


def private_commands() -> list[BotCommand]:
    return [
        BotCommand(command="today", description=_("Today at a glance")),
        BotCommand(command="dashboard", description=_("Open the dashboard")),
        BotCommand(command="new", description=_("Create a company")),
        BotCommand(command="language", description=_("Change language")),
        BotCommand(command="start", description=_("Home")),
    ]


def menu_button() -> MenuButtonWebApp | MenuButtonCommands:
    """The "Dashboard" button opens the console as a Mini App (needs an https address)."""
    url = settings.DASHBOARD_URL
    if url.startswith("https://"):
        return MenuButtonWebApp(text=_("Dashboard"), web_app=WebAppInfo(url=url))
    return MenuButtonCommands()


async def set_commands(bot: Bot) -> None:
    """Best effort: without menus the bot still works, so a failure only gets logged.

    No language code is the list for every other Telegram language: it is in Uzbek, like the
    replies those people get (research R1 L5)."""
    try:
        for language in (None, *Language.values):
            with translation.override(language or "uz"):
                await bot.set_my_commands(
                    private_commands(),
                    scope=BotCommandScopeAllPrivateChats(),
                    language_code=language,
                )
        with translation.override("uz"):
            await bot.set_chat_menu_button(menu_button=menu_button())
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the owner bot's command menu: %s", exc)
    await set_profile(bot, OWNER_PROFILE)
