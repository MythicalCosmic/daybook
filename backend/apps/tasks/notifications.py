from collections.abc import Callable

from django.utils import timezone, translation

from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.tasks import bot_messages
from apps.tasks.models import Task
from apps.tasks.queries import TASK_RELATIONS, reviewers


def send_task_assigned(task_id: int) -> None:
    task = _load(task_id)
    if task is None or not task.is_open:
        return
    _send(task.assignee, bot_messages.task_assigned, task, timezone.now())


def send_task_completed(task_id: int) -> None:
    task = _load(task_id)
    if task is None:
        return
    photo = task.proof_photo.name or None
    now = timezone.now()
    if task.status == Task.Status.REVIEW:
        for reviewer in reviewers(task):
            _send(reviewer, bot_messages.review_request, task, reviewer, now, photo=photo)
    elif (
        task.status == Task.Status.DONE
        and task.kind == Task.Kind.ASSIGNED
        and task.created_by is not None
    ):
        _send(task.created_by, bot_messages.task_completed, task, task.created_by, now, photo=photo)


def send_task_reviewed(task_id: int) -> None:
    task = _load(task_id)
    if task is None:
        return
    now = timezone.now()
    if task.status == Task.Status.DONE:
        _send(task.assignee, bot_messages.task_confirmed, task, now)
    elif task.status == Task.Status.RETURNED:
        reason = task.comments.order_by("-created_at").values_list("text", flat=True).first()
        _send(task.assignee, bot_messages.task_returned, task, reason or "", now)


def send_nudge(task_id: int, by_id: int) -> None:
    """The dashboard's "Nudge now": the task's card with who is waiting for it."""
    task = _load(task_id)
    by = Membership.objects.select_related("user").filter(pk=by_id).first()
    if task is None or by is None or not task.is_open:
        return
    _send(task.assignee, bot_messages.nudge, task, by, timezone.now())


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


def _send(
    member: Membership,
    build: Callable[..., BotMessage],
    *args,
    photo: str | None = None,
) -> None:
    user = member.user
    if member.status != Membership.Status.APPROVED or user.telegram_id is None:
        return  # suspended or gone: the bot leaves them alone
    with translation.override(user.language):
        text, markup = build(*args)
    send_telegram_message.delay(
        BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup), photo
    )


def _load(task_id: int) -> Task | None:
    return (
        Task.objects.select_related(*TASK_RELATIONS, "confirmed_by__user")
        .prefetch_related("checklist")
        .filter(pk=task_id)
        .first()
    )
