"""Turning what people type or tap into deadlines, and deadlines into words, in the company's
local time.

Month and weekday names are written out here per language rather than taken from a locale
library: no new dependency, and the same words as the mini app and the dashboard
(research R3 §1.7, §2.1): "Ertaga, 22-oktabr (payshanba), 18:00" / "Завтра, 22 октября (чт),
18:00" / "Tomorrow, 22 Oct (Thu), 18:00", and in short "bugun, 18:30", "25-okt, 18:30".
"""

import re
from datetime import date, datetime, time, timedelta

from apps.tasks import quickadd
from apps.tasks.callbacks import DuePreset

EVENING = time(18, 0)
MORNING = time(9, 0)
# Before this hour "tomorrow morning" is still the coming morning (the night shift's rule, as in
# apps.tasks.quickadd).
ROLLOVER_HOUR = quickadd.ROLLOVER_HOUR

LANGUAGES = ("uz", "ru", "en")
MONTHS = {
    "uz": (
        "yanvar",
        "fevral",
        "mart",
        "aprel",
        "may",
        "iyun",
        "iyul",
        "avgust",
        "sentabr",
        "oktabr",
        "noyabr",
        "dekabr",
    ),
    # The genitive: a day of the month ("22 октября").
    "ru": (
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}
SHORT_MONTHS = {
    "uz": ("yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"),
    "ru": (
        "янв.",
        "февр.",
        "мар.",
        "апр.",
        "мая",
        "июн.",
        "июл.",
        "авг.",
        "сент.",
        "окт.",
        "нояб.",
        "дек.",
    ),
    "en": MONTHS["en"],
}
WEEKDAYS = {
    "uz": ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"),
    "ru": ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
# In brackets after a date: Uzbek keeps the whole word, as people write it.
WEEKDAYS_IN_BRACKETS = {
    "uz": WEEKDAYS["uz"],
    "ru": ("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
TODAY = {"uz": "bugun", "ru": "сегодня", "en": "today"}
TOMORROW = {"uz": "ertaga", "ru": "завтра", "en": "tomorrow"}

_CLOCK = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def read_when(text: str, *, now: datetime) -> quickadd.QuickAdd:
    """What an answer to "when is it due?" says. A bare "9.05" there is a time, not 9 May, as
    the bot always read it; everything else goes through the quick-add parser."""
    if (match := _CLOCK.match(text)) and int(match[1]) <= 23 and int(match[2]) <= 59:
        due = datetime.combine(now.date(), time(int(match[1]), int(match[2])), tzinfo=now.tzinfo)
        rolled = due <= now
        return quickadd.QuickAdd(
            title="",
            due_at=due + timedelta(days=1) if rolled else due,
            spans=((0, len(text)),),
            rolled=rolled,
        )
    return quickadd.parse(text, now=now)


def parse_due(text: str, *, now: datetime) -> datetime | None:
    """A deadline typed on its own (`18:30`, `25.10 18:30`, `ertaga 9:00`, `пятница`, `3pm`) in
    `now`'s timezone, or None when the text is something else or names a moment that has passed.

    A bare time that has already passed today means tomorrow. A date without a year is this
    year's, the next year's only once that day is over: "25.10 08:00" typed on 25 October at
    09:00 has passed (it used to become next October)."""
    found = read_when(text, now=now)
    if found.title or found.past:
        return None
    return found.due_at


def resolve_preset(preset: DuePreset, *, now: datetime) -> datetime | None:
    today_evening = datetime.combine(now.date(), EVENING, tzinfo=now.tzinfo)
    match preset:
        case DuePreset.IN_AN_HOUR:
            return now + timedelta(hours=1)
        case DuePreset.TODAY_EVENING:
            return today_evening if today_evening > now else today_evening + timedelta(days=1)
        case DuePreset.TOMORROW_MORNING:
            return tomorrow_morning(now)
        case DuePreset.NONE:
            return None


def tomorrow_morning(now: datetime) -> datetime:
    """09:00 of the coming morning: tomorrow's, or today's when it's still night (before 05:00,
    when a night shift's "tomorrow" is the morning ahead)."""
    day = now.date() if now.hour < ROLLOVER_HOUR else now.date() + timedelta(days=1)
    return datetime.combine(day, MORNING, tzinfo=now.tzinfo)


def language(code: str | None) -> str:
    """One of uz, ru, en: Uzbek for anything else, as the bots do."""
    code = (code or "")[:2].lower()
    return code if code in LANGUAGES else "uz"


def due_label(due: datetime, now: datetime, lang: str | None) -> str:
    """A deadline in full, to start a line: the day in words, the date and the weekday, the time.

    "Ertaga, 22-oktabr (payshanba), 18:00" · "Завтра, 22 октября (чт), 18:00" · "Tomorrow,
    22 Oct (Thu), 18:00"; other days start with the weekday: "Juma, 23-oktabr, 18:00". `due` and
    `now` are in the company's timezone. The weekday and the date are always there, so "ertaga"
    typed after midnight can't be misread."""
    lang = language(lang)
    day, today = due.date(), now.date()
    when = _day_and_month(day, today, lang)
    weekday = day.weekday()
    if day == today or day == today + timedelta(days=1):
        word = (TODAY if day == today else TOMORROW)[lang]
        text = f"{word}, {when} ({WEEKDAYS_IN_BRACKETS[lang][weekday]}), {due:%H:%M}"
    else:
        text = f"{WEEKDAYS[lang][weekday]}, {when}, {due:%H:%M}"
    return text[0].upper() + text[1:]


def short_due(due: datetime, now: datetime, lang: str | None) -> str:
    """A deadline in a few characters, for the middle of a line ("Muddat: bugun, 18:30"):
    "bugun, 18:30", "ertaga, 09:00", "25-okt, 18:30" · "сегодня, 18:30", "25 окт., 18:30" ·
    "today, 18:30", "25 Oct, 18:30". Another year adds it."""
    lang = language(lang)
    day, today = due.date(), now.date()
    if day == today:
        word = TODAY[lang]
    elif day == today + timedelta(days=1):
        word = TOMORROW[lang]
    else:
        month = SHORT_MONTHS[lang][day.month - 1]
        word = f"{day.day}-{month}" if lang == "uz" else f"{day.day} {month}"
        if day.year != today.year:
            word = f"{word}, {day.year}" if lang == "uz" else f"{word} {day.year}"
    return f"{word}, {due:%H:%M}"


def _day_and_month(day: date, today: date, lang: str) -> str:
    month = MONTHS[lang][day.month - 1]
    if lang == "uz":
        text = f"{day.day}-{month}"
        return text if day.year == today.year else f"{day.year}-yil {text}"
    text = f"{day.day} {month}"
    return text if day.year == today.year else f"{text} {day.year}"
