"""The command menu Telegram shows in private chats with the Davomat bot, the button beside the
message field (the web app as a Mini App for the people who use it), and the bot's profile texts
(the description before Start and the short About text)."""

import asyncio
import hashlib
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.telegram_chat import set_profile
from apps.core.bot_runtime import DatabaseContext
from apps.core.models import Language
from apps.davomat import conf as davomat_conf
from apps.members.models import Membership
from davomat_bot import bot_messages, edition
from davomat_bot.bot_messages import MenuButton

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


async def relabel(
    bot: Bot, chat_id: int, *, language: str, manager: bool, menu: MenuButton
) -> None:
    """One person's menu in their language, with /today only for managers, and the button
    beside the message field (`menu`: bot_messages.menu_button, the web app for its users).
    Best effort."""
    with translation.override(language):
        commands = private_commands(manager=manager)
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except TelegramAPIError as exc:
        logger.info("Couldn't relabel chat %s: %s", chat_id, exc)
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=menu)
    except TelegramAPIError as exc:
        logger.info("Couldn't set the menu button of chat %s: %s", chat_id, exc)


# Every linked person who uses the web app gets the Mini App button once per bot (a new token
# is another bot, whose chats have no button yet) and web app address; people linked later get
# it when they claim their link. Kept in the cache, so restarts don't send it all again.
MENU_SYNC_KEY = "davomat:menu-buttons:{version}:{address}"
# Telegram allows a bot about 30 calls a second; this stays well under while polling runs too.
MENU_SYNC_PAUSE_S = 0.05


def menu_sync_key(version: str | None) -> str:
    address = hashlib.sha256(bot_messages.app_url().encode()).hexdigest()[:16]
    return MENU_SYNC_KEY.format(version=version or "0", address=address)


def menu_chats() -> list[tuple[int, MenuButton]]:
    """(chat, button) for every linked person of the organization who uses the web app and
    hasn't blocked the bot."""
    company = edition.organization()
    url = bot_messages.app_url(f"c/{company.pk}") if company is not None else ""
    if not url:
        return []
    button = bot_messages.web_app_menu(url, davomat_conf.product_name(company))
    people = Membership.objects.filter(
        company=company,
        status=Membership.Status.APPROVED,
        user__telegram_id__isnull=False,
        user__is_active=True,
        user__owner_bot_blocked_at__isnull=True,
    ).select_related("company", "user", "role")
    return [
        (person.user.telegram_id, button)
        for person in people.order_by("pk")
        if bot_messages.uses_dashboard(person)
    ]


async def sync_menu_buttons(bot: Bot, version: str | None) -> int:
    """Once per token version and web app address: the Mini App button for everyone linked
    who uses the web app, at most ~20 calls a second. Best effort; returns how many chats got
    it. Interrupted (a restart), it runs again next time."""
    key = menu_sync_key(version)
    try:
        if await cache.aget(key):
            return 0
        async with DatabaseContext():
            chats = await sync_to_async(menu_chats)()
    except Exception:  # Redis or the database away: the next start tries again
        logger.warning("Couldn't set the web app buttons now", exc_info=True)
        return 0
    done = 0
    for chat_id, button in chats:
        try:
            await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
            done += 1
        except TelegramAPIError as exc:
            logger.info("Couldn't set the menu button of chat %s: %s", chat_id, exc)
        await asyncio.sleep(MENU_SYNC_PAUSE_S)
    with suppress(Exception):  # unsaved, the next start sends them again: harmless
        await cache.aset(key, True, timeout=None)
    if done:
        logger.info("The web app button is set for %s people", done)
    return done
