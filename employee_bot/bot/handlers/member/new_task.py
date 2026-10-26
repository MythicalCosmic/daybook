"""New task in the chat (the menu's plus button).

The title can carry its deadline ("Kassani sanash ertaga 18:00", research R2 T1): the bot
reads it with the quick-add parser and shows what it understood, with the weekday and the date,
before saving, and "Not a date" keeps the words as typed (T2). Without a date it asks, with
presets, and a typed answer goes through the same parser (B-3). Whoever may give work picks who
it's for first, themselves at the top (audit X-7).
"""

from contextlib import suppress
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members import departments
from apps.members.bot_messages import MENU_NEW_TASK, BotMessage
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks import bot_messages as task_messages
from apps.tasks import dates, quickadd, services
from apps.tasks.callbacks import (
    DueCallback,
    DuePreset,
    PickCallback,
    QuickAddCallback,
    TaskAction,
    TaskCallback,
)
from apps.tasks.models import Repeat, Task
from bot.filters.membership import IsRegistered
from bot.filters.menu import MenuButton
from bot.handlers.member import cards
from bot.handlers.member.tasks import CANCEL_WORDS, _colleagues
from bot.states.tasks import NewTask

router = Router(name="member_new_task")
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())

TITLE_MAX = 200


@router.message(Command("new"))
@router.message(MenuButton(MENU_NEW_TASK))
async def new_task(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewTask.title)
    text, markup = task_messages.ask_title()
    await message.answer(text, reply_markup=markup)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.NEW))
