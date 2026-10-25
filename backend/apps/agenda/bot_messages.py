"""What the bots say about the company calendar. Call these under the reader's language."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from django.conf import settings
from django.utils import timezone
from django.utils.dates import WEEKDAYS
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

from apps.agenda import queries
from apps.agenda.callbacks import EvAction, EvCallback
from apps.agenda.models import Event, EventAttendee
from apps.members.bot_messages import BotMessage, miniapp_url


def app_screen(event: Event) -> str:
    return f"agenda.event:{event.pk}"


def dashboard_url(event: Event) -> str:
    return f"/c/{event.company_id}/calendar?event={event.pk}"


def day_label(day: date, today: date) -> str:
    if day == today:
        return _("today")
    if day == today + timedelta(days=1):
        return _("tomorrow")
    return f"{WEEKDAYS[day.weekday()]}, {day:%d.%m}"


def _time(moment: datetime, event: Event) -> str:
    return f"{timezone.localtime(moment, queries.tz_of(event.company)):%H:%M}"


def when(event: Event, start: datetime, end: datetime | None, *, today: date | None = None) -> str:
    """When it happens in the company's time: "tomorrow 10:00-11:30", "Friday, 24.10 · all
    day", or a range of days for a long all-day event."""
    company = event.company
    today = today or queries.local_day(timezone.now(), company)
    first = queries.local_day(start, company)
    if event.all_day:
        last = queries.local_day(end, company) if end else first
        if last != first:
            return f"{first:%d.%m}–{last:%d.%m}"
        return f"{day_label(first, today)} · {_('all day')}"
    text = f"{day_label(first, today)} {_time(start, event)}"
    if end is not None:
        if queries.local_day(end, company) == first:
            text += f"–{_time(end, event)}"
        else:
            text += f" – {day_label(queries.local_day(end, company), today)} {_time(end, event)}"
    return text


def event_line(event: Event) -> str:
    """One line under a notification title: when, where."""
    parts = [when(event, event.start, event.end)]
    if event.repeat == Event.Repeat.WEEKLY:
        parts.append(_("every week"))
    elif event.repeat == Event.Repeat.MONTHLY:
        parts.append(_("every month"))
    if event.place:
        parts.append(event.place)
    elif event.branch_id:
        parts.append(event.branch.name)
    return " · ".join(parts)


def occurrence_line(occurrence) -> str:
    event = occurrence.event
    parts = [when(event, occurrence.start, occurrence.end)]
    if event.place:
        parts.append(event.place)
    elif event.branch_id:
        parts.append(event.branch.name)
    return " · ".join(parts)


def invite_title(event: Event) -> str:
    return _("You're invited: %(title)s") % {"title": event.title}


def changed_title(event: Event) -> str:
    return _("Event moved: %(title)s") % {"title": event.title}


def cancelled_title(event: Event) -> str:
    return _("Event cancelled: %(title)s") % {"title": event.title}


def cancelled_body(event: Event) -> str:
    line = event_line(event)
    if event.cancel_reason:
        return f"{line}\n{event.cancel_reason}"
    return line


def reminder_title(occurrence) -> str:
    event = occurrence.event
    start = occurrence.start
    minutes = int((start - timezone.now()).total_seconds() // 60)
    if event.all_day or minutes > 120:
        return _("Coming up: %(title)s") % {"title": event.title}
    if minutes <= 1:
        return _("Starting now: %(title)s") % {"title": event.title}
    return _("In %(minutes)d min: %(title)s") % {"minutes": minutes, "title": event.title}


def going_button() -> str:
    return _("I'll come")


def decline_button() -> str:
    # Translators: the attendee's own answer on a button ("I can't come"), not their status.
    return pgettext("event answer button", "Can't come")


def response_note(response: str) -> str:
    if response == EventAttendee.Response.GOING:
        return _("You said you'll come.")
    if response == EventAttendee.Response.DECLINED:
        return _("You said you can't come.")
    return ""


def event_card(event: Event, *, invite: EventAttendee | None) -> BotMessage:
    """An event in the chat, with "I'll come / Can't come" for an attendee."""
    line = event_line(event)  # "tomorrow 10:00 · …" starts a line here: capitalised
    lines = [f"<b>{html.quote(event.title)}</b>", html.quote(line[:1].upper() + line[1:])]
    if event.cancelled_at is not None:
        lines += ["", _("This event was cancelled.")]
    if event.description:
        lines += ["", html.quote(event.description[:1500])]
    rows: list[list[InlineKeyboardButton]] = []
    if invite is not None and event.cancelled_at is None:
        note = response_note(invite.response)
        if note:
            lines += ["", note]
        rows.append(
            [
                InlineKeyboardButton(
                    text=going_button(),
                    callback_data=EvCallback(action=EvAction.GOING, event_id=event.pk).pack(),
                ),
                InlineKeyboardButton(
                    text=decline_button(),
                    callback_data=EvCallback(action=EvAction.DECLINE, event_id=event.pk).pack(),
                ),
            ]
        )
    if settings.EMPLOYEE_MINIAPP_URL.startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_("Open in the app"),
                    web_app=WebAppInfo(url=miniapp_url(app_screen(event))),
                )
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def week(lines: list[tuple[date, list[str]]], *, today: date) -> BotMessage:
    """The next seven days: one block per day that has something."""
    if not lines:
        return _("Nothing on the calendar for the next seven days."), None
    text = [_("<b>Your next seven days</b>"), ""]
    for day, entries in lines:
        text.append(f"<b>{html.quote(day_label(day, today).capitalize())}</b>")
        text += [f"  {html.quote(entry)}" for entry in entries]
        text.append("")
    return "\n".join(text).strip(), None


def answered(response: str) -> str:
    return response_note(response) or _("Saved.")


def cancelled_title_generic() -> str:
    return _("This event isn't on the calendar any more.")
