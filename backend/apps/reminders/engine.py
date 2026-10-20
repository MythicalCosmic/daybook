"""Sends the reminders that are due. Celery beat runs it every minute."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from django.db import transaction
from django.utils import timezone, translation

from apps.groups import tasks as group_jobs
from apps.members.models import Membership
from apps.notifications import telegram
from apps.notifications.telegram import BotName, serialize_markup
from apps.reminders import bot_messages
from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.reminders.policies import escalation_recipients, policy_for
from apps.reminders.schedule import quiet_until
from apps.tasks.models import Task
from apps.tasks.queries import TASK_RELATIONS
from apps.timeoff.queries import days_off

logger = logging.getLogger(__name__)

BATCH = 500
# While someone has blocked the bot, try again this often instead of every few minutes.
BLOCKED_RETRY = timedelta(hours=1)
DAYS_OFF_AHEAD = timedelta(days=70)


@dataclass
class Claim:
    task: Task
    policy: ReminderPolicy
    kind: str
    step: int
    escalate: bool
    previous_message_id: int | None


def send_due_reminders(now: datetime | None = None) -> int:
    now = now or timezone.now()
    due = list(
        Task.objects.filter(status__in=Task.OPEN_STATUSES, next_reminder_at__lte=now)
        .order_by("next_reminder_at")
        .values_list("pk", flat=True)[:BATCH]
    )
    sent = 0
    for task_id in due:
        claim = _claim(task_id, now)
        if claim is not None:
            _deliver(claim, now)
            sent += 1
    return sent


@transaction.atomic
def _claim(task_id: int, now: datetime) -> Claim | None:
    """Lock the task, move its next reminder on, and say what to send.

    Another run holding the row simply skips it, so a reminder never goes out twice.
    """
    task = (
        Task.objects.select_for_update(skip_locked=True, of=("self",))
        .select_related(
            *TASK_RELATIONS, "escalate_to__user", "reminder_policy", "template__reminder_policy"
        )
        .filter(pk=task_id, status__in=Task.OPEN_STATUSES, next_reminder_at__lte=now)
        .first()
    )
    if task is None:
        return None
    member = task.assignee
    if (
        task.due_at is None
        or member.status != Membership.Status.APPROVED
        or member.user.telegram_id is None
    ):
        _save(task, next_reminder_at=None)
        return None
    policy = policy_for(task)
    local_now = timezone.localtime(now, ZoneInfo(task.company.timezone))
    # Holidays and approved time off are quiet too, for as far ahead as time off can reach.
    off = days_off(member, local_now.date(), local_now.date() + DAYS_OFF_AHEAD)
    if (resume_at := quiet_until(local_now, policy, off)) is not None:
        _save(task, next_reminder_at=resume_at)
        return None

    previous = task.last_reminder_message_id if policy.replace_previous else None
    if task.due_at > now:
        _save(task, next_reminder_at=task.due_at)
        return Claim(task, policy, ReminderLog.Kind.HEADS_UP, 0, False, previous)

    step = task.reminders_sent + 1
    personal = task.kind == Task.Kind.PERSONAL
    escalate = (
        not personal
        and policy.escalate_after > 0
        and step >= policy.escalate_after
        and task.escalated_at is None
    )
    # A personal task gets one reminder; others repeat until done or the cap.
    more = not personal and (policy.max_reminders == 0 or step < policy.max_reminders)
    _save(
        task,
        reminders_sent=step,
        escalated_at=now if escalate else task.escalated_at,
        next_reminder_at=now + timedelta(minutes=policy.repeat_every_minutes) if more else None,
    )
    return Claim(task, policy, ReminderLog.Kind.REMINDER, step, escalate, previous)


def _deliver(claim: Claim, now: datetime) -> None:
    task, member = claim.task, claim.task.assignee
    user = member.user
    recipients = escalation_recipients(task) if claim.escalate else []
    manager = str(recipients[0]) if len(recipients) == 1 else None  # named in the reminder
    if claim.escalate:
        group_jobs.announce_late.delay(task.pk)  # once per task, when the manager hears too
    with translation.override(user.language):
        if claim.kind == ReminderLog.Kind.HEADS_UP:
            text, markup = bot_messages.heads_up(task)
        else:
            text, markup = bot_messages.reminder(task, claim.step, claim.policy, now, manager)

    try:
        if claim.previous_message_id:
            telegram.delete_message(BotName.EMPLOYEE, user.telegram_id, claim.previous_message_id)
        message_id = telegram.send_message(
            BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup)
        )
    except TelegramForbiddenError:
        _blocked(task, member, now)
        return
    except TelegramAPIError as exc:
        logger.warning("Reminder for task %s not delivered: %s", task.pk, exc)
        _log(task, claim.kind, claim.step, member, error=str(exc))
        return

    Task.objects.filter(pk=task.pk).update(last_reminder_message_id=message_id)
    if user.employee_bot_blocked_at is not None:
        user.employee_bot_blocked_at = None  # it got through, so they unblocked us
        user.save(update_fields=["employee_bot_blocked_at"])
    _log(task, claim.kind, claim.step, member)
    if claim.escalate:
        _tell(
            recipients,
            ReminderLog.Kind.ESCALATION,
            task,
            claim.step,
            lambda: bot_messages.escalation(task, now),
        )


def _blocked(task: Task, member: Membership, now: datetime) -> None:
    user = member.user
    Task.objects.filter(pk=task.pk).update(next_reminder_at=now + BLOCKED_RETRY)
    _log(task, ReminderLog.Kind.REMINDER, task.reminders_sent, member, error="blocked the bot")
    if user.employee_bot_blocked_at is not None:
        return  # managers already know
    user.employee_bot_blocked_at = now
    user.save(update_fields=["employee_bot_blocked_at"])
    recipients = escalation_recipients(task)
    _tell(
        recipients,
        ReminderLog.Kind.BLOCKED,
        task,
        task.reminders_sent,
        lambda: bot_messages.blocked(member, task),
    )


def _tell(recipients, kind: str, task: Task, step: int, build) -> None:
    for recipient in recipients:
        chat_id = recipient.user.telegram_id
        if chat_id is None:
            continue
        with translation.override(recipient.user.language):
            text, markup = build()
        try:
            telegram.send_message(BotName.EMPLOYEE, chat_id, text, serialize_markup(markup))
        except TelegramAPIError as exc:
            _log(task, kind, step, recipient, error=str(exc))
        else:
            _log(task, kind, step, recipient)


def _save(task: Task, **fields) -> None:
    for name, value in fields.items():
        setattr(task, name, value)
    task.save(update_fields=[*fields, "updated_at"])


def _log(task: Task, kind: str, step: int, recipient: Membership, error: str = "") -> None:
    ReminderLog.objects.create(
        task=task, kind=kind, step=step, recipient=recipient, delivered=not error, error=error[:200]
    )
