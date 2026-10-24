from aiogram.methods import SetMyCommands, SetMyDescription, SetMyShortDescription
from aiogram.types import BotCommandScopeAllPrivateChats
from django.utils import translation
from django.utils.translation import gettext

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
            "check",
            "checkin",
            "expense",
            "pay",
            "kudos",
            "kb",
            "calendar",
            "announce",
            "language",
            "help",
        ]
        assert all(c.description for c in menu.commands)


async def test_the_default_menu_is_in_uzbek(bot):
    """People whose Telegram is in another language get Uzbek replies, so an Uzbek menu too
    (research R1 L5)."""
    await set_commands(bot)

    [default] = [
        r
        for r in bot.requests
        if isinstance(r, SetMyCommands)
        and isinstance(r.scope, BotCommandScopeAllPrivateChats)
        and r.language_code is None
    ]
    with translation.override("uz"):
        assert default.commands[1].description == gettext("My tasks")


async def test_the_bot_describes_itself_in_three_languages(bot):
    await set_commands(bot)

    descriptions = {
        r.language_code: r.description for r in bot.requests if isinstance(r, SetMyDescription)
    }
    shorts = {
        r.language_code: r.short_description
        for r in bot.requests
        if isinstance(r, SetMyShortDescription)
    }
    assert set(descriptions) == set(shorts) == {None, "uz", "ru", "en"}
    assert descriptions[None] == descriptions["uz"]  # Uzbek for every other language
    assert descriptions["ru"].startswith("Daybook — рабочий бот")
    assert all(len(text) <= 512 for text in descriptions.values())
    assert all(len(text) <= 120 for text in shorts.values())
