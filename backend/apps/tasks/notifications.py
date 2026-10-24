from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta

from aiogram.exceptions import TelegramAPIError
from django.utils import timezone, translation

from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.notifications import telegram
from apps.notifications.tasks import edit_telegram_message, send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.tasks import bot_messages
from apps.tasks.models import Task, TaskComment, TaskMessage
from apps.tasks.queries import TASK_RELATIONS, reviewers


def send_task_assigned(task_id: int) -> None:
    task = _load(task_id)
    if task is None or not task.is_open:
        return
    _send(task.assignee, bot_messages.task_assigned, task, timezone.now(), about=task)


def send_task_completed(task_id: int, completed_at: str | None = None) -> None:
    """Tell the reviewer (or whoever gave it). Queued after the undo window with the completion
    it was for: a Done taken back, or done again since, sends nothing from here."""
    task = _load(task_id)
    if task is None:
        return
    if completed_at is not None and task.completed_at != datetime.fromisoformat(completed_at):
        return
    photo = task.proof_photo.name or None
    now = timezone.now()
    if task.status == Task.Status.REVIEW:
        for reviewer in reviewers(task):
            _send(
                reviewer,
                bot_messages.review_request,
                task,
                reviewer,
                now,
                photo=photo,
                about=task,
                kind=TaskMessage.Kind.REVIEW,
            )
    elif (
        task.status == Task.Status.DONE
        and task.kind == Task.Kind.ASSIGNED
        and task.created_by is not None
    ):
        _send(
            task.created_by,
            bot_messages.task_completed,
            task,
            task.created_by,
            now,
            photo=photo,
            about=task,
        )


def send_task_reviewed(task_id: int) -> None:
    task = _load(task_id)
    if task is None:
        return
    now = timezone.now()
    if task.status == Task.Status.DONE:
        _send(task.assignee, bot_messages.task_confirmed, task, now, about=task)
    elif task.status == Task.Status.RETURNED:
        reason = task.comments.order_by("-created_at").values_list("text", flat=True).first()
        _send(task.assignee, bot_messages.task_returned, task, reason or "", now, about=task)


def send_nudge(task_id: int, by_id: int) -> None:
    """The dashboard's "Nudge now": the task's card with who is waiting for it."""
    task = _load(task_id)
    by = _member(by_id)
    if task is None or by is None or not task.is_open:
        return
    _send(task.assignee, bot_messages.nudge, task, by, timezone.now(), about=task)


def send_comment(comment_id: int, mentioned_ids: list[int]) -> None:
    """A new comment, to the assignee, whoever gave the task and everyone mentioned; never to
    the author (research R2 T33/T34)."""
    comment = TaskComment.objects.select_related("author__user").filter(pk=comment_id).first()
    if comment is None:
        return
    task = _load(comment.task_id)
    if task is None:
        return
    mentioned = set(mentioned_ids)
    people: dict[int, Membership] = {}
    for person in (task.assignee, task.created_by):
        if person is not None:
            people[person.pk] = person
    for person in Membership.objects.select_related("user", "company").filter(
        pk__in=mentioned, company_id=task.company_id
    ):
        people.setdefault(person.pk, person)
    author_id = comment.author_id
    for person in people.values():
        if person.pk == author_id:
            continue
        on_task = person.pk in (task.assignee_id, task.created_by_id)
        _send(
            person,
            bot_messages.comment_notice,
            task,
            comment.text,
            comment.author,
            person,
            person.pk in mentioned and not on_task,
        )


def send_due_changed(task_id: int, old_due: str | None, by_id: int) -> None:
    task, by = _load(task_id), _member(by_id)
    if task is None or by is None or not task.is_open:
        return
    old = datetime.fromisoformat(old_due) if old_due else None
    _send(task.assignee, bot_messages.due_changed, task, old, by, timezone.now(), about=task)


def send_task_cancelled(task_id: int, by_id: int) -> None:
    task, by = _load(task_id), _member(by_id)
    if task is None or by is None or task.status != Task.Status.CANCELLED:
        return
    _send(task.assignee, bot_messages.task_cancelled, task, by)


def send_task_taken_away(task_id: int, previous_id: int, by_id: int) -> None:
    task, previous, by = _load(task_id), _member(previous_id), _member(by_id)
    if task is None or previous is None or by is None or task.assignee_id == previous.pk:
        return
    _send(previous, bot_messages.task_taken_away, task, by)


def send_blocked(task_id: int, giver_ids: list[int]) -> None:
    """ "Can't do it" reaches whoever gave the task, with what they can do about it."""
    task = _load(task_id)
    if task is None or task.blocked_at is None:
        return
    now = timezone.now()
    for giver in Membership.objects.select_related("user", "company").filter(pk__in=giver_ids):
        _send(
            giver,
            bot_messages.blocked_notice,
            task,
            giver,
            now,
            about=task,
            kind=TaskMessage.Kind.BLOCKED,
        )


