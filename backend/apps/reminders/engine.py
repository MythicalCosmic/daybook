"""Sends the reminders that are due. Celery beat runs it every minute."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from django.db import transaction
from django.utils import timezone, translation

from apps.groups import tasks as group_jobs
from apps.members.models import Membership
from apps.notifications import telegram
from apps.notifications.telegram import BotName, serialize_markup
from apps.reminders import bot_messages
from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.reminders.policies import escalation_recipients, policy_for
from apps.reminders.schedule import quiet_for_task
from apps.tasks.models import Task, TaskMessage
from apps.tasks.queries import with_relations
from apps.timeoff.queries import days_off

logger = logging.getLogger(__name__)

BATCH = 500
# While someone has blocked the bot, try again this often instead of every few minutes.
BLOCKED_RETRY = timedelta(hours=1)
DAYS_OFF_AHEAD = timedelta(days=70)
# Around a shift: arriving a little early or staying a little late still counts as at work.
SHIFT_MARGIN = timedelta(minutes=30)
SHIFT_LOOKAHEAD = timedelta(hours=24)


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
    # with_relations also brings the escalation contact, the policies and the company.
    task = (
        with_relations(Task.objects.select_for_update(skip_locked=True, of=("self",)))
        .filter(pk=task_id, status__in=Task.OPEN_STATUSES, next_reminder_at__lte=now)
        .first()
    )
    if task is None:
        return None
    member = task.assignee
    if (
        task.due_at is None
        or task.blocked_at is not None  # "can't do it": quiet until someone decides
        or member.status != Membership.Status.APPROVED
        or member.user.telegram_id is None
    ):
        _save(task, next_reminder_at=None)
        return None
    policy = policy_for(task)
    local_now = timezone.localtime(now, ZoneInfo(task.company.timezone))
    # Holidays and approved time off are quiet too, for as far ahead as time off can reach.
    off = days_off(member, local_now.date(), local_now.date() + DAYS_OFF_AHEAD)
    resume_at = quiet_for_task(
        local_now, policy, off, due=task.due_at, shift=shift_now(member, now, task.company)
    )
    if resume_at is not None:
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
    except TelegramRetryAfter as exc:
        if not claim.escalate:
            _retry_later(claim, now + timedelta(seconds=exc.retry_after + 1))
            return
        # An escalation isn't sent again: the team group already heard; the next reminder follows.
        logger.warning("Reminder for task %s not delivered: %s", task.pk, exc)
        _log(task, claim.kind, claim.step, member, error=str(exc))
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
            lambda recipient: bot_messages.escalation(task, now, recipient),
        )


def shift_now(
    member: Membership, now: datetime, company=None
) -> tuple[bool, datetime | None] | None:
    """Whether the person is at work now and when their next shift starts, from the attendance
    roster (research R1 N1); None when the company doesn't use attendance or the person has no
    shift around now, so the policy's quiet hours decide."""
    if not (company or member.company).has_feature("attendance"):
        return None
    from apps.attendance.models import WorkShift

    shifts = list(
        WorkShift.objects.working()
        .filter(
            membership=member,
            ends_at__gte=now - SHIFT_MARGIN,
            starts_at__lte=now + SHIFT_LOOKAHEAD,
        )
        .order_by("starts_at")
        .values_list("starts_at", "ends_at")
    )
    if not shifts:
        return None
    at_work = any(start - SHIFT_MARGIN <= now <= end + SHIFT_MARGIN for start, end in shifts)
    upcoming = [start for start, _end in shifts if start - SHIFT_MARGIN > now]
    return at_work, (upcoming[0] if upcoming else None)


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
        lambda recipient: bot_messages.blocked(member, task),
    )


def _tell(recipients, kind: str, task: Task, step: int, build) -> None:
    for recipient in recipients:
        chat_id = recipient.user.telegram_id
        if chat_id is None:
            continue
        with translation.override(recipient.user.language):
            text, markup = build(recipient)
        try:
            message_id = telegram.send_message(
                BotName.EMPLOYEE, chat_id, text, serialize_markup(markup)
            )
        except TelegramAPIError as exc:
            _log(task, kind, step, recipient, error=str(exc))
        else:
            _log(task, kind, step, recipient)
            if kind == ReminderLog.Kind.ESCALATION and message_id is not None:
                # Kept, so the alert says "done" once it is (research R1 C5).
                TaskMessage.objects.get_or_create(
                    chat_id=chat_id,
                    message_id=message_id,
                    defaults={
                        "task": task,
                        "member": recipient,
                        "kind": TaskMessage.Kind.ESCALATION,
                    },
                )


def _retry_later(claim: Claim, at: datetime) -> None:
    """Telegram asked to slow down: the same reminder goes again once it allows, instead of being
    lost until the next one (the claim had already moved the step and the next time on)."""
    fields = {"next_reminder_at": at}
    if claim.kind == ReminderLog.Kind.REMINDER:
        fields["reminders_sent"] = claim.step - 1
    _save(claim.task, **fields)


def _save(task: Task, **fields) -> None:
    for name, value in fields.items():
        setattr(task, name, value)
    task.save(update_fields=[*fields, "updated_at"])


def _log(task: Task, kind: str, step: int, recipient: Membership, error: str = "") -> None:
    ReminderLog.objects.create(
        task=task, kind=kind, step=step, recipient=recipient, delivered=not error, error=error[:200]
    )
