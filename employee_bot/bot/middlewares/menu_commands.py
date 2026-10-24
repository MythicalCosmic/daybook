import re
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from apps.members.bot_menu import registered
from apps.members.bot_messages import MENU_APP, MENU_TO_CHECK, is_company_button
from bot.commands import private_commands
from bot.filters.menu import translations

# How Telegram writes a command: "/name", optionally "@bot", then a space or the end.
COMMAND = re.compile(r"/(?P<command>[A-Za-z0-9_]{1,32})(?:@[A-Za-z0-9_]+)?(?:\s|$)")


# Typed rather than picked from the menu, they still end a conversation: the language
# command's short forms, and settings.
HIDDEN_COMMANDS = frozenset({"til", "lang", "settings"})


@cache
def menu_commands() -> frozenset[str]:
    """The commands in the private chat menu (bot/commands.py), without the slash: the menu of
    someone in several companies too (/company), and the hidden short forms."""
    listed = private_commands(several_companies=True)
    return frozenset(command.command for command in listed) | HIDDEN_COMMANDS


def command_of(message: Message) -> str | None:
    """The command a message starts with, lowercased ("checkin" for `/Checkin@our_bot now`)."""
    found = COMMAND.match(message.text or "")
    return found["command"].lower() if found else None


def is_menu_command(message: Message) -> bool:
    return command_of(message) in menu_commands()


def is_menu_button(message: Message) -> bool:
    """A main-menu button a module registered (apps.members.bot_menu), the app's or the
    checker's button, or the company switch ("🏢 Demo Dorixona ▸"), in any language."""
    text = message.text
    if not text:
        return False
    if text in translations(MENU_APP) or text in translations(MENU_TO_CHECK):
        return True
    return is_company_button(text) or any(
        text in translations(button.msgid) for button in registered()
    )


def interrupts(message: Message) -> bool:
    """A menu command other than /start, or a module's menu button: the start router decides
    about /start itself (a deep link's handler may keep the conversation, plain /start ends
    it)."""
    command = command_of(message)
    return (command in menu_commands() and command != "start") or is_menu_button(message)


class MenuCommandMiddleware(BaseMiddleware):
    """A command from the menu does what it says, whatever conversation the person was in.

    State-bound routers come before the feature routers (the task and announcement routers in
    the member router, the applicant router before the contact router), so that a proof photo
    or an answer always reaches the conversation waiting for it. Without this, "/checkin" typed
    while the bot waits for a task title would become the title. A menu command ends the
    conversation instead and is routed as if there had been none; other text, photos and
    commands outside the menu (a feature's own "/cancel") still reach the conversation. A menu
    button a module registered ("📍 Keldim") counts as a menu command.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if (
            isinstance(event, Message)
            and event.chat.type == ChatType.PRIVATE
            and data.get("raw_state") is not None
            and interrupts(event)
        ):
            state: FSMContext | None = data.get("state")
            if state is not None:
                await state.clear()
            # The state filters read this, so no router sees the old conversation.
            data["raw_state"] = None
        return await handler(event, data)
