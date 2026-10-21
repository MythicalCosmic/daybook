"""The command menus Telegram shows: personal commands in private chats, group ones in groups.

Picking a command from the menu in a group adds the bot's @username, so the command still
reaches the bot when other bots are in the group too.
"""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.models import Language
from apps.members.bot_messages import MENU_APP

logger = logging.getLogger(__name__)


def private_commands() -> list[BotCommand]:
    # Telegram shows one menu to everyone, so the module commands (/checkin, /expense, /pay,
    # /kudos, /kb, /calendar) are listed even where the module is off: each module's handler in
    # bot/handlers/features/ answers that case. Until it exists the command gets the home screen.
    return [
        BotCommand(command="start", description=_("Home")),
        BotCommand(command="tasks", description=_("My tasks")),
        BotCommand(command="new", description=_("New task")),
        BotCommand(command="checkin", description=_("Check in or out")),
        BotCommand(command="expense", description=_("Submit an expense with a receipt")),
        BotCommand(command="pay", description=_("My pay and payslips")),
        BotCommand(command="kudos", description=_("Thank a colleague")),
        BotCommand(command="kb", description=_("Knowledge base: pages to read")),
        BotCommand(command="calendar", description=_("Company calendar: the next 7 days")),
        BotCommand(command="announce", description=_("Send an announcement (managers)")),
    ]


def group_commands() -> list[BotCommand]:
    return [
        BotCommand(command="connect", description=_("Link this group to your company")),
        BotCommand(command="settings", description=_("Choose what gets posted here")),
        BotCommand(command="disconnect", description=_("Stop posting here")),
    ]


def menu_button() -> MenuButtonWebApp | MenuButtonCommands:
    """The chat's menu button opens the mini app (Telegram needs an https address). A Mini App
    opened this way gets initData and signs the person in; one opened from a keyboard button
    wouldn't, so the main menu's app button only asks the bot for an inline one."""
    url = settings.EMPLOYEE_MINIAPP_URL
    if url.startswith("https://"):
        return MenuButtonWebApp(text=_(MENU_APP), web_app=WebAppInfo(url=url))
    return MenuButtonCommands()


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
        # One menu button for every chat, so in the bot's first language.
        with translation.override("uz"):
            await bot.set_chat_menu_button(menu_button=menu_button())
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the command menus: %s", exc)
