import re
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from bot.commands import private_commands

# How Telegram writes a command: "/name", optionally "@bot", then a space or the end.
COMMAND = re.compile(r"/(?P<command>[A-Za-z0-9_]{1,32})(?:@[A-Za-z0-9_]+)?(?:\s|$)")


@cache
def menu_commands() -> frozenset[str]:
    """The commands in the private chat menu (bot/commands.py), without the slash."""
    return frozenset(command.command for command in private_commands())


def command_of(message: Message) -> str | None:
    """The command a message starts with, lowercased ("checkin" for `/Checkin@our_bot now`)."""
    found = COMMAND.match(message.text or "")
    return found["command"].lower() if found else None


def is_menu_command(message: Message) -> bool:
    return command_of(message) in menu_commands()


def interrupts(message: Message) -> bool:
    """A menu command other than /start: the start router decides about /start itself (a deep
    link's handler may keep the conversation, plain /start ends it)."""
    command = command_of(message)
    return command in menu_commands() and command != "start"


class MenuCommandMiddleware(BaseMiddleware):
    """A command from the menu does what it says, whatever conversation the person was in.

    State-bound routers come before the feature routers (the task and announcement routers in
    the member router, the applicant router before the contact router), so that a proof photo
    or an answer always reaches the conversation waiting for it. Without this, "/checkin" typed
    while the bot waits for a task title would become the title. A menu command ends the
    conversation instead and is routed as if there had been none; other text, photos and
    commands outside the menu (a feature's own "/cancel") still reach the conversation.
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
