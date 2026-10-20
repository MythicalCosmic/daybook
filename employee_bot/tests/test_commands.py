from aiogram.methods import SetMyCommands
from aiogram.types import BotCommandScopeAllPrivateChats

from bot.commands import set_commands


async def test_the_private_menu_has_the_module_commands(bot):
    await set_commands(bot)

    menus = [
        r
        for r in bot.requests
        if isinstance(r, SetMyCommands) and isinstance(r.scope, BotCommandScopeAllPrivateChats)
    ]
    assert {m.language_code for m in menus} == {None, "uz", "ru", "en"}
    for menu in menus:
        assert [c.command for c in menu.commands] == [
            "start",
            "tasks",
            "new",
            "checkin",
            "expense",
            "pay",
            "kudos",
            "announce",
        ]
        assert all(c.description for c in menu.commands)
