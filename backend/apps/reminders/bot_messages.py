"""What reminders say. The wording firms up with every reminder; owners can replace it."""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.reminders.models import ReminderPolicy
from apps.tasks.bot_messages import format_duration
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Task


def heads_up(task: Task) -> BotMessage:
    text = _("⏳ Heads-up: <b>%(task)s</b> is due at %(time)s.") % {
        "task": html.quote(task.title),
        "time": _clock(task),
    }
    return text, _keyboard(task, snooze_minutes=None)


def reminder(
    task: Task, step: int, policy: ReminderPolicy, now: datetime, manager: str | None
) -> BotMessage:
    values = {
        "task": html.quote(task.title),
        "time": _clock(task),
        "late": format_duration(now - task.due_at),
        "step": step,
        "manager": html.quote(manager or _("Your manager")),
    }
    custom = _custom_text(policy, step)
    if custom is not None:
        text = _fill(custom, task, values)
    elif step == 1:
        text = _("⏰ <b>%(task)s</b> was due at %(time)s. Please do it now.") % values
    elif (
        policy.escalate_after and step == policy.escalate_after and task.kind != Task.Kind.PERSONAL
    ):
        text = _("🚨 <b>%(task)s</b> is %(late)s late. %(manager)s has been told.") % values
    elif policy.escalate_after and step > policy.escalate_after and task.kind != Task.Kind.PERSONAL:
        text = (
            _("😤 Still not done: <b>%(task)s</b>, %(late)s late. Finish it now, please.") % values
        )
    else:
        text = _("🔔 Reminder %(step)d: <b>%(task)s</b> is %(late)s late.") % values
    snoozes_left = policy.max_snoozes - task.snooze_count
    return text, _keyboard(task, snooze_minutes=policy.snooze_minutes if snoozes_left > 0 else None)


def escalation(task: Task, now: datetime) -> BotMessage:
    text = _(
        "🚨 <b>%(name)s</b> is %(late)s late with <b>%(task)s</b>. Reminders sent: %(count)d."
    ) % {
        "name": html.quote(str(task.assignee)),
        "late": format_duration(now - task.due_at),
        "task": html.quote(task.title),
        "count": task.reminders_sent,
    }
    return text, _open_keyboard(task)


def blocked(member: Membership, task: Task) -> BotMessage:
    text = _(
        "⛔ <b>%(name)s</b> blocked the bot, so reminders can't reach them. "
        "<b>%(task)s</b> is still open."
    ) % {"name": html.quote(str(member)), "task": html.quote(task.title)}
    return text, _open_keyboard(task)


def _custom_text(policy: ReminderPolicy, step: int) -> str | None:
    texts = [text for text in policy.texts.all() if text.from_step <= step]
    return max(texts, key=lambda text: text.from_step).text if texts else None


def _fill(template: str, task: Task, values: dict) -> str:
    """Owner-written text: escape it, then fill the placeholders it uses."""
    text = html.quote(template)
    replacements = {
        "{name}": html.quote(task.assignee.first_name or str(task.assignee)),
        "{task}": f"<b>{values['task']}</b>",
        "{due}": values["time"],
        "{late}": values["late"],
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _clock(task: Task) -> str:
    return timezone.localtime(task.due_at, ZoneInfo(task.company.timezone)).strftime("%H:%M")


def _keyboard(task: Task, snooze_minutes: int | None) -> InlineKeyboardMarkup:
    row = [_button(_("✅ Done"), TaskAction.DONE, task.pk)]
    if snooze_minutes:
        row.append(
            _button(
                _("⏰ %(minutes)d min") % {"minutes": snooze_minutes}, TaskAction.SNOOZE, task.pk
            )
        )
    row.append(_button(_("📋 Open"), TaskAction.OPEN, task.pk))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def _open_keyboard(task: Task) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(_("📋 Open"), TaskAction.OPEN, task.pk)]])


def _button(text: str, action: TaskAction, task_id: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=TaskCallback(action=action, task_id=task_id).pack()
    )
