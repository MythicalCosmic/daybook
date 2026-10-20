"""Telegram texts and keyboards about tasks, used by the bot and by backend notifications."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.companies.models import Company
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership
from apps.tasks import rules
from apps.tasks.callbacks import DueCallback, DuePreset, TaskAction, TaskCallback
from apps.tasks.dates import EVENING
from apps.tasks.models import Proof, Task

LIST_LIMIT = 30


def task_list(tasks: list[Task], now: datetime) -> BotMessage:
    if not tasks:
        return _("🎉 Nothing on your list right now."), None
    rows = [[task_button(task, now)] for task in tasks[:LIST_LIMIT]]
    text = "\n".join([_("📋 <b>Your tasks</b>"), _("Tap a task to open it.")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def task_button(task: Task, now: datetime) -> InlineKeyboardButton:
    """A list entry that opens the task's card."""
    return _button(_list_label(task, now), TaskAction.OPEN, task.pk)


def list_button(label: str) -> InlineKeyboardButton:
    """Shows the person's task list."""
    return _button(label, TaskAction.LIST)


def task_card(task: Task, member: Membership, now: datetime, header: str = "") -> BotMessage:
    lines = [header, ""] if header else []
    lines.append(f"{_icon(task, now)} <b>{html.quote(task.title)}</b>")
    if task.description:
        lines.append(html.quote(task.description))
    lines.append("")
    lines.append(_("Status: %(status)s") % {"status": task.get_status_display()})
    if task.due_at:
        lines.append(_("Due: %(when)s") % {"when": format_due(task, now)})
    if task.kind == Task.Kind.ASSIGNED and task.created_by:
        lines.append(_("From: %(name)s") % {"name": html.quote(str(task.created_by))})
    if not rules.is_assignee(task, member):
        lines.append(_("For: %(name)s") % {"name": html.quote(str(task.assignee))})
    checklist = list(task.checklist.all())
    if checklist:
        done = sum(item.is_done for item in checklist)
        lines.append(
            _("Checklist: %(done)d of %(total)d") % {"done": done, "total": len(checklist)}
        )
    if task.proof != Proof.NONE and task.is_open:
        lines.append(_("Proof needed: %(proof)s") % {"proof": task.get_proof_display().lower()})
    if task.proof_text:
        lines.append(_("Report: %(text)s") % {"text": html.quote(task.proof_text)})
    return "\n".join(lines), _card_keyboard(task, member)


def task_assigned(task: Task, now: datetime) -> BotMessage:
    header = _("📨 <b>New task</b> from %(name)s") % {"name": html.quote(str(task.created_by))}
    return task_card(task, task.assignee, now, header)


def review_request(task: Task, reviewer: Membership, now: datetime) -> BotMessage:
    header = _("🔎 %(name)s finished a task. Please check it.") % {
        "name": html.quote(str(task.assignee))
    }
    return task_card(task, reviewer, now, header)


def task_completed(task: Task, creator: Membership, now: datetime) -> BotMessage:
    header = _("✅ %(name)s completed a task.") % {"name": html.quote(str(task.assignee))}
    return task_card(task, creator, now, header)


def task_confirmed(task: Task, now: datetime) -> BotMessage:
    header = _("👍 %(name)s confirmed your task.") % {"name": html.quote(str(task.confirmed_by))}
    return task_card(task, task.assignee, now, header)


def task_returned(task: Task, reason: str, now: datetime) -> BotMessage:
    header = _("↩️ Your task was sent back: %(reason)s") % {"reason": html.quote(reason)}
    return task_card(task, task.assignee, now, header)


def proof_request(task: Task) -> BotMessage:
    title = {"title": html.quote(task.title)}
    if task.proof == Proof.PHOTO:
        text = _("📷 Send a photo to complete <b>%(title)s</b>.") % title
    elif task.proof == Proof.TEXT:
        text = _("✍️ Send a short report to complete <b>%(title)s</b>.") % title
    else:
        text = _("📷 Send a photo or a short report to complete <b>%(title)s</b>.") % title
    return text, stop_keyboard()


