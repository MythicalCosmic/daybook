"""Tasks in the chat: the lists, the card and everything done from it.

One task is one message (research R1 C2, C3): every action edits the card that was tapped.
Done can be undone for a minute (R2 T38); a proof photo is asked for on the card itself and
an album counts once (audit B-6); checklist steps are ticked from the card (X-5); snoozing
offers choices and says the deadline stays (R1 N4); replies to a task message become comments
(R1 Q2); managers act on an escalation from its card (B-9).
"""

from datetime import datetime, timedelta

from aiogram import Bot, F, Router, html
from aiogram.filters import Command, Filter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender
from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.members.bot_messages import MENU_MY_TASKS, MENU_TO_CHECK, BotMessage
from apps.members.models import Membership
from apps.members.scope import branch_ids, restrict
from apps.tasks import bot_messages as task_messages
from apps.tasks import dates, queries, services
from apps.tasks.callbacks import (
    ListCallback,
    PhotoCallback,
    PickCallback,
    ReasonCallback,
    SnoozeCallback,
    StepCallback,
    TaskAction,
    TaskCallback,
    WhenCallback,
)
from apps.tasks.models import Proof, Task
from bot.filters.membership import IsRegistered
from bot.filters.menu import MenuButton
from bot.handlers.member import cards
from bot.handlers.member.cards import Outcome
from bot.states.tasks import (
    BlockTask,
    CommentTask,
    CompleteTask,
    ProofFirst,
    ReturnTask,
    TaskTime,
)
from bot.task_refs import task_id_of_message

router = Router(name="member_tasks")
router.message.filter(IsRegistered())
router.callback_query.filter(IsRegistered())

CANCEL_WORDS = frozenset({"/cancel", "cancel", "bekor", "bekor qilish", "отмена", "отменить"})
IMAGE = F.photo | (F.document & F.document.mime_type.startswith("image/"))
# A captioned hashtag (#xarajat) belongs to another module's photos, never to task proof.
NOT_TAGGED = F.func(lambda message: not (message.caption or "").lstrip().startswith("#"))


# Lists -------------------------------------------------------------------------------------
# Menu buttons come first so they win over whatever the bot was waiting for.


@router.message(Command("tasks"))
@router.message(MenuButton(MENU_MY_TASKS))
async def show_tasks(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _task_list(membership)
    await message.answer(text, reply_markup=markup)


@router.message(Command("check"))
@router.message(MenuButton(MENU_TO_CHECK))
async def show_reviews(message: Message, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _review_list(membership)
    await message.answer(text, reply_markup=markup)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.LIST))
async def back_to_list(callback: CallbackQuery, membership: Membership, state: FSMContext) -> None:
    await state.clear()
    await cards.edit(callback, await _task_list(membership))
    await callback.answer()


@router.callback_query(ListCallback.filter())
async def turn_page(callback: CallbackQuery, callback_data: ListCallback, membership: Membership):
    if callback_data.view == "check":
        message = await _review_list(membership, callback_data.page)
    else:
        message = await _task_list(membership, callback_data.page)
    await cards.edit(callback, message)
    await callback.answer()


@router.callback_query(TaskCallback.filter(F.action == TaskAction.REVIEWS))
async def reviews_from_a_button(callback: CallbackQuery, membership: Membership) -> None:
    await cards.edit(callback, await _review_list(membership))
    await callback.answer()


# Replies to a task message become comments (R1 Q2), unless a conversation waits for text.


class IsTaskReply(Filter):
    """A text reply to one of the bot's task messages: the task it names."""

    async def __call__(self, message: Message, bot: Bot) -> bool | dict:
        replied = message.reply_to_message
        if replied is None or replied.from_user is None or replied.from_user.id != bot.id:
            return False
        if (message.text or "").startswith("/"):
            return False
        task_id = task_id_of_message(replied)
        return {"task_id": task_id} if task_id else False


@router.message(StateFilter(None), F.text, IsTaskReply())
async def reply_comments(message: Message, membership: Membership, task_id: int, bot: Bot):
    alert = await _comment(membership, task_id, message.text)
    await message.answer(alert or _("Comment added."))