def send_blocker_resolved(task_id: int, action: str, by_id: int, reporter_id: int) -> None:
    task, by, reporter = _load(task_id), _member(by_id), _member(reporter_id)
    if task is None or by is None or reporter is None:
        return
    _send(reporter, bot_messages.blocker_answer, task, action, by, timezone.now(), about=task)


def send_extension_decided(task_id: int, approved: bool, by_id: int, until: str) -> None:
    task, by = _load(task_id), _member(by_id)
    if task is None or by is None or not task.is_open:
        return
    _send(
        task.assignee, bot_messages.extension_answer, task, approved, by, timezone.now(), about=task
    )


def refresh_card(task_id: int, member_id: int, chat_id: int, message_id: int) -> None:
    """The card in a chat, drawn again as it is now (an Undo button whose minute is over goes)."""
    task, member = _load(task_id), _member(member_id)
    if task is None or member is None:
        return
    with translation.override(member.user.language):
        text, markup = bot_messages.task_card(task, member, timezone.now())
    edit_telegram_message.delay(
        BotName.EMPLOYEE, chat_id, message_id, text, serialize_markup(markup)
    )


def send_onboarding(member_id: int, task_ids: list[int]) -> None:
    """A new person's first tasks, in one welcome message."""
    member = Membership.objects.select_related("user", "company").filter(pk=member_id).first()
    if member is None:
        return
    tasks = list(
        Task.objects.select_related(*TASK_RELATIONS).filter(pk__in=task_ids).order_by("due_at")
    )
    if tasks:
        _send(member, bot_messages.onboarding_welcome, member, tasks, timezone.now())


def send_work_handed_back(member_id: int, handed_back: list) -> None:
    """Tell each giver which of the leaver's tasks came back to them."""
    leaver = Membership.objects.filter(pk=member_id).first()
    if leaver is None:
        return
    now = timezone.now()
    for giver_id, task_ids in handed_back:
        giver = Membership.objects.select_related("user").filter(pk=giver_id).first()
        tasks = list(
            Task.objects.select_related("company").filter(pk__in=task_ids).order_by("due_at")
        )
        if giver is not None and tasks:
            _send(giver, bot_messages.work_came_back, str(leaver), tasks, now)


def deliver(task_id, member_id, kind, chat_id, text, reply_markup=None, photo=None) -> None:
    """Send a task message and keep its id (research R1 C5)."""
    message_id = telegram.send_message(BotName.EMPLOYEE, chat_id, text, reply_markup, photo)
    if message_id is not None:
        TaskMessage.objects.get_or_create(
            chat_id=chat_id,
            message_id=message_id,
            defaults={"task_id": task_id, "member_id": member_id, "kind": kind},
        )


# Copies older than this are left as they are.
COPIES_KEPT = timedelta(days=14)


def refresh_messages(task_id: int) -> None:
    """Every copy of the task in people's chats, drawn again as it is now: a checker's request
    once someone else accepted it, the card of someone it was taken from, the giver's "can't do
    it" once answered, a late alert once the work is done. The last reminder goes once the task
    is closed (Telegram deletes messages up to 48 hours old; older ones keep their text)."""
    task = _load(task_id)
    if task is None:
        return
    now = timezone.now()
    copies = TaskMessage.objects.filter(
        task=task, created_at__gte=now - COPIES_KEPT
    ).select_related("member__user", "member__company")
    for row in copies:
        member = row.member
        if member is None:
            continue
        with translation.override(member.user.language):
            text, markup = bot_messages.copy_of(task, member, row.kind, now)
        edit_telegram_message.delay(
            BotName.EMPLOYEE, row.chat_id, row.message_id, text, serialize_markup(markup)
        )
    chat_id = task.assignee.user.telegram_id
    if not task.is_open and task.last_reminder_message_id and chat_id:
        with suppress(TelegramAPIError):
            telegram.delete_message(BotName.EMPLOYEE, chat_id, task.last_reminder_message_id)
        Task.objects.filter(pk=task.pk).update(last_reminder_message_id=None)


def _send(
    member: Membership,
    build: Callable[..., BotMessage],
    *args,
    photo: str | None = None,
    about: Task | None = None,
    kind: str = TaskMessage.Kind.CARD,
) -> None:
    """Send `build(*args)` to `member` in their language. A message `about` a task keeps its id
    (`kind` says what it is), so it can be drawn again when the task changes."""
    user = member.user
    if member.status != Membership.Status.APPROVED or user.telegram_id is None:
        return  # suspended or gone: the bot leaves them alone
    with translation.override(user.language):
        text, markup = build(*args)
    if about is not None:
        from apps.tasks.tasks import send_task_message

        send_task_message.delay(
            about.pk, member.pk, kind, user.telegram_id, text, serialize_markup(markup), photo
        )
        return
    send_telegram_message.delay(
        BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup), photo
    )


def _member(member_id: int) -> Membership | None:
    return Membership.objects.select_related("user", "company").filter(pk=member_id).first()


def _load(task_id: int) -> Task | None:
    return (
        Task.objects.select_related(*TASK_RELATIONS, "confirmed_by__user")
        .prefetch_related("checklist")
        .filter(pk=task_id)
        .first()
    )