def return_reason_request() -> BotMessage:
    return _("What needs to be fixed? Send a short comment."), stop_keyboard()


def ask_title() -> BotMessage:
    return _("✍️ What needs to be done? Send the task title."), stop_keyboard()


def ask_due(company: Company, now: datetime) -> BotMessage:
    local_now = timezone.localtime(now, ZoneInfo(company.timezone))
    presets = [(_("⏰ In an hour"), DuePreset.IN_AN_HOUR)]
    if local_now.time() < EVENING:
        presets.append((_("🌆 Today 18:00"), DuePreset.TODAY_EVENING))
    presets += [
        (_("🌅 Tomorrow 09:00"), DuePreset.TOMORROW_MORNING),
        (_("♾ No deadline"), DuePreset.NONE),
    ]
    rows = [
        [InlineKeyboardButton(text=label, callback_data=DueCallback(preset=preset).pack())]
        for label, preset in presets
    ]
    rows.append([_button(_("✖️ Cancel"), TaskAction.STOP)])
    text = _("⏰ When is it due? Pick one or send a time like 18:30 or 25.10 18:30.")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def stop_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button(_("✖️ Cancel"), TaskAction.STOP)]])


def format_due(task: Task, now: datetime) -> str:
    tz = ZoneInfo(task.company.timezone)
    due, today = timezone.localtime(task.due_at, tz), timezone.localtime(now, tz).date()
    if due.date() == today:
        day = _("today")
    elif due.date() == today + timedelta(days=1):
        day = _("tomorrow")
    else:
        day = due.strftime("%d.%m")
    text = f"{day} {due:%H:%M}"
    if task.is_overdue(now):
        text += " · " + _("⚠️ late by %(duration)s") % {
            "duration": format_duration(now - task.due_at)
        }
    return text


def format_duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return _("%(minutes)d min") % {"minutes": minutes}
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return _("%(hours)d h %(minutes)d min") % {"hours": hours, "minutes": minutes}
    days, hours = divmod(hours, 24)
    return _("%(days)d d %(hours)d h") % {"days": days, "hours": hours}


def _card_keyboard(task: Task, member: Membership) -> InlineKeyboardMarkup | None:
    actions = rules.allowed_actions(task, member)
    row = []
    if rules.Action.START in actions:
        row.append(_button(_("▶️ Start"), TaskAction.START, task.pk))
    if rules.Action.COMPLETE in actions:
        row.append(_button(_("✅ Done"), TaskAction.DONE, task.pk))
    if rules.Action.CONFIRM in actions:
        row.append(_button(_("✅ Confirm"), TaskAction.CONFIRM, task.pk))
    if rules.Action.RETURN in actions:
        row.append(_button(_("↩️ Send back"), TaskAction.RETURN, task.pk))
    rows = [row] if row else []
    if rules.is_assignee(task, member):
        rows.append([_button(_("⬅️ My tasks"), TaskAction.LIST)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _list_label(task: Task, now: datetime) -> str:
    if task.due_at is None:
        when = "—"
    else:
        tz = ZoneInfo(task.company.timezone)
        due = timezone.localtime(task.due_at, tz)
        same_day = due.date() == timezone.localtime(now, tz).date()
        when = f"{due:%H:%M}" if same_day else f"{due:%d.%m %H:%M}"
    title = task.title if len(task.title) <= 40 else f"{task.title[:39]}…"
    return f"{_icon(task, now)} {when} · {title}"


def _icon(task: Task, now: datetime) -> str:
    if task.status == Task.Status.DONE:
        return "✅"
    if task.status == Task.Status.REVIEW:
        return "🔎"
    if task.status == Task.Status.CANCELLED:
        return "✖️"
    if task.status == Task.Status.RETURNED:
        return "↩️"
    if task.is_overdue(now):
        return "🔴"
    return "🟡" if task.status == Task.Status.IN_PROGRESS else "⚪"


def _button(text: str, action: TaskAction, task_id: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=TaskCallback(action=action, task_id=task_id).pack()
    )