async def new_task_from_a_list(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(NewTask.title)
    text, markup = task_messages.ask_title()
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.message(NewTask.title, F.text)
async def got_title(message: Message, membership: Membership, state: FSMContext) -> None:
    raw = message.text.strip()
    if raw.lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer(_("Okay, cancelled."))
        return
    if raw.startswith("/"):
        await message.answer(_("Send the task's title, or tap «Cancel»."))
        return
    found = quickadd.parse(raw, now=cards.local_now(membership), lang=translation.get_language())
    data = await state.get_data()
    update: dict = {"raw": raw[:TITLE_MAX], "found": found.found or bool(data.get("found"))}
    if found.due_at is not None:
        update["due"] = found.due_at.isoformat()
    elif found.past and found.passed is not None:
        update["passed"] = found.passed.isoformat()
    if found.repeat:
        update["repeat"] = found.repeat
    if found.priority:
        update["urgent"] = True
    title = found.title
    if not title:  # only a time: keep it, and ask what is to be done
        await state.update_data(**update)
        await message.answer(_("And what needs to be done?"), reply_markup=_cancel())
        return
    update["title"] = title[:TITLE_MAX]
    if len(title) > TITLE_MAX:
        update["note"] = _("The title was cut to 200 characters.")
    await state.update_data(**update)
    if membership.has_perm(Perm.TASKS_ASSIGN) or await sync_to_async(departments.leads)(
        membership
    ):  # a head gives work to their people
        await _ask_assignee(message, membership, state)
        return
    await _next(message, membership, state, edit=False)


@router.message(NewTask.title)
async def title_expected(message: Message) -> None:
    """A photo or a sticker while the title is awaited: ask again (audit B-10)."""
    await message.answer(_("Send the task's title, or tap «Cancel»."), reply_markup=_cancel())


async def _ask_assignee(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.set_state(NewTask.assignee)
    people = await _colleagues(membership)
    markup = task_messages.person_picker(people, me=True)
    await message.answer(task_messages.ask_assignee(), reply_markup=markup)


@router.callback_query(NewTask.assignee, PickCallback.filter(F.task_id == 0))
async def got_assignee(
    callback: CallbackQuery, callback_data: PickCallback, membership: Membership, state: FSMContext
) -> None:
    if callback_data.member_id < 0:  # turning the list's pages
        people = await _colleagues(membership)
        markup = task_messages.person_picker(people, me=True, page=callback_data.page)
        await cards.edit_keyboard(callback, markup)
        await callback.answer()
        return
    await state.update_data(assignee_id=callback_data.member_id or None)
    await callback.answer()
    await _next(callback.message, membership, state, edit=True)


async def _next(target: Message, membership: Membership, state: FSMContext, *, edit: bool):
    """After the title (and who it's for): the preview when a deadline was read, "it has passed,
    tomorrow?" for a past one, else the deadline question."""
    data = await state.get_data()
    if "due" in data:
        await _preview(target, membership, state, edit=edit)
    elif data.get("passed"):
        await state.set_state(NewTask.due)
        await _say(target, _passed_message(data, membership), edit=edit)
    else:
        await state.set_state(NewTask.due)
        message = await sync_to_async(task_messages.ask_due)(membership.company, timezone.now())
        await _say(target, message, edit=edit)


@router.callback_query(NewTask.due, DueCallback.filter())
async def due_preset(
    callback: CallbackQuery, callback_data: DueCallback, membership: Membership, state: FSMContext
) -> None:
    due = dates.resolve_preset(callback_data.preset, now=cards.local_now(membership))
    await state.update_data(due=due.isoformat() if due else None)
    if callback_data.preset == DuePreset.NONE:
        await state.update_data(repeat=None)  # a repeat needs a time
    await callback.answer()
    await _preview(callback.message, membership, state, edit=True)


@router.message(NewTask.due, F.text)
async def due_typed(message: Message, membership: Membership, state: FSMContext) -> None:
    text = message.text.strip()
    if text.lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer(_("Okay, cancelled."))
        return
    found = dates.read_when(text, now=cards.local_now(membership))
    if found.past and found.passed is not None and not found.title:
        await state.update_data(passed=found.passed.isoformat())
        text, markup = _passed_message(await state.get_data(), membership)
        await message.answer(text, reply_markup=markup)
        return
    if found.title or found.due_at is None:
        # The presets and Cancel again with every miss (audit B-3).
        text, markup = await sync_to_async(task_messages.ask_due)(
            membership.company, timezone.now(), error=True
        )
        await message.answer(text, reply_markup=markup)
        return
    update = {"due": found.due_at.isoformat()}
    if found.repeat:
        update["repeat"] = found.repeat
    await state.update_data(**update)
    await _preview(message, membership, state, edit=False)


@router.callback_query(QuickAddCallback.filter())
async def preview_button(
    callback: CallbackQuery,
    callback_data: QuickAddCallback,
    membership: Membership,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    if "title" not in data:  # an old preview, its conversation gone
        await callback.answer(_("Start again with «New task»."), show_alert=True)
        return
    action = callback_data.action
    if action == "save":
        await _save(callback, membership, state, data)
        return
    if action == "tomorrow" and data.get("passed"):
        passed = datetime.fromisoformat(data["passed"])
        await state.update_data(due=(passed + timedelta(days=1)).isoformat(), passed=None)
        await callback.answer()
        await _preview(callback.message, membership, state, edit=True)
        return
    if action == "literal":
        # "Not a date": the words stay in the title as typed, and the deadline is asked for.
        data.update(title=data.get("raw") or data["title"], repeat=None, urgent=False)
    data.pop("due", None)
    data.pop("passed", None)
    await state.set_data(data)
    await state.set_state(NewTask.due)
    message = await sync_to_async(task_messages.ask_due)(membership.company, timezone.now())
    await cards.edit(callback, message)
    await callback.answer()


async def _save(callback: CallbackQuery, membership: Membership, state: FSMContext, data: dict):
    outcome, header = await _create(membership, data)
    if outcome.alert:
        await callback.answer(outcome.alert[:200], show_alert=True)
        await state.set_state(NewTask.due)
        message = await sync_to_async(task_messages.ask_due)(membership.company, timezone.now())
        await cards.edit(callback, message)
        return
    await state.clear()
    text, markup = outcome.message
    await cards.edit(callback, (f"{header}\n\n{text}", markup))
    await callback.answer()


async def _preview(target: Message, membership: Membership, state: FSMContext, *, edit: bool):
    await state.set_state(NewTask.confirm)
    data = await state.get_data()
    message = await sync_to_async(_preview_message)(membership, data)
    await _say(target, message, edit=edit)


def _preview_message(membership: Membership, data: dict) -> BotMessage:
    now = cards.local_now(membership)
    due = _local(data.get("due"), now)
    label = dates.due_label(due, now, translation.get_language()) if due else None
    assignee = None
    if data.get("assignee_id"):
        person = Membership.objects.filter(pk=data["assignee_id"]).select_related("user").first()
        assignee = str(person) if person else None
    repeat = data.get("repeat") if not data.get("assignee_id") and due else None
    return task_messages.quick_add_preview(
        data["title"],
        label,
        found=bool(data.get("found")),
        assignee=assignee,
        repeat=Repeat(repeat).label if repeat else None,
        urgent=bool(data.get("urgent")),
        note=data.get("note", ""),
    )


def _passed_message(data: dict, membership: Membership) -> BotMessage:
    passed = _local(data["passed"], cards.local_now(membership))
    return task_messages.due_passed(f"{passed:%H:%M}")


@sync_to_async
def _create(member: Membership, data: dict) -> tuple[cards.Outcome, str]:
    assignee = None
    if data.get("assignee_id"):
        assignee = (
            Membership.objects.for_company(member.company_id)
            .select_related("user", "role", "company")
            .filter(pk=data["assignee_id"])
            .first()
        )
        if assignee is None:
            return cards.Outcome(alert=_("That person isn't in your company.")), ""
    due = datetime.fromisoformat(data["due"]) if data.get("due") else None
    repeat = data.get("repeat") if assignee is None and due is not None else None
    try:
        task = services.create_task(
            by=member,
            title=data["title"],
            due_at=due,
            assignee=assignee,
            priority=Task.Priority.URGENT if data.get("urgent") else Task.Priority.NORMAL,
            repeat=repeat or Repeat.NONE,
        )
    except (DomainError, PermissionDenied) as exc:
        return cards.Outcome(alert=str(exc)), ""
    task = cards.load(member, task.pk)
    message = task_messages.task_card(task, member, timezone.now())
    if assignee is not None and assignee.pk != member.pk:
        header = _("Sent. For: %(name)s") % {"name": assignee}
    else:
        header = _("Added to your list.")
    return cards.Outcome(message=message, task=task), header


def _local(value: str | None, now: datetime) -> datetime | None:
    if not value:
        return None
    return timezone.localtime(datetime.fromisoformat(value), now.tzinfo)


def _cancel():
    return task_messages.stop_keyboard(placeholder=True)


async def _say(target: Message, message: BotMessage, *, edit: bool) -> None:
    text, markup = message
    if edit:
        with suppress(TelegramBadRequest):
            await target.edit_text(text, reply_markup=markup)
            return
    await target.answer(text, reply_markup=markup)
