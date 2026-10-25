"""What the task handlers share: finding a task the member may see, acting on it through a
service, and drawing its card where it is.

A task message is one living message (research R1 C2, C3): actions edit the card that was
tapped, and a refusal that only means "it's already like that" is a toast, not a pop-up (C6).
"""

import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.tasks import bot_messages as task_messages
from apps.tasks import queries, rules, services
from apps.tasks import tasks as jobs
from apps.tasks.models import Task
from apps.tasks.queries import TASK_RELATIONS

CAPTION_LIMIT = 1024
# An album's other photos arrive as their own messages within a moment of the first.
ALBUM_WINDOW = 30.0
_albums: dict[str, float] = {}


@dataclass
class Outcome:
    """What a task action produced: the refreshed card, and why it didn't go through."""

    message: BotMessage | None = None
    alert: str | None = None
    task: Task | None = None
    soft: bool = False  # the task already was as asked: a toast, not a pop-up

    @property
    def done(self) -> bool:
        return self.alert is None and self.task is not None


def gone() -> str:
    return _("This task was deleted or given to someone else.")


def local_now(membership: Membership) -> datetime:
    return timezone.localtime(timezone.now(), ZoneInfo(membership.company.timezone))


def visible(member: Membership):
    return queries.visible_tasks(member).prefetch_related("checklist")


def load(member: Membership, task_id: int) -> Task | None:
    """The task as the member sees it; one they just acted on even if their view of it ends
    there (a checker without tasks.view_all stops seeing work once it's accepted)."""
    task = visible(member).filter(pk=task_id).first()
    if task is None:
        task = (
            Task.objects.select_related(*TASK_RELATIONS)
            .prefetch_related("checklist")
            .filter(pk=task_id, company_id=member.company_id)
            .first()
        )
    return task


@sync_to_async
def find(member: Membership, task_id: int) -> Task | None:
    return visible(member).filter(pk=task_id).first()


@sync_to_async
def card(member: Membership, task_id: int, *, seen: bool = False) -> Outcome:
    task = visible(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=gone())
    if seen:
        services.mark_seen(task, by=member)  # the assignee opened it (research R2 T36)
    return Outcome(message=task_messages.task_card(task, member, timezone.now()), task=task)


def act_now(member: Membership, task_id: int, action, **kwargs) -> Outcome:
    """Run `action(task, by=member, **kwargs)` and draw the card after it (sync code; the
    handlers use `act`)."""
    task = visible(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=gone())
    alert = None
    soft = False
    try:
        action(task, by=member, **kwargs)
    except (DomainError, PermissionDenied) as exc:
        alert = str(exc) or _("You can't do that.")
        task = load(member, task_id)
        soft = task is not None and _already(action, task)
    task = load(member, task_id)
    if task is None:
        return Outcome(alert=alert or gone())
    message = task_messages.task_card(task, member, timezone.now())
    return Outcome(message=message, alert=alert, task=task, soft=soft)


act = sync_to_async(act_now)


def _already(action, task: Task) -> bool:
    """A refusal that only means the task already is as asked (a double tap)."""
    if action is services.start_task:
        return task.status == Task.Status.IN_PROGRESS
    if action is services.complete_task:
        return task.status in (Task.Status.DONE, Task.Status.REVIEW)
    if action in (services.confirm_task, services.return_task):
        return task.status != Task.Status.REVIEW
    if action is services.reopen_task:
        return task.is_open
    return False


async def show(callback: CallbackQuery, outcome: Outcome, success: str | None = None) -> None:
    """Edit the tapped message into the card and answer the tap."""
    if outcome.message is not None:
        await edit(callback, outcome.message)
    if outcome.alert:
        await callback.answer(outcome.alert[:200], show_alert=not outcome.soft)
    else:
        await callback.answer(success[:200] if success else None)


async def edit(callback: CallbackQuery, message: BotMessage) -> None:
    if not isinstance(callback.message, Message):
        return
    await edit_message(callback.message, message)


async def edit_message(target: Message, message: BotMessage) -> None:
    text, markup = message
    with suppress(TelegramBadRequest):  # unchanged, or too old to edit
        if target.photo or target.document:
            await target.edit_caption(caption=_caption(text), reply_markup=markup)
        else:
            await target.edit_text(text, reply_markup=markup)


async def edit_at(bot: Bot, chat_id: int, message_id: int, message: BotMessage) -> None:
    """Edit a message the conversation kept the id of (the card a proof was asked on)."""
    text, markup = message
    try:
        await bot.edit_message_text(
            text=text, chat_id=chat_id, message_id=message_id, reply_markup=markup
        )
    except TelegramBadRequest as exc:
        if "no text in the message" in str(exc).lower():
            with suppress(TelegramBadRequest):
                await bot.edit_message_caption(
                    caption=_caption(text),
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                )


async def edit_keyboard(callback: CallbackQuery, markup) -> None:
    if isinstance(callback.message, Message):
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=markup)


async def react(bot: Bot, message: Message, emoji: str) -> None:
    """A reaction on the person's message (👀 while working, 👍 when done): best effort."""
    with suppress(TelegramAPIError):
        await bot.set_message_reaction(
            chat_id=message.chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )


def album_seen(group_id: str | None) -> bool:
    """Whether an earlier photo of this album already reached us: the album is one proof, and
    gets one answer (audit B-6). Checked and marked with no await in between."""
    if not group_id:
        return False
    now = time.monotonic()
    for key, expires in list(_albums.items()):
        if expires < now:
            del _albums[key]
    if group_id in _albums:
        return True
    _albums[group_id] = now + ALBUM_WINDOW
    return False


def done_note(task: Task) -> str:
    """What finishing said (audit B-5): sent for checking is not done."""
    if accepted := task_messages.accepted_note(task):  # accepted at once (PLAN-OWNER §15.3)
        return accepted
    if task.status == Task.Status.REVIEW:
        checkers = queries.reviewers(task)
        if len(checkers) == 1:
            return _("🔎 Sent for checking · %(name)s") % {"name": checkers[0]}
        return _("🔎 Sent for checking")
    return _("Done! 🎉")


def drop_undo_later(task: Task, member: Membership, message: Message) -> None:
    """The Undo button goes once its minute is over: the card is drawn again then."""
    if rules.can_undo(task, member, timezone.now()):
        jobs.refresh_card.apply_async(
            (task.pk, member.pk, message.chat.id, message.message_id),
            countdown=int(rules.UNDO_WINDOW.total_seconds()) + 2,
        )


def _caption(text: str) -> str:
    if len(text) <= CAPTION_LIMIT:
        return text
    # Cut at a line break, so no HTML tag is left open.
    cut = text.rfind("\n", 0, CAPTION_LIMIT - 1)
    return text[: cut if cut > 0 else CAPTION_LIMIT - 1] + "\n…"
