"""What nothing else answered.

- A plain text from a member becomes "Add this as a task?" with what the bot understood
  (research R1 Q1): the quick-add preview, so a stray message never becomes a task by itself.
- Thanks, "ok" and stickers get a reaction rather than the whole home screen (C4, Q1).
- Greetings, unknown commands and anything else get the home message.
- A button no handler took is still answered, so its spinner stops.
"""

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.utils import translation
from django.utils.translation import gettext as _

from apps.members import bot_messages
from apps.members.models import Membership
from apps.tasks import quickadd
from bot.filters.membership import IsRegistered
from bot.handlers.member import cards
from bot.handlers.member.new_task import _preview_message
from bot.states.tasks import NewTask

router = Router(name="member_home")

THANKS = frozenset(
    {
        "rahmat",
        "raxmat",
        "katta rahmat",
        "rahmat sizga",
        "ok",
        "ok!",
        "okay",
        "ок",
        "окей",
        "хорошо",
        "спасибо",
        "спс",
        "thanks",
        "thank you",
        "",
        "",
        "ha",
        "xo'p",
        "xo‘p",
        "mayli",
    }
)
GREETINGS = frozenset(
    {
        "salom",
        "assalomu alaykum",
        "assalomu aleykum",
        "привет",
        "здравствуйте",
        "добрый день",
        "hello",
        "hi",
        "hey",
    }
)
SHORTEST_TASK = 4


@router.message(F.sticker)
async def sticker(message: Message, bot: Bot) -> None:
    await cards.react(bot, message, "")


@router.message(F.text, IsRegistered())
async def plain_text(message: Message, membership: Membership, state: FSMContext, bot: Bot) -> None:
    text = message.text.strip()
    plain = text.lower().strip(" !.,)")
    if plain in THANKS:
        await cards.react(bot, message, "")
        return
    if text.startswith("/") or plain in GREETINGS or len(text) < SHORTEST_TASK:
        await _home(message, membership)
        return
    found = quickadd.parse(text, now=cards.local_now(membership), lang=translation.get_language())
    if not found.title:
        await _home(message, membership)
        return
    data = {"title": found.title[:200], "raw": text[:200], "found": found.found}
    if found.due_at is not None:
        data["due"] = found.due_at.isoformat()
    if found.repeat:
        data["repeat"] = found.repeat
    if found.priority:
        data["urgent"] = True
    await state.set_state(NewTask.confirm)
    await state.set_data(data)
    body, markup = await sync_to_async(_preview_message)(membership, data)
    await message.answer(f"{_('Add this as a task?')}\n{body}", reply_markup=markup)


@router.message()
async def home(message: Message, membership: Membership) -> None:
    await _home(message, membership)


async def _home(message: Message, membership: Membership) -> None:
    text, markup = await sync_to_async(bot_messages.member_home)(membership)
    await message.answer(text, reply_markup=markup)


@router.callback_query()
async def unanswered(callback: CallbackQuery) -> None:
    """A button nothing took (an old message's, say): answer it, so no spinner runs on."""
    with suppress(TelegramAPIError):
        await callback.answer()