# The card ----------------------------------------------------------------------------------


@router.callback_query(TaskCallback.filter(F.action == TaskAction.OPEN))
async def open_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    await cards.show(callback, await cards.card(membership, callback_data.task_id, seen=True))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.BACK))
async def back_to_card(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    await state.clear()
    await cards.show(callback, await cards.card(membership, callback_data.task_id))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.STOP))
async def stop(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    """Cancel: leave whatever the bot was asking for; a card asking for proof is itself again."""
    await state.clear()
    if callback_data.task_id:
        await cards.show(callback, await cards.card(membership, callback_data.task_id))
        return
    await cards.edit(callback, (_("Okay, cancelled."), None))
    await callback.answer()


@router.callback_query(TaskCallback.filter(F.action == TaskAction.START))
async def start_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await cards.act(membership, callback_data.task_id, services.start_task)
    await cards.show(callback, outcome, success=_("Started"))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.DONE))
async def complete_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    await _done(callback, membership, state, callback_data.task_id)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.TICK_ALL))
async def tick_all_and_finish(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    alert = await _tick_all(membership, callback_data.task_id)
    if alert:
        await callback.answer(alert, show_alert=True)
        return
    await _done(callback, membership, state, callback_data.task_id)


async def _done(
    callback: CallbackQuery, membership: Membership, state: FSMContext, task_id: int
) -> None:
    """Done: steps not ticked ask first (X-5); proof is asked for on the card (C3); else done."""
    task = await cards.find(membership, task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    now = timezone.now()
    if task.is_open:
        left = sum(not item.is_done for item in task.checklist.all())
        if left:
            message = await sync_to_async(task_messages.unticked_prompt)(
                task, membership, now, left
            )
            await cards.edit(callback, message)
            await callback.answer()
            return
        if task.proof != Proof.NONE:
            await state.set_state(CompleteTask.proof)
            await state.update_data(
                task_id=task.pk,
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
            )
            message = await sync_to_async(task_messages.proof_prompt)(task, membership, now)
            await cards.edit(callback, message)
            await callback.answer()
            return
    outcome = await cards.act(membership, task_id, services.complete_task)
    note = await sync_to_async(cards.done_note)(outcome.task) if outcome.done else None
    await cards.show(callback, outcome, success=note)
    if outcome.done:
        await sync_to_async(cards.drop_undo_later)(outcome.task, membership, callback.message)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.UNDO))
