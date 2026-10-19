"""Turning what people type or tap into deadlines, in the company's local time."""

import re
from datetime import date, datetime, time, timedelta

from apps.tasks.callbacks import DuePreset

EVENING = time(18, 0)
MORNING = time(9, 0)

_TIME = re.compile(r"^(\d{1,2})[:.](\d{2})$")
_DATE_TIME = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s+(\d{1,2})[:.](\d{2})$")


def parse_due(text: str, *, now: datetime) -> datetime | None:
    """Parse `18:30`, `25.10 18:30` or `25.10.2026 18:30` in `now`'s timezone.

    A bare time that has already passed today means tomorrow; a date without a year
    that has already passed means next year.
    """
    text = text.strip()
    if match := _TIME.match(text):
        due = _at(now.date(), int(match[1]), int(match[2]), now)
        if due is not None and due <= now:
            due += timedelta(days=1)
        return due
    if match := _DATE_TIME.match(text):
        day, month, hour, minute = int(match[1]), int(match[2]), int(match[4]), int(match[5])
        year = int(match[3]) if match[3] else now.year
        try:
            due = _at(date(year, month, day), hour, minute, now)
        except ValueError:
            return None
        if due is not None and match[3] is None and due <= now:
            try:
                due = due.replace(year=year + 1)
            except ValueError:  # 29 February
                return None
        return due
    return None


def resolve_preset(preset: DuePreset, *, now: datetime) -> datetime | None:
    today_evening = datetime.combine(now.date(), EVENING, tzinfo=now.tzinfo)
    match preset:
        case DuePreset.IN_AN_HOUR:
            return now + timedelta(hours=1)
        case DuePreset.TODAY_EVENING:
            return today_evening if today_evening > now else today_evening + timedelta(days=1)
        case DuePreset.TOMORROW_MORNING:
            return datetime.combine(now.date() + timedelta(days=1), MORNING, tzinfo=now.tzinfo)
        case DuePreset.NONE:
            return None


def _at(day: date, hour: int, minute: int, now: datetime) -> datetime | None:
    try:
        return datetime.combine(day, time(hour, minute), tzinfo=now.tzinfo)
    except ValueError:
        return None
