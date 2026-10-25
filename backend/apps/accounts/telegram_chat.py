"""The employee bot's chat with one person, in their language (research R1 L1 to L7): its command
menu, menu button, the bot's profile texts, and relabelling a chat after a language change.

In the backend rather than the bot package: a Celery job relabels the chat when someone changes
their language in the mini app, and workers can't import the bot.

What Telegram lets a bot relabel per person: the reply keyboard (only by sending a message that
carries it), the command menu (`BotCommandScopeChat` outranks the per-language lists) and the
menu button. The name and descriptions follow the Telegram interface's language instead.
"""

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.core.models import Language

logger = logging.getLogger(__name__)

# Native names, no flags (flags stand for countries), as the mini app's picker writes them.
LANGUAGE_NAMES = {"uz": "O‘zbekcha", "ru": "Русский", "en": "English"}
LANGUAGES = ("uz", "ru", "en")

# What the language picker says. Each language's own words, not translations through the
# catalogue: the confirmation must read right in the language just picked, from the first try.
# The picker names the current language in words; its button is also coloured (no tick marks).
PICK_TITLE = {
    "uz": "Tilni tanlang. Hozir: O‘zbekcha.",
    "ru": "Выберите язык. Сейчас: русский.",
    "en": "Choose a language. Now: English.",
}
# Everyone starts in Uzbek (the owner's "uzbek first", 25.10.2026): the greeting carries this one
# small button, in all three languages since it is for whoever doesn't read Uzbek.
LANGUAGE_BUTTON = "Til / Язык / Language"
CHANGED = {
    "uz": "Endi o‘zbek tilida yozaman. Ilova ham shu tilda ochiladi. Menyu yangilandi.",
    "ru": "Теперь пишу по-русски. Приложение тоже откроется на русском. Меню обновлено.",
    "en": "I'll write in English from now on. The app will open in English too. "
    "The menu is updated.",
}
# The owner bot has no reply keyboard to replace: just the words.
CHANGED_SHORT = {
    "uz": "Endi o‘zbek tilida yozaman.",
    "ru": "Теперь пишу по-русски.",
    "en": "I'll write in English from now on.",
}
ALREADY = {
    "uz": "O‘zbekcha allaqachon tanlangan",
    "ru": "Русский уже выбран",
    "en": "English is already selected",
}
CURRENT = {"uz": "Til: O‘zbekcha", "ru": "Язык: русский", "en": "Language: English"}

# The bots' profiles (L7): the description fills the empty chat before Start (≤512 characters),
# the short description is the About text and shows on shared links (≤120).
EMPLOYEE_PROFILE = {
    "uz": (
        "Daybook — jamoangiz uchun ish boti.\n"
        "Vazifalaringizni shu yerda olasiz va bajarilganini belgilaysiz.\n"
        "Muddat yaqinlashganda eslatib turaman.\n"
        "Menejeringiz natijani shu yerda qabul qiladi.\n"
        "Boshlash uchun menejeringiz yuborgan taklif havolasini oching.",
        "Jamoangiz uchun vazifalar, eslatmalar va hisobotlar.",
    ),
    "ru": (
        "Daybook — рабочий бот вашей команды.\n"
        "Здесь вы получаете задачи и отмечаете выполнение.\n"
        "Напомню, когда подходит срок.\n"
        "Руководитель принимает работу прямо здесь.\n"
        "Чтобы начать, откройте ссылку-приглашение от руководителя.",
        "Задачи, напоминания и отчёты для вашей команды.",
    ),
    "en": (
        "Daybook — the work bot for your team.\n"
        "Get your tasks here and mark them done.\n"
        "I'll remind you when a deadline is near.\n"
        "Your manager checks the work right here.\n"
        "To start, open the invite link your manager sent you.",
        "Tasks, reminders and reports for your team.",
    ),
}
OWNER_PROFILE = {
    "uz": (
        "Biznesingiz egasi uchun bot.\n"
        "/today — bugungi raqamlar va sizni kutayotgan ishlar.\n"
        "So‘rov va xarajatlarni shu yerda tasdiqlaysiz.\n"
        "Boshqaruv paneliga kirishni shu yerda tasdiqlaysiz.\n"
        "Boshlash uchun /start bosing.",
        "Biznesingiz bir qarashda: raqamlar, tasdiqlar va ogohlantirishlar.",
    ),
    "ru": (
        "Бот владельца вашего бизнеса.\n"
        "/today — цифры за сегодня и что ждёт вашего решения.\n"
        "Одобряйте заявки и расходы прямо здесь.\n"
        "Подтверждайте вход в панель управления.\n"
        "Чтобы начать, нажмите /start.",
        "Ваш бизнес на виду: цифры, одобрения и уведомления.",
    ),
    "en": (
        "The owner's bot for your business.\n"
        "/today: today's numbers and what waits for you.\n"
        "Approve requests and expenses right here.\n"
        "Confirm dashboard sign-ins.\n"
        "To start, tap /start.",
        "Your business at a glance: numbers, approvals and alerts.",
    ),
}


