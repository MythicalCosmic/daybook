from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members.bot_messages import MENU_MY_TASKS, MENU_NEW_TASK, BotMessage
from apps.members.models import Membership
from apps.tasks import bot_messages as task_messages
from apps.tasks import queries, rules, services
from apps.tasks.callbacks import DueCallback, TaskAction, TaskCallback
from apps.tasks.dates import parse_due, resolve_preset
from apps.tasks.models import Proof, Task
from bot.filters.membership import IsRegistered
from bot.filters.menu import MenuButton
from bot.states.tasks import CompleteTask, NewTask, ReturnTask

router = Router(name="member_tasks")
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())


@dataclass
class Outcome:
    """What a task action produced: the refreshed card, and an alert if it didn't go through."""

    message: BotMessage | None = None
    alert: str | None = None
    task: Task | None = None


# Menu buttons come first so they win over whatever the bot was waiting for.


@router.message(Command("tasks"))
@router.message(MenuButton(MENU_MY_TASKS))
async def show_tasks(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _task_list(membership)
    await message.answer(text, reply_markup=markup)


@router.message(Command("new"))
@router.message(MenuButton(MENU_NEW_TASK))
async def new_task(message: Message, state: FSMContext) -> None:
    await state.set_state(NewTask.title)
    text, markup = task_messages.ask_title()
    await message.answer(text, reply_markup=markup)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.STOP))
async def stop(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(callback, (_("Okay, cancelled."), None))
    await callback.answer()


@router.callback_query(TaskCallback.filter(F.action == TaskAction.LIST))
async def back_to_list(callback: CallbackQuery, membership: Membership) -> None:
    await _edit(callback, await _task_list(membership))
    await callback.answer()


@router.callback_query(TaskCallback.filter(F.action == TaskAction.OPEN))
async def open_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    await _show(callback, await _card(membership, callback_data.task_id))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.START))
async def start_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await _act(membership, callback_data.task_id, services.start_task)
    await _show(callback, outcome, success=_("Started 💪"))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.DONE))
async def complete_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    task = await _find(membership, callback_data.task_id)
    if task is not None and task.is_open and task.proof != Proof.NONE:
        await state.set_state(CompleteTask.proof)
        await state.update_data(task_id=task.pk)
        text, markup = task_messages.proof_request(task)
        await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    outcome = await _act(membership, callback_data.task_id, services.complete_task)
    await _show(callback, outcome, success=_("Done! 🎉"))


@router.message(CompleteTask.proof, F.photo)
async def proof_photo(
    message: Message, membership: Membership, state: FSMContext, bot: Bot
) -> None:
    task_id = (await state.get_data())["task_id"]
    downloaded = await bot.download(message.photo[-1])
    photo = ContentFile(downloaded.getvalue(), name="proof.jpg")
    outcome = await _act(
        membership,
        task_id,
        services.complete_task,
        proof_text=message.caption or "",
        proof_photo=photo,
    )
    await _finish_proof(message, state, outcome)


@router.message(CompleteTask.proof, F.text)
async def proof_text(message: Message, membership: Membership, state: FSMContext) -> None:
    task_id = (await state.get_data())["task_id"]
    outcome = await _act(membership, task_id, services.complete_task, proof_text=message.text)
    await _finish_proof(message, state, outcome)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.SNOOZE))
async def snooze_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await _act(membership, callback_data.task_id, services.snooze_task)
    success = None
    if outcome.task is not None and outcome.task.snoozed_until is not None:
        until = timezone.localtime(
            outcome.task.snoozed_until, ZoneInfo(membership.company.timezone)
        )
        success = _("Snoozed until %(time)s.") % {"time": until.strftime("%H:%M")}
    await _show(callback, outcome, success=success)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.CONFIRM))
async def confirm_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await _act(membership, callback_data.task_id, services.confirm_task)
    await _show(callback, outcome, success=_("Confirmed 👍"))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.RETURN))
