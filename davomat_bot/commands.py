"""The command menu Telegram shows in private chats with the Davomat bot, and the bot's profile
texts (the description before Start and the short About text)."""

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.telegram_chat import set_profile
from apps.core.models import Language

logger = logging.getLogger(__name__)

# Each language's own words (≤512 and ≤120 characters), as the other bots' profiles.
PROFILE = {
    "uz": (
        "Davomat — tashkilotingizning davomat boti.\n"
        "Terminal sizni ko‘rganda kelgan va ketgan vaqtingiz shu yerga keladi.\n"
        "/me — bugungi va shu oydagi davomatingiz.\n"
        "Rahbarlar uchun /today — bugun kim ishda, kim kechikdi.\n"
        "Boshlash uchun administrator bergan havolani oching.",
        "Kelish-ketish, kechikishlar va oylik davomat bir joyda.",
    ),
    "ru": (
        "Davomat — бот учёта посещаемости вашей организации.\n"
        "Когда терминал вас видит, время прихода и ухода приходит сюда.\n"
        "/me — ваш день и месяц.\n"
        "Для руководителей /today — кто сегодня на работе и кто опоздал.\n"
        "Чтобы начать, откройте ссылку от администратора.",
        "Приходы и уходы, опоздания и посещаемость за месяц в одном месте.",
    ),
    "en": (
        "Davomat — your organization's attendance bot.\n"
        "When a terminal sees you, your arrival and departure come here.\n"
        "/me: your day and your month.\n"
        "For managers, /today: who is at work and who is late.\n"
        "To start, open the link your administrator gave you.",
        "Arrivals and departures, lateness and your month in one place.",
    ),
}


def private_commands(*, manager: bool = True) -> list[BotCommand]:
    """The menu. Everyone gets the managers' /today in the default menu (Telegram shows one
    menu to all; the command says who may use it); a linked person's own chat gets theirs."""
    commands = [BotCommand(command="me", description=_("My day and month"))]
    if manager:
        commands.append(BotCommand(command="today", description=_("Who is at work today")))
        commands.append(
            BotCommand(command="report", description=_("Attendance report, Excel or PDF"))
        )
    commands += [
        BotCommand(command="language", description=_("Change language")),
        BotCommand(command="help", description=_("Help")),
        BotCommand(command="start", description=_("Home")),
    ]
    return commands


async def set_commands(bot: Bot) -> None:
    """Best effort: without menus the bot still works, so a failure only gets logged.

    No language code is the list for every other Telegram language: in Uzbek, like the replies
    those people get."""
    try:
        for language in (None, *Language.values):
            with translation.override(language or "uz"):
                await bot.set_my_commands(
                    private_commands(),
                    scope=BotCommandScopeAllPrivateChats(),
                    language_code=language,
                )
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the Davomat bot's command menu: %s", exc)
    await set_profile(bot, PROFILE)


async def relabel(bot: Bot, chat_id: int, *, language: str, manager: bool) -> None:
    """One person's menu in their language, with /today only for managers. Best effort."""
    with translation.override(language):
        commands = private_commands(manager=manager)
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except TelegramAPIError as exc:
        logger.info("Couldn't relabel chat %s: %s", chat_id, exc)