def private_commands(*, several_companies: bool = False) -> list[BotCommand]:
    """The menu of private chats. Telegram shows one default menu to everyone, so the module
    commands (/checkin, /expense, /pay, /kudos, /kb, /calendar) are listed even where a module
    is off: each module's handler answers that case. /company only goes into the menus of
    people in several companies (set per chat)."""
    commands = [
        BotCommand(command="start", description=_("Home")),
        BotCommand(command="tasks", description=_("My tasks")),
        BotCommand(command="new", description=_("New task")),
        BotCommand(command="check", description=_("Work to check")),
        BotCommand(command="checkin", description=_("Check in or out")),
        BotCommand(command="expense", description=_("Submit an expense with a receipt")),
        BotCommand(command="pay", description=_("My pay and payslips")),
        BotCommand(command="kudos", description=_("Thank a colleague")),
        BotCommand(command="kb", description=_("Knowledge base: pages to read")),
        BotCommand(command="calendar", description=_("Company calendar: the next 7 days")),
        BotCommand(command="announce", description=_("Send an announcement (managers)")),
    ]
    if several_companies:
        commands.append(BotCommand(command="company", description=_("Switch company")))
    commands += [
        BotCommand(command="language", description=_("Change language")),
        BotCommand(command="help", description=_("Help")),
    ]
    return commands


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
    from apps.members.bot_messages import MENU_APP

    url = settings.EMPLOYEE_MINIAPP_URL
    if url.startswith("https://"):
        return MenuButtonWebApp(text=_(MENU_APP), web_app=WebAppInfo(url=url))
    return MenuButtonCommands()


def language_of(code: str | None) -> str:
    code = (code or "")[:2].lower()
    return code if code in LANGUAGES else "uz"


@dataclass(frozen=True)
class ChatLabels:
    commands: list[BotCommand]
    button: MenuButtonWebApp | MenuButtonCommands
    message: tuple | None  # (text, reply markup) carrying the reply keyboard, or None


def chat_labels(user: User, membership=None, *, confirm: bool = True) -> ChatLabels:
    """What the chat shows in `user.language` (reads the database, so call it from sync code):
    the command menu, the menu button and, with `confirm`, the message that carries the reply
    keyboard (the main menu for a member, their status for anyone else)."""
    from apps.members import bot_messages
    from apps.members.models import Membership

    member = membership
    approved = member is not None and member.status == Membership.Status.APPROVED
    with translation.override(user.language):
        commands = private_commands(several_companies=_several(user))
        button = menu_button()
        message = None
        if confirm:
            if approved and member.is_onboarded:
                message = (CHANGED[language_of(user.language)], bot_messages.main_menu(member))
            else:
                message = bot_messages.status(member)
    return ChatLabels(commands, button, message)


async def relabel(
    bot: Bot,
    chat_id: int,
    user: User,
    membership=None,
    *,
    confirm: bool = True,
    silent: bool = False,
) -> None:
    """The chat in `user.language` (see `chat_labels`), from async code such as the bot's
    handlers. Best effort: each part that Telegram refuses is logged and skipped."""
    labels = await sync_to_async(chat_labels)(user, membership, confirm=confirm)
    await send_labels(bot, chat_id, labels, silent=silent)


async def send_labels(bot: Bot, chat_id: int, labels: ChatLabels, *, silent: bool) -> None:
    commands, button, message = labels.commands, labels.button, labels.message
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the commands of chat %s: %s", chat_id, exc)
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
    except TelegramAPIError as exc:
        logger.warning("Couldn't label the menu button of chat %s: %s", chat_id, exc)
    if message is not None:
        text, markup = message
        try:
            await bot.send_message(chat_id, text, reply_markup=markup, disable_notification=silent)
        except TelegramAPIError as exc:
            logger.warning("Couldn't send the new menu to chat %s: %s", chat_id, exc)


def relabel_employee_chat(user_id: int) -> None:
    """After a language change in the mini app (contract 11): the person's chat with the
    employee bot follows, quietly, since they did it themselves. Only for approved members:
    others get their status at their next message anyway."""
    from apps.accounts.services import bot_membership
    from apps.members.models import Membership

    user = User.objects.filter(pk=user_id).first()
    if user is None or user.telegram_id is None:
        return
    membership = bot_membership(user)
    if membership is None or membership.status != Membership.Status.APPROVED:
        return
    token = settings.EMPLOYEE_BOT_TOKEN
    if settings.TELEGRAM_DRY_RUN or not token:
        logger.info("Not relabelling chat %s: no employee bot to do it", user.telegram_id)
        return
    labels = chat_labels(user, membership)
    asyncio.run(_send_with(token, user.telegram_id, labels))


async def _send_with(token: str, chat_id: int, labels: ChatLabels) -> None:
    async with Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
        await send_labels(bot, chat_id, labels, silent=True)


async def set_profile(bot: Bot, profile: dict[str, tuple[str, str]]) -> None:
    """The bot's description and short description in every language, and in Uzbek for anyone
    whose Telegram is in another language (L5, L7). Best effort, like the command menus."""
    try:
        for language in (None, *Language.values):
            description, short = profile[language or "uz"]
            await bot.set_my_description(description=description, language_code=language)
            await bot.set_my_short_description(short_description=short, language_code=language)
    except TelegramAPIError as exc:
        logger.warning("Couldn't set the bot's description: %s", exc)


def _several(user: User) -> bool:
    from apps.members.models import Membership

    return (
        Membership.objects.filter(
            user=user, status=Membership.Status.APPROVED, company__is_active=True
        ).count()
        > 1
    )
