import re
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject
from asgiref.sync import sync_to_async

from apps.accounts.services import bot_membership
from apps.members import bot_menu
from apps.members.bot_menu import MenuButton, registered
from apps.members.bot_messages import (
    MENU_APP,
    MENU_MY_TASKS,
    MENU_NEW_TASK,
    MENU_TO_CHECK,
    is_company_button,
)
from bot.commands import private_commands
from bot.filters.menu import is_label

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
    checker's button, or the company switch ("Kompaniya: Demo Dorixona"), in any language,
    also as the keyboards from before 25.10.2026 write them ("📱 Ilovani ochish")."""
    return _is_menu_text(message.text)


def is_main_menu_label(text: str | None) -> bool:
    """Any button of the main menu, the two task buttons included."""
    return bool(text) and (
        is_label(text, MENU_MY_TASKS) or is_label(text, MENU_NEW_TASK) or _is_menu_text(text)
    )


def _is_menu_text(text: str | None) -> bool:
    if not text:
        return False
    if is_label(text, MENU_APP) or is_label(text, MENU_TO_CHECK):
        return True
    return is_company_button(text) or any(is_label(text, button.msgid) for button in registered())


def interrupts(message: Message) -> bool:
    """A menu command other than /start, or a module's menu button: the start router decides
    about /start itself (a deep link's handler may keep the conversation, plain /start ends
    it)."""
    command = command_of(message)
    return (command in menu_commands() and command != "start") or is_menu_button(message)


def module_button(text: str | None) -> MenuButton | None:
    """The module's button `text` is, in any language ("Kassa"), if it is one."""
    return next((b for b in registered() if text and is_label(text, b.msgid)), None)


def sees(user, button: MenuButton) -> bool:
    """Whether `user` has `button` on their menu. A module label is a plain word since labels
    lost their emoji ("Kassa"), so typed as a task title by someone without that button, it is
    just text."""
    membership = bot_membership(user)
    return membership is not None and button in bot_menu.buttons_for(membership)


async def interrupts_for(message: Message, user) -> bool:
    if not interrupts(message):
        return False
    button = module_button(message.text) if command_of(message) is None else None
    if button is None or user is None:
        return True
    return await sync_to_async(sees)(user, button)


class MenuCommandMiddleware(BaseMiddleware):
    """A command from the menu does what it says, whatever conversation the person was in.

    State-bound routers come before the feature routers (the task and announcement routers in
    the member router, the applicant router before the contact router), so that a proof photo
    or an answer always reaches the conversation waiting for it. Without this, "/checkin" typed
    while the bot waits for a task title would become the title. A menu command ends the
    conversation instead and is routed as if there had been none; other text, photos and
    commands outside the menu (a feature's own "/cancel") still reach the conversation. A menu
    button a module registered ("Keldim") counts as a menu command.
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
            and await interrupts_for(event, data.get("user"))
        ):
            state: FSMContext | None = data.get("state")
            if state is not None:
                await state.clear()
            # The state filters read this, so no router sees the old conversation.
            data["raw_state"] = None
        return await handler(event, data)
