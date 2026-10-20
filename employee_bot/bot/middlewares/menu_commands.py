import re
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject

from bot.commands import private_commands

# How Telegram writes a command: "/name", optionally "@bot", then a space or the end.
COMMAND = re.compile(r"/(?P<command>[A-Za-z0-9_]{1,32})(?:@[A-Za-z0-9_]+)?(?:\s|$)")


@cache
def menu_commands() -> frozenset[str]:
    """The commands in the private chat menu (bot/commands.py), without the slash."""
    return frozenset(command.command for command in private_commands())


def is_menu_command(message: Message) -> bool:
    """`/checkin`, `/checkin@our_bot` or `/checkin something`, for a command from the menu."""
    found = COMMAND.match(message.text or "")
    return found is not None and found["command"].lower() in menu_commands()


class MenuCommandMiddleware(BaseMiddleware):
    """A command from the menu does what it says, whatever conversation the person was in.

    The state-bound routers come before the feature routers, so that a proof photo or an
    announcement text always reaches the conversation waiting for it. Without this, "/checkin"
    typed while the bot waits for a task title would become the title. A menu command ends the
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
            and data.get("raw_state") is not None
            and is_menu_command(event)
        ):
            state: FSMContext | None = data.get("state")
            if state is not None:
                await state.clear()
            # The state filters read this, so no router below sees the old conversation.
            data["raw_state"] = None
        return await handler(event, data)
