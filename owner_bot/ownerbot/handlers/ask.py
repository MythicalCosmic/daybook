"""Questions typed to the owner bot, answered by Ask AI (apps.ai.chat) from the company's data.

An owner or top manager types a question ("Bugun nechta vazifa kechikdi?", "Kim sovuq zanjirdan
sust?") outside any conversation: the bot answers "Thinking…" at once, Ask AI works on it on the
ai queue with the same read-only tools, permissions and branch scope as in the dashboard, and
the answer replaces "Thinking…" when it is ready (Markdown turned into Telegram's HTML,
`ownerbot.answers`), with a button to the whole conversation in the dashboard.

- Only where Ask AI is available to the person (`chat.available`: `ai.use`, the company's AI
  on, Claude or AI_FAKE there); otherwise the text falls through to the home message, as before.
- With several such companies the bot asks which one first.
- Follow-up questions within two hours continue the same conversation (`AITurn.page` "telegram"
  marks the bot's), so "and yesterday?" keeps its context; a full conversation starts a new one.
- The handler returns at once; a background task waits for the answer (`WAIT_SECONDS`), so the
  person's next update is never held up behind it.
"""

import asyncio
import logging
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone, translation

from apps.accounts.models import User
from apps.ai import chat
from apps.ai.models import AIConversation, AITurn
from apps.members.models import Membership
from ownerbot import bot_messages, brief
from ownerbot.callbacks import AskPick
from ownerbot.states import AskAI

logger = logging.getLogger(__name__)

router = Router(name="ask")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

PAGE = "telegram"
POLL_SECONDS = 1.5
WAIT_SECONDS = 150
REUSE = timedelta(hours=2)
FINAL = (AITurn.Status.DONE, AITurn.Status.FAILED, AITurn.Status.CANCELLED)
# Answers still being waited for: kept so they aren't collected before they finish.
_waiting: set[asyncio.Task] = set()


def askable(user: User) -> list[Membership]:
    """The person's companies (as the owner bot serves them) where they may use Ask AI."""
    return [member for member in brief.memberships(user) if chat.available(member)]


class CanAsk(Filter):
    """Typed text that isn't a command, from someone with Ask AI in at least one company."""

    async def __call__(self, message: Message, user: User | None = None) -> bool:
        if user is None or not message.text or message.text.startswith("/"):
            return False
        return bool(await sync_to_async(askable)(user))


def _conversation(member: Membership) -> AIConversation:
    recent = (
        AIConversation.objects.filter(
            membership=member,
            last_activity_at__gte=timezone.now() - REUSE,
            turn_count__lt=chat.MAX_TURNS,
            turns__page=PAGE,
        )
        .order_by("-last_activity_at")
        .first()
    )
    return recent or chat.start_conversation(member)


def _start(member: Membership, text: str) -> tuple[int, int]:
    with transaction.atomic():
        conversation = _conversation(member)
        turn = chat.start_turn(conversation, by=member, text=text, page=PAGE)
    return turn.pk, conversation.pk


def _turn_state(turn_id: int) -> tuple[str, str] | None:
    return AITurn.objects.filter(pk=turn_id).values_list("status", "text").first()


def _member(user: User, company_id: int) -> Membership | None:
    return next((m for m in askable(user) if m.company_id == company_id), None)


async def _deliver(
    bot: Bot,
    chat_id: int,
    message_id: int,
    turn_id: int,
    company_id: int,
    conversation_id: int,
    language: str,
) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + WAIT_SECONDS
    status, text = AITurn.Status.QUEUED, ""
    while True:
        row = await sync_to_async(_turn_state)(turn_id)
        if row is None:
            return
        status, text = row
        if status in FINAL:
            break
        if loop.time() >= deadline:
            status = "late"
            break
        await asyncio.sleep(POLL_SECONDS)
    with translation.override(language):
        body, markup = bot_messages.ask_answer(status, text, company_id, conversation_id)
    try:
        await bot.edit_message_text(
            body, chat_id=chat_id, message_id=message_id, reply_markup=markup
        )
    except TelegramBadRequest:  # the "Thinking…" message is gone: say it anew
        await bot.send_message(chat_id, body, reply_markup=markup)


async def ask(message: Message, bot: Bot, user: User, member: Membership, text: str) -> None:
    """Start the turn, say "Thinking…", and leave a task to put the answer in its place."""
    try:
        turn_id, conversation_id = await sync_to_async(_start)(member, text[: chat.TEXT_MAX])
    except chat.TurnRefused as refused:
        await message.answer(bot_messages.ask_refused(str(refused)))
        return
    sent = await message.answer(bot_messages.ask_thinking())
    task = asyncio.create_task(
        _deliver(
            bot,
            sent.chat.id,
            sent.message_id,
            turn_id,
            member.company_id,
            conversation_id,
            user.language,
        )
    )
    _waiting.add(task)
    task.add_done_callback(_waiting.discard)


async def answers_sent() -> None:
    """Wait for every answer still being waited for (the tests; a clean shutdown)."""
    while _waiting:
        await asyncio.gather(*list(_waiting), return_exceptions=True)


@router.message(StateFilter(None), F.text, CanAsk())
async def question(message: Message, user: User, state: FSMContext, bot: Bot) -> None:
    members = await sync_to_async(askable)(user)
    if len(members) > 1:
        await state.set_state(AskAI.company)
        await state.update_data(question=message.text[: chat.TEXT_MAX])
        text, markup = bot_messages.ask_which_company(
            [(member.company_id, member.company.name) for member in members]
        )
        await message.answer(text, reply_markup=markup)
        return
    await ask(message, bot, user, members[0], message.text)


@router.message(AskAI.company, F.text, ~F.text.startswith("/"))
async def another_question(message: Message, user: User, state: FSMContext, bot: Bot) -> None:
    """A new question while the bot waits for the company: this one is asked instead."""
    await state.clear()
    await question(message, user, state, bot)


@router.callback_query(AskPick.filter())
async def picked(
    callback: CallbackQuery, callback_data: AskPick, user: User, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    text = data.get("question", "")
    member = await sync_to_async(_member)(user, callback_data.company)
    await callback.answer()
    if member is None or not text:
        await callback.message.answer(bot_messages.ask_again())
        return
    await ask(callback.message, bot, user, member, text)
