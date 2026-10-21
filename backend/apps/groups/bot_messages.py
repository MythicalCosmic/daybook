"""What the bot posts in company groups."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.companies.models import Company
from apps.groups.callbacks import GroupAction, GroupCallback
from apps.groups.models import GroupEvent, TelegramGroup, available_events
from apps.groups.reports import DayStats, PlanRow
from apps.members.bot_messages import BotMessage
from apps.members.models import Membership, Position
from apps.tasks.bot_messages import display_title, format_duration
from apps.tasks.models import Task

NOT_DONE_LIMIT = 15
# Longer lists of positions are cut short on the settings button.
WHO_LIMIT = 40


def task_done(task: Task) -> BotMessage:
    zone = ZoneInfo(task.company.timezone)
    at = timezone.localtime(task.completed_at, zone).strftime("%H:%M")
    values = {
        "name": html.quote(str(task.assignee)),
        "task": html.quote(display_title(task)),
        "time": at,
    }
    lines = [_("✅ <b>%(name)s</b> finished <b>%(task)s</b>") % values]
    if task.due_at is None or task.completed_at <= task.due_at:
        lines.append(_("At %(time)s, on time.") % values)
    else:
        lines.append(
            _("At %(time)s, %(late)s late.")
            % (values | {"late": format_duration(task.completed_at - task.due_at)})
        )
    if task.proof_text:
        lines.append(f"📝 {html.quote(task.proof_text)}")
    if task.status == Task.Status.REVIEW:
        lines.append(_("Waiting for a check."))
    return "\n".join(lines), None


def late(task: Task, now: datetime) -> BotMessage:
    text = _("🚨 <b>%(name)s</b> is %(late)s late with <b>%(task)s</b>.") % {
        "name": html.quote(str(task.assignee)),
        "late": format_duration(now - task.due_at),
        "task": html.quote(display_title(task)),
    }
    return text, None


def member_joined(member: Membership) -> BotMessage:
    values = {"name": html.quote(str(member))}
    if member.position:
        text = _("👋 <b>%(name)s</b> joined the team as %(position)s.") % (
            values | {"position": html.quote(member.position.name)}
        )
    else:
        text = _("👋 <b>%(name)s</b> joined the team.") % values
    return text, None


def morning(company: Company, day: date, rows: list[PlanRow]) -> BotMessage:
    zone = ZoneInfo(company.timezone)
    lines = [_("🌅 <b>Today's plan</b> · %(date)s") % {"date": day.strftime("%d.%m")}, ""]
    for row in rows:
        lines.append(
            _("• %(name)s: %(count)d, the first at %(time)s")
            % {
                "name": html.quote(row.name),
                "count": row.count,
                "time": timezone.localtime(row.first_due, zone).strftime("%H:%M"),
            }
        )
    return "\n".join(lines), None


def evening(day: date, stats: DayStats) -> BotMessage:
    lines = [
        _("🌙 <b>How today went</b> · %(date)s") % {"date": day.strftime("%d.%m")},
        "",
        _("✅ Done on time: %(count)d") % {"count": stats.on_time},
        _("⏰ Done late: %(count)d") % {"count": stats.late},
        _("❌ Not done: %(count)d") % {"count": len(stats.not_done)},
    ]
    if stats.not_done:
        lines.append("")
        for person, task in stats.not_done[:NOT_DONE_LIMIT]:
            lines.append(f"• {html.quote(person)}: {html.quote(task)}")
        if (more := len(stats.not_done) - NOT_DONE_LIMIT) > 0:
            lines.append(_("…and %(count)d more") % {"count": more})
    return "\n".join(lines), None


def connected(group: TelegramGroup) -> BotMessage:
    header = _("🔗 This group is now connected to <b>%(company)s</b>.") % {
        "company": html.quote(group.company.name)
    }
    text, markup = settings(group)
    return f"{header}\n\n{text}", markup


def settings(group: TelegramGroup) -> BotMessage:
    rows = [
        [
            _button(
                f"{'✅' if event in group.events else '▫️'} {event.label}",
                GroupAction.TOGGLE,
                event=event,
            )
        ]
        for event in available_events(group.company, group.events)
    ]
    rows.append([_button(_("👥 Whose news: %(who)s") % {"who": _who(group)}, GroupAction.WHO)])
    rows.append([_button(_("✔️ Done"), GroupAction.CLOSE)])
    text = _("⚙️ <b>What should I post here?</b> Tap to turn things on or off.")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def positions_picker(group: TelegramGroup) -> BotMessage:
    chosen = {position.pk for position in group.positions.all()}
    positions = Position.objects.for_company(group.company_id).filter(
        Q(is_active=True) | Q(pk__in=chosen)
    )
    rows = [
        [
            _button(
                f"{'✅' if position.pk in chosen else '▫️'} {position.name}",
                GroupAction.POSITION,
                position_id=position.pk,
            )
        ]
        for position in positions
    ]
    rows.append([_button(_("⬅️ Back"), GroupAction.BACK)])
    text = _(
        "👥 <b>Whose news should this group get?</b> "
        "Pick positions, or leave them all off for everyone."
    )
    if not rows[:-1]:
        text += "\n\n" + _("This company has no positions yet.")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _who(group: TelegramGroup) -> str:
    names = ", ".join(position.name for position in group.positions.all())
    if not names:
        return _("everyone")
    return names if len(names) <= WHO_LIMIT else f"{names[: WHO_LIMIT - 1]}…"


def _button(text: str, action: GroupAction, **fields) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=GroupCallback(action=action, **fields).pack()
    )


def welcome() -> BotMessage:
    text = _(
        "👋 Hi! I post this team's task news here: finished work, late tasks and daily summaries."
        "\nA manager can link me to the company by sending /connect."
    )
    return text, None


def not_connected() -> BotMessage:
    return _("This group isn't connected to a company yet. A manager can send /connect."), None


def anonymous() -> BotMessage:
    text = _(
        "I can't tell who you are while you post anonymously. "
        "Turn off “Remain anonymous” in your admin rights and try again."
    )
    return text, None


def disconnected() -> BotMessage:
    text = _(
        "🔌 Disconnected. I won't post here any more. "
        "A manager can send /connect to link this group again."
    )
    return text, None


def settings_saved(group: TelegramGroup) -> BotMessage:
    chosen = [str(GroupEvent(event).label) for event in group.events]
    if not chosen:
        return _("Nothing will be posted here. Send /settings to change that."), None
    lines = [_("I'll post here: %(events)s.") % {"events": ", ".join(chosen)}]
    if names := [position.name for position in group.positions.all()]:
        lines.append(_("Only about: %(positions)s.") % {"positions": html.quote(", ".join(names))})
    lines.append(_("Send /settings to change that."))
    return "\n".join(lines), None