async def ask_return_reason(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    task = await _find(membership, callback_data.task_id)
    if task is None or task.status != Task.Status.REVIEW or not rules.can_review(task, membership):
        await callback.answer(_("This task isn't waiting for your confirmation."), show_alert=True)
        return
    await state.set_state(ReturnTask.reason)
    await state.update_data(task_id=task.pk)
    text, markup = task_messages.return_reason_request()
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.message(ReturnTask.reason, F.text)
async def send_back(message: Message, membership: Membership, state: FSMContext) -> None:
    task_id = (await state.get_data())["task_id"]
    outcome = await _act(membership, task_id, services.return_task, reason=message.text)
    await state.clear()
    await message.answer(outcome.alert or _("↩️ Sent back with your comment."))


@router.message(NewTask.title, F.text)
async def new_task_title(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip()[:200])
    await state.set_state(NewTask.due)
    text, markup = task_messages.ask_due(membership.company, timezone.now())
    await message.answer(text, reply_markup=markup)


@router.callback_query(NewTask.due, DueCallback.filter())
async def new_task_due_preset(
    callback: CallbackQuery, callback_data: DueCallback, membership: Membership, state: FSMContext
) -> None:
    due_at = resolve_preset(callback_data.preset, now=_local_now(membership))
    await _create_personal(callback.message, membership, state, due_at)
    await callback.answer()


@router.message(NewTask.due, F.text)
async def new_task_due_typed(message: Message, membership: Membership, state: FSMContext) -> None:
    due_at = parse_due(message.text, now=_local_now(membership))
    if due_at is None:
        await message.answer(_("I didn't get that. Send a time like 18:30 or 25.10 18:30."))
        return
    await _create_personal(message, membership, state, due_at)


async def _create_personal(
    message: Message, membership: Membership, state: FSMContext, due_at: datetime | None
) -> None:
    title = (await state.get_data())["title"]
    await state.clear()
    outcome = await _create(membership, title, due_at)
    if outcome.alert:
        await message.answer(outcome.alert)
        return
    text, markup = outcome.message
    await message.answer(f"{_('✅ Added to your list.')}\n\n{text}", reply_markup=markup)


async def _finish_proof(message: Message, state: FSMContext, outcome: Outcome) -> None:
    if outcome.alert and outcome.task is not None and outcome.task.is_open:
        await message.answer(outcome.alert)  # e.g. it needs a photo: keep waiting for one
        return
    await state.clear()
    if outcome.alert:
        await message.answer(outcome.alert)
        return
    text, markup = outcome.message
    await message.answer(f"{_('Done! 🎉')}\n\n{text}", reply_markup=markup)


async def _show(callback: CallbackQuery, outcome: Outcome, success: str | None = None) -> None:
    if outcome.message is not None:
        await _edit(callback, outcome.message)
    if outcome.alert:
        await callback.answer(outcome.alert, show_alert=True)
    else:
        await callback.answer(success)


async def _edit(callback: CallbackQuery, message: BotMessage) -> None:
    if not isinstance(callback.message, Message):
        return
    text, markup = message
    with suppress(TelegramBadRequest):  # unchanged, or too old to edit
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await callback.message.edit_text(text, reply_markup=markup)


def _local_now(membership: Membership) -> datetime:
    return timezone.localtime(timezone.now(), ZoneInfo(membership.company.timezone))


def _with_checklist(member: Membership):
    return queries.visible_tasks(member).prefetch_related("checklist")


@sync_to_async
def _task_list(member: Membership) -> BotMessage:
    now = timezone.now()
    tasks = list(queries.open_work(member).prefetch_related("checklist"))
    reviews = queries.awaiting_review_by(member).count()
    return task_messages.task_list(tasks, now, reviews=reviews)


@sync_to_async
def _find(member: Membership, task_id: int) -> Task | None:
    return _with_checklist(member).filter(pk=task_id).first()


@sync_to_async
def _card(member: Membership, task_id: int) -> Outcome:
    task = _with_checklist(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=_("This task no longer exists."))
    return Outcome(message=task_messages.task_card(task, member, timezone.now()), task=task)


@sync_to_async
def _act(member: Membership, task_id: int, action, **kwargs) -> Outcome:
    task = queries.visible_tasks(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=_("This task no longer exists."))
    alert = None
    try:
        action(task, by=member, **kwargs)
    except (DomainError, PermissionDenied) as exc:
        alert = str(exc)
    task = _with_checklist(member).get(pk=task_id)
    card = task_messages.task_card(task, member, timezone.now())
    return Outcome(message=card, alert=alert, task=task)


@sync_to_async
def _create(member: Membership, title: str, due_at: datetime | None) -> Outcome:
    try:
        task = services.create_task(by=member, title=title, due_at=due_at)
    except (DomainError, PermissionDenied) as exc:
        return Outcome(alert=str(exc))
    task = _with_checklist(member).get(pk=task.pk)
    return Outcome(message=task_messages.task_card(task, member, timezone.now()), task=task)
