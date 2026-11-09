"""`/start` (with `link_<code>`, the one-time link an admin makes for a person), `/help`, the
home message for anything else, and the block/unblock notices of private chats.

    /start link_<code>   link this Telegram to that employee or user (apps.davomat)
"""

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatMemberUpdated, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone, translation

from apps.accounts.models import User
from apps.accounts.telegram_chat import language_of
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from davomat_bot import bot_messages, commands, edition
from davomat_bot.middlewares.person import Person

router = Router(name="start")
# Last of all (handlers/__init__.py): whatever no other handler took.
fallback_router = Router(name="fallback")


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(
    message: Message,
    person: Person,
    bot: Bot,
    state: FSMContext,
    command: CommandObject | None = None,
) -> None:
    await state.clear()
    payload = (command.args or "").strip() if command else ""
    if payload.startswith(bot_messages.START_LINK):
        await claim(message, bot, payload.removeprefix(bot_messages.START_LINK))
        return
    await home(message, person)


async def home(message: Message, person: Person) -> None:
    text, markup = bot_messages.home(person.member, person.company, _first_name(message, person))
    await message.answer(text, reply_markup=markup)


def _first_name(message: Message, person: Person) -> str:
    if person.member is not None and person.member.first_name:
        return person.member.first_name
    return message.from_user.first_name or ""


async def claim(message: Message, bot: Bot, code: str) -> None:
    tg = message.from_user
    done, reason = await sync_to_async(_claim)(code, tg.id, tg.username or "", tg.first_name or "")
    if done is None:
        await message.answer(bot_messages.link_failed(reason))
        return
    text, markup, language, manager = done
    await message.answer(text, reply_markup=markup)
    await commands.relabel(bot, message.chat.id, language=language, manager=manager)


def _claim(code: str, telegram_id: int, username: str, first_name: str):
    """((text, markup, language, manager), None) once linked, else (None, the reason to show
    or None for the plain "this link doesn't work")."""
    if not code:
        return None, None
    try:
        # It also records that this person started the bot (notifications may come now).
        claimed = edition.claim_link(
            code, telegram_id=telegram_id, username=username, first_name=first_name
        )
    except DomainError as exc:  # apps.davomat's LinkRefused: unknown, used, expired, inactive
        return None, str(exc)
    except ObjectDoesNotExist, DjangoValidationError, ValueError:
        return None, None
    member = (
        Membership.objects.select_related("company", "user", "role", "position")
        .filter(pk=claimed.pk)
        .first()
    )
    if member is None:
        return None, None
    language = language_of(member.user.language)
    with translation.override(language):
        text, markup = bot_messages.linked(member)
    return (text, markup, language, bot_messages.sees_attendance(member)), None


@router.message(Command("help"), F.chat.type == ChatType.PRIVATE)
async def cmd_help(message: Message, person: Person, state: FSMContext) -> None:
    await state.clear()
    await message.answer(bot_messages.help_text(person.member, person.company))


@fallback_router.message(F.chat.type == ChatType.PRIVATE, StateFilter(None))
async def anything_else(message: Message, person: Person) -> None:
    """Text, a command or a file the bot has no use for: the home message, so nobody is left
    without an answer."""
    await home(message, person)


@router.my_chat_member(F.chat.type == ChatType.PRIVATE)
async def chat_member_changed(update: ChatMemberUpdated, user: User | None = None) -> None:
    if user is None:
        return
    blocked = update.new_chat_member.status == ChatMemberStatus.KICKED
    await sync_to_async(_record_block)(user, blocked)


def _record_block(user: User, blocked: bool) -> None:
    if blocked:
        User.objects.filter(pk=user.pk).update(owner_bot_blocked_at=timezone.now())
    else:
        User.objects.filter(pk=user.pk).update(
            owner_bot_blocked_at=None,
            owner_bot_started_at=user.owner_bot_started_at or timezone.now(),
        )