async def undo(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await cards.act(membership, callback_data.task_id, services.reopen_task)
    await cards.show(callback, outcome, success=_("The task is open again."))


@router.callback_query(StepCallback.filter())
async def tick_step(
    callback: CallbackQuery, callback_data: StepCallback, membership: Membership
) -> None:
    outcome = await _toggle(membership, callback_data.task_id, callback_data.item_id)
    await cards.show(callback, outcome)


# Proof: a photo (or an image sent as a file), or a short report ---------------------------


@router.message(CompleteTask.proof, IMAGE)
async def proof_photo(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    if cards.album_seen(message.media_group_id):
        return  # the album is one proof: its first photo
    data = await state.get_data()
    async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id, initial_sleep=0.5):
        photo = await _download(bot, message)
        outcome = await cards.act(
            membership,
            data["task_id"],
            services.complete_task,
            proof_text=message.caption or "",
            proof_photo=photo,
        )
    await _finish_proof(message, state, outcome, data, bot, membership)


@router.message(CompleteTask.proof, F.text)
async def proof_text(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        outcome = await cards.card(membership, data["task_id"])
        if outcome.message:
            await cards.edit_at(bot, data["chat_id"], data["message_id"], outcome.message)
        await message.answer(_("Okay, cancelled."))
        return
    outcome = await cards.act(
        membership, data["task_id"], services.complete_task, proof_text=message.text
    )
    await _finish_proof(message, state, outcome, data, bot, membership)


@router.message(CompleteTask.proof)
async def proof_expected(message: Message, membership: Membership, state: FSMContext) -> None:
    """Anything else while a proof is awaited gets the same ask again (audit B-6)."""
    task = await cards.find(membership, (await state.get_data())["task_id"])
    if task is None or not task.is_open:
        await state.clear()
        return
    text, _markup = task_messages.proof_request(task)
    await message.answer(text, reply_markup=_stop_on(task))


async def _finish_proof(
    message: Message, state: FSMContext, outcome: Outcome, data: dict, bot: Bot, member
) -> None:
    if outcome.alert and outcome.task is not None and outcome.task.is_open:
        # e.g. a text for a task that needs a photo: keep waiting for one
        await message.answer(outcome.alert, reply_markup=_stop_on(outcome.task))
        return
    await state.clear()
    if outcome.alert:
        await message.answer(outcome.alert)
        return
    # No reaction on the photo: the card above says the proof arrived.
    await cards.edit_at(bot, data["chat_id"], data["message_id"], outcome.message)
    note = await sync_to_async(cards.done_note)(outcome.task)
    if message.message_id != data["message_id"] + 1:
        # The card isn't just above the photo: say where it went, and for which task.
        note = f"<b>{html.quote(note)}</b>\n{html.quote(outcome.task.title)}"
        await message.answer(note, reply_markup=_list_keyboard())
    await sync_to_async(_drop_undo_at)(outcome.task, member, data["chat_id"], data["message_id"])


def _drop_undo_at(task: Task, member: Membership, chat_id: int, message_id: int) -> None:
    from apps.tasks import rules
    from apps.tasks import tasks as jobs

    if rules.can_undo(task, member, timezone.now()):
        jobs.refresh_card.apply_async(
            (task.pk, member.pk, chat_id, message_id),
            countdown=int(rules.UNDO_WINDOW.total_seconds()) + 2,
        )


# A photo that came first (R1 C4): which task is it for? ------------------------------------


@router.message(StateFilter(None), IMAGE, NOT_TAGGED)
async def photo_first(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    if cards.album_seen(message.media_group_id):
        return
    tasks = await _photo_tasks(membership)
    if not tasks:
        await message.answer(_("No task is waiting for a photo right now."))
        return
    file = message.photo[-1] if message.photo else message.document
    await state.set_state(ProofFirst.pick)
    await state.update_data(file_id=file.file_id, caption=message.caption or "")
    text, markup = await sync_to_async(task_messages.which_photo_task)(tasks, timezone.now())
    await message.answer(text, reply_markup=markup)


@router.callback_query(ProofFirst.pick, PhotoCallback.filter())
async def photo_for_task(
    callback: CallbackQuery,
    callback_data: PhotoCallback,
    membership: Membership,
    state: FSMContext,
    bot: Bot,
) -> None:
    data = await state.get_data()
    await state.clear()
    if not callback_data.task_id:
        await cards.edit(callback, (_("Okay, no task."), None))
        await callback.answer()
        return
    downloaded = await bot.download(data["file_id"])
    photo = ContentFile(downloaded.getvalue(), name="proof.jpg")
    outcome = await cards.act(
        membership,
        callback_data.task_id,
        services.complete_task,
        proof_text=data.get("caption", ""),
        proof_photo=photo,
    )
    note = await sync_to_async(cards.done_note)(outcome.task) if outcome.done else None
    await cards.show(callback, outcome, success=note)


@router.callback_query(PhotoCallback.filter())
async def photo_question_expired(callback: CallbackQuery) -> None:
    await callback.answer(_("Send the photo again, please."), show_alert=True)


# Snooze ------------------------------------------------------------------------------------


@router.callback_query(TaskCallback.filter(F.action == TaskAction.SNOOZE_MENU))
async def snooze_choices(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    keyboard = await sync_to_async(task_messages.snooze_keyboard)(task, membership)
    await cards.edit_keyboard(callback, keyboard)
    await callback.answer()


@router.callback_query(SnoozeCallback.filter())
async def snooze_with_choice(
    callback: CallbackQuery, callback_data: SnoozeCallback, membership: Membership
) -> None:
    outcome = await cards.act(
        membership, callback_data.task_id, services.snooze_task, preset=callback_data.preset
    )
    note = await sync_to_async(task_messages.snoozed_note)(outcome.task) if outcome.done else None
    await cards.show(callback, outcome, success=note)


@router.callback_query(TaskCallback.filter(F.action == TaskAction.SNOOZE))
async def snooze_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    """The policy's own length: the button of reminders sent before snooze choices."""
    outcome = await cards.act(membership, callback_data.task_id, services.snooze_task)
    note = await sync_to_async(task_messages.snoozed_note)(outcome.task) if outcome.done else None
    await cards.show(callback, outcome, success=note)


# Comments ----------------------------------------------------------------------------------


@router.callback_query(TaskCallback.filter(F.action == TaskAction.COMMENT))
async def ask_comment(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    await state.set_state(CommentTask.text)
    await state.update_data(task_id=task.pk)
    text, markup = task_messages.comment_prompt(task)
    await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.message(CommentTask.text, F.text)
async def write_comment(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    task_id = (await state.get_data())["task_id"]
    await state.clear()
    if message.text.strip().lower() in CANCEL_WORDS:
        await message.answer(_("Okay, cancelled."))
        return
    alert = await _comment(membership, task_id, message.text)
    await message.answer(alert or _("Comment added."))


# Checking: accept, or send back with a reason (R1 C8) -------------------------------------


async def _checked(outcome: Outcome, membership: Membership) -> Outcome:
    """After a check the checker's message keeps saying what happened above the card
    ("Accepted · Name", "Sent back"), as the copy the backend refreshed a moment earlier
    does; the plain card would drop it."""
    if outcome.done and outcome.message is not None:
        outcome.message = await sync_to_async(task_messages.copy_of)(
            outcome.task, membership, "review", timezone.now()
        )
    return outcome


@router.callback_query(TaskCallback.filter(F.action == TaskAction.CONFIRM))
async def confirm_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await cards.act(membership, callback_data.task_id, services.confirm_task)
    await cards.show(callback, await _checked(outcome, membership), success=_("Confirmed"))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.RETURN))
async def ask_return_reason(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    if task.status != Task.Status.REVIEW:
        await cards.show(callback, await cards.card(membership, task.pk))
        return
    await state.set_state(ReturnTask.reason)
    await state.update_data(
        task_id=task.pk, chat_id=callback.message.chat.id, message_id=callback.message.message_id
    )
    message = await sync_to_async(task_messages.return_prompt)(task, membership, timezone.now())
    await cards.edit(callback, message)
    await callback.answer()


@router.callback_query(ReasonCallback.filter(F.kind == "return"))
async def send_back_with_a_reason(
    callback: CallbackQuery,
    callback_data: ReasonCallback,
    membership: Membership,
    state: FSMContext,
) -> None:
    await state.clear()
    reasons = dict(task_messages.return_reasons())
    reason = reasons.get(callback_data.code, "")
    outcome = await cards.act(
        membership, callback_data.task_id, services.return_task, reason=reason
    )
    outcome = await _checked(outcome, membership)
    await cards.show(callback, outcome, success=_("Sent back with your comment."))


@router.message(ReturnTask.reason, F.text)
async def send_back(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if message.text.strip().lower() in CANCEL_WORDS:
        outcome = await cards.card(membership, data["task_id"])
        if outcome.message and "message_id" in data:
            await cards.edit_at(bot, data["chat_id"], data["message_id"], outcome.message)
        await message.answer(_("Okay, cancelled."))
        return
    outcome = await cards.act(
        membership, data["task_id"], services.return_task, reason=message.text
    )
    if outcome.alert:
        await message.answer(outcome.alert)
        return
    outcome = await _checked(outcome, membership)
    if outcome.message and "message_id" in data:
        await cards.edit_at(bot, data["chat_id"], data["message_id"], outcome.message)
    await message.answer(_("Sent back with your comment."))


# "Can't do it" and "Need more time" (R2 T57, T17) -----------------------------------------


@router.callback_query(TaskCallback.filter(F.action == TaskAction.BLOCK))
async def block_reasons(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    await cards.edit_keyboard(callback, task_messages.block_keyboard(task))
    await callback.answer(_("Why can't it be done?"))


@router.callback_query(ReasonCallback.filter(F.kind == "block"))
async def block_with_reason(
    callback: CallbackQuery,
    callback_data: ReasonCallback,
    membership: Membership,
    state: FSMContext,
) -> None:
    if callback_data.code == Task.Blocker.OTHER:
        await state.set_state(BlockTask.note)
        await state.update_data(
            task_id=callback_data.task_id,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )
        await callback.message.answer(
            _("What's in the way? Write a few words."),
            reply_markup=task_messages.stop_keyboard(placeholder=True),
        )
        await callback.answer()
        return
    outcome = await cards.act(
        membership, callback_data.task_id, services.report_blocker, reason_code=callback_data.code
    )
    await cards.show(callback, outcome, success=_("Sent. Reminders wait until someone decides."))


@router.message(BlockTask.note, F.text)
async def block_with_note(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    if message.text.strip().lower() in CANCEL_WORDS:
        await message.answer(_("Okay, cancelled."))
        return
    outcome = await cards.act(
        membership,
        data["task_id"],
        services.report_blocker,
        reason_code=Task.Blocker.OTHER,
        note=message.text,
    )
    if outcome.alert:
        await message.answer(outcome.alert)
        return
    await cards.edit_at(bot, data["chat_id"], data["message_id"], outcome.message)
    await message.answer(_("Sent. Reminders wait until someone decides."))


@router.callback_query(
    TaskCallback.filter(F.action.in_({TaskAction.MORE_TIME, TaskAction.NEW_DUE}))
)
async def time_choices(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership, state: FSMContext
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    kind = "more" if callback_data.action == TaskAction.MORE_TIME else "due"
    keyboard = await sync_to_async(task_messages.when_keyboard)(task, kind, timezone.now())
    await cards.edit_keyboard(callback, keyboard)
    # A time typed while the choices show ("ertaga 10:00") is read too, not only after "Type a
    # time".
    await state.set_state(TaskTime.typed)
    await state.update_data(
        kind=kind,
        task_id=task.pk,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        via="choices",
    )
    await callback.answer()


@router.callback_query(WhenCallback.filter())
async def time_chosen(
    callback: CallbackQuery,
    callback_data: WhenCallback,
    membership: Membership,
    state: FSMContext,
) -> None:
    if callback_data.choice == "type":
        await state.set_state(TaskTime.typed)
        await state.update_data(
            kind=callback_data.kind,
            task_id=callback_data.task_id,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            via="asked",
        )
        text, markup = task_messages.ask_typed_time(callback_data.kind)
        await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    if await state.get_state() == TaskTime.typed.state:
        await state.clear()
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    moment = _chosen_moment(task, callback_data.kind, callback_data.choice, membership)
    outcome = await _set_time(membership, task.pk, callback_data.kind, moment)
    await cards.show(callback, outcome, success=_time_note(callback_data.kind))


@router.message(TaskTime.typed, F.text)
async def time_typed(message: Message, membership: Membership, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if message.text.strip().lower() in CANCEL_WORDS:
        await state.clear()
        await message.answer(_("Okay, cancelled."))
        return
    found = dates.read_when(message.text, now=cards.local_now(membership))
    if found.title or found.due_at is None:
        if data.get("via") == "choices":
            # Nobody asked them to type a time (the choices were left alone): it's anything
            # else they meant, e.g. a new task, so it gets the usual answer.
            from bot.handlers.member import home

            await state.clear()
            if reply := await IsTaskReply()(message, bot):
                await reply_comments(message, membership, reply["task_id"], bot)
            else:
                await home.plain_text(message, membership, state, bot)
            return
        text, markup = task_messages.ask_typed_time(data["kind"])
        await message.answer(_("I didn't catch the time.") + "\n" + text, reply_markup=markup)
        return
    await state.clear()
    outcome = await _set_time(membership, data["task_id"], data["kind"], found.due_at)
    if outcome.alert:
        await message.answer(outcome.alert)
        return
    await cards.edit_at(bot, data["chat_id"], data["message_id"], outcome.message)
    await message.answer(_time_note(data["kind"]))


def _chosen_moment(task: Task, kind: str, choice: str, membership: Membership) -> datetime:
    now = cards.local_now(membership)
    start = max(task.due_at, now) if (kind == "more" and task.due_at) else now
    if choice == "30m":
        return start + timedelta(minutes=30)
    if choice == "1h":
        return start + timedelta(hours=1)
    if choice == "today":
        return datetime.combine(now.date(), dates.EVENING, tzinfo=now.tzinfo)
    return dates.tomorrow_morning(now)


def _time_note(kind: str) -> str:
    if kind == "more":
        return _("Asked for more time. The answer comes here.")
    return _("New deadline set.")


# Managers on a card (audit B-9): remind now, someone else, cancel -------------------------


@router.callback_query(TaskCallback.filter(F.action == TaskAction.NUDGE))
async def nudge(callback: CallbackQuery, callback_data: TaskCallback, membership: Membership):
    outcome = await cards.act(membership, callback_data.task_id, services.nudge)
    await cards.show(callback, outcome, success=_("Reminder sent."))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.REASSIGN))
async def pick_someone_else(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    people = await _colleagues(membership, exclude=task.assignee_id)
    keyboard = task_messages.person_picker(people, task_id=task.pk)
    await cards.edit_keyboard(callback, keyboard)
    await callback.answer(task_messages.ask_assignee())


@router.callback_query(PickCallback.filter(F.task_id > 0))
async def someone_else_picked(
    callback: CallbackQuery, callback_data: PickCallback, membership: Membership
) -> None:
    if callback_data.member_id < 0:  # turning the list's pages
        task = await cards.find(membership, callback_data.task_id)
        if task is not None:
            people = await _colleagues(membership, exclude=task.assignee_id)
            keyboard = task_messages.person_picker(people, task_id=task.pk, page=callback_data.page)
            await cards.edit_keyboard(callback, keyboard)
        await callback.answer()
        return
    outcome = await _give_to(membership, callback_data.task_id, callback_data.member_id)
    await cards.show(callback, outcome, success=_("Given to someone else."))


@router.callback_query(TaskCallback.filter(F.action == TaskAction.CANCEL))
async def ask_cancel(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    task = await cards.find(membership, callback_data.task_id)
    if task is None:
        await callback.answer(cards.gone(), show_alert=True)
        return
    await cards.edit_keyboard(callback, task_messages.cancel_keyboard(task))
    await callback.answer()


@router.callback_query(TaskCallback.filter(F.action == TaskAction.CANCEL_YES))
async def cancel_task(
    callback: CallbackQuery, callback_data: TaskCallback, membership: Membership
) -> None:
    outcome = await _cancel(membership, callback_data.task_id)
    await cards.show(callback, outcome, success=_("Task cancelled."))


# Helpers -----------------------------------------------------------------------------------


def _stop_on(task: Task):
    return task_messages.InlineKeyboardMarkup(
        inline_keyboard=[[task_messages._button(_("Cancel"), TaskAction.STOP, task.pk)]]
    )


def _list_keyboard():
    return task_messages.InlineKeyboardMarkup(
        inline_keyboard=[[task_messages.list_button(_("My tasks"))]]
    )


async def _download(bot: Bot, message: Message) -> ContentFile:
    file = message.photo[-1] if message.photo else message.document
    downloaded = await bot.download(file)
    return ContentFile(downloaded.getvalue(), name="proof.jpg")


@sync_to_async
def _task_list(member: Membership, page: int = 0) -> BotMessage:
    now = timezone.now()
    tasks = list(queries.open_work(member).prefetch_related("checklist"))
    reviews = queries.awaiting_review_by(member).count()
    return task_messages.task_list(tasks, now, page=page, reviews=reviews)


@sync_to_async
def _review_list(member: Membership, page: int = 0) -> BotMessage:
    tasks = list(queries.awaiting_review_by(member).prefetch_related("checklist"))
    return task_messages.review_list(tasks, timezone.now(), page=page)


@sync_to_async
def _photo_tasks(member: Membership) -> list[Task]:
    """Open tasks of theirs that need a photo, the soonest first (up to five)."""
    tasks = (
        queries.open_work(member)
        .filter(status__in=Task.OPEN_STATUSES, proof__in=(Proof.PHOTO, Proof.ANY))
        .order_by("due_at", "pk")
    )
    return list(tasks[:5])


@sync_to_async
def _toggle(member: Membership, task_id: int, item_id: int) -> Outcome:
    task = cards.visible(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=cards.gone())
    item = task.checklist.filter(pk=item_id).first()
    alert = None
    if item is not None:
        try:
            services.toggle_checklist_item(item, by=member, done=not item.is_done)
        except (DomainError, PermissionDenied) as exc:
            alert = str(exc)
    task = cards.load(member, task_id)
    return Outcome(
        message=task_messages.task_card(task, member, timezone.now()), alert=alert, task=task
    )


@sync_to_async
def _tick_all(member: Membership, task_id: int) -> str | None:
    task = cards.visible(member).filter(pk=task_id).first()
    if task is None:
        return cards.gone()
    try:
        for item in task.checklist.filter(is_done=False):
            services.toggle_checklist_item(item, by=member, done=True)
    except (DomainError, PermissionDenied) as exc:
        return str(exc)
    return None


@sync_to_async
def _comment(member: Membership, task_id: int, text: str) -> str | None:
    task = cards.visible(member).filter(pk=task_id).first()
    if task is None:
        return cards.gone()
    try:
        services.add_comment(task, by=member, text=text)
    except (DomainError, PermissionDenied) as exc:
        return str(exc)
    return None


@sync_to_async
def _set_time(member: Membership, task_id: int, kind: str, moment: datetime) -> Outcome:
    """More time asked (the assignee), or a new deadline (a manager; it also answers a "can't do
    it" waiting for one)."""
    task = cards.visible(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=cards.gone())

    def apply(task: Task, *, by: Membership) -> None:
        if kind == "more":
            services.request_extension(task, by=by, until=moment)
        elif task.blocked_at is not None:
            services.resolve_blocker(task, by=by, action="new_due", due_at=moment)
        else:
            services.update_task(task, by=by, due_at=moment)

    return cards.act_now(member, task_id, apply)


@sync_to_async
def _give_to(member: Membership, task_id: int, member_id: int) -> Outcome:
    task = cards.visible(member).filter(pk=task_id).first()
    if task is None:
        return Outcome(alert=cards.gone())

    def apply(task: Task, *, by: Membership) -> None:
        if task.blocked_at is not None:
            services.resolve_blocker(task, by=by, action="reassign", assignee_id=member_id)
            return
        person = (
            Membership.objects.for_company(by.company_id)
            .select_related("user", "company", "role")
            .filter(pk=member_id)
            .first()
        )
        if person is None:
            raise DomainError(_("That person isn't in your company."))
        services.reassign_task(task, by=by, assignee=person)

    return cards.act_now(member, task_id, apply)


@sync_to_async
def _cancel(member: Membership, task_id: int) -> Outcome:
    def apply(task: Task, *, by: Membership) -> None:
        if task.blocked_at is not None:
            services.resolve_blocker(task, by=by, action="cancel")
        else:
            services.cancel_task(task, by=by)

    return cards.act_now(member, task_id, apply)


@sync_to_async
def _colleagues(member: Membership, *, exclude: int | None = None) -> list[Membership]:
    """Registered people the member may give work to: their branch scope, by name."""
    people = restrict(
        Membership.objects.for_company(member.company_id).filter(
            status=Membership.Status.APPROVED, onboarded_at__isnull=False
        ),
        branch_ids(member),
        field="branches",
    ).select_related("user", "position")
    found = [person for person in people if person.pk not in (member.pk, exclude)]
    return sorted(found, key=lambda person: str(person).lower())
