from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.tasks.callbacks import DuePreset
from apps.tasks.dates import (
    due_label,
    parse_due,
    read_when,
    resolve_preset,
    short_due,
    tomorrow_morning,
)

TASHKENT = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 10, 19, 14, 30, tzinfo=TASHKENT)  # a Monday


def local(month, day, hour, minute, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TASHKENT)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("18:30", local(10, 19, 18, 30)),
        (
            "9.05",
            local(10, 20, 9, 5),
        ),  # answering "when?", a bare 9.05 is a time; past, so tomorrow
        ("14:30", local(10, 20, 14, 30)),  # right now counts as past
        ("25.10 18:00", local(10, 25, 18, 0)),
        ("01.03 08:00", local(3, 1, 8, 0, year=2027)),  # that day is over this year: next year
        ("25.10.2027 18:00", local(10, 25, 18, 0, year=2027)),
        ("  25.10 9:00 ", local(10, 25, 9, 0)),
        # Words, now that the quick-add parser reads the answer (R2 P3).
        ("ertaga 9:00", local(10, 20, 9, 0)),
        ("завтра в 10", local(10, 20, 10, 0)),
        ("3pm", local(10, 19, 15, 0)),  # still ahead today
        ("9am", local(10, 20, 9, 0)),  # passed today: tomorrow
        ("juma", local(10, 23, 18, 0)),
        ("tomorrow", local(10, 20, 18, 0)),
        ("25.10", local(10, 25, 18, 0)),
    ],
)
def test_parse_due(text, expected):
    assert parse_due(text, now=NOW) == expected


@pytest.mark.parametrize("text", ["", "25:00", "18:61", "31.02 10:00", "18", "kassa ertaga"])
def test_parse_due_rejects_nonsense(text):
    assert parse_due(text, now=NOW) is None


def test_todays_date_with_a_time_that_has_passed_is_not_next_year():
    """R2 P2: "25.10 08:00" typed on 25 October at 09:00 used to become 25 October 2027."""
    morning = local(10, 25, 9, 0)
    assert parse_due("25.10 08:00", now=morning) is None
    assert read_when("25.10 08:00", now=morning).past
    assert parse_due("25.10 10:00", now=morning) == local(10, 25, 10, 0)
    assert parse_due("24.10 08:00", now=morning) == local(10, 24, 8, 0, year=2027)


def test_a_bare_clock_says_when_it_rolled_over():
    found = read_when("09:15", now=NOW)
    assert found.due_at == local(10, 20, 9, 15)
    assert found.rolled and found.title == ""


@pytest.mark.parametrize(
    ("preset", "now", "expected"),
    [
        (DuePreset.IN_AN_HOUR, NOW, local(10, 19, 15, 30)),
        (DuePreset.TODAY_EVENING, NOW, local(10, 19, 18, 0)),
        (DuePreset.TODAY_EVENING, local(10, 19, 19, 0), local(10, 20, 18, 0)),
        (DuePreset.TOMORROW_MORNING, NOW, local(10, 20, 9, 0)),
        # On a night shift, "tomorrow morning" at 01:00 is the morning ahead, the same day.
        (DuePreset.TOMORROW_MORNING, local(10, 20, 1, 0), local(10, 20, 9, 0)),
        (DuePreset.NONE, NOW, None),
    ],
)
def test_presets(preset, now, expected):
    assert resolve_preset(preset, now=now) == expected


def test_tomorrow_morning_after_the_rollover_hour():
    assert tomorrow_morning(local(10, 20, 5, 0)) == local(10, 21, 9, 0)


@pytest.mark.parametrize(
    ("due", "lang", "expected"),
    [
        (local(10, 20, 18, 0), "uz", "Ertaga, 20-oktabr (seshanba), 18:00"),
        (local(10, 20, 18, 0), "ru", "Завтра, 20 октября (вт), 18:00"),
        (local(10, 20, 18, 0), "en", "Tomorrow, 20 Oct (Tue), 18:00"),
        (local(10, 19, 18, 30), "uz", "Bugun, 19-oktabr (dushanba), 18:30"),
        (local(10, 19, 18, 30), "ru", "Сегодня, 19 октября (пн), 18:30"),
        (local(10, 23, 9, 0), "uz", "Juma, 23-oktabr, 09:00"),
        (local(10, 23, 9, 0), "ru", "Пятница, 23 октября, 09:00"),
        (local(10, 23, 9, 0), "en", "Friday, 23 Oct, 09:00"),
        (local(1, 5, 18, 0, year=2027), "uz", "Seshanba, 2027-yil 5-yanvar, 18:00"),
        (local(1, 5, 18, 0, year=2027), "ru", "Вторник, 5 января 2027, 18:00"),
        (local(1, 5, 18, 0, year=2027), "en", "Tuesday, 5 Jan 2027, 18:00"),
        (local(10, 20, 18, 0), "kk", "Ertaga, 20-oktabr (seshanba), 18:00"),  # unknown: Uzbek
    ],
)
def test_due_label(due, lang, expected):
    assert due_label(due, NOW, lang) == expected


@pytest.mark.parametrize(
    ("due", "lang", "expected"),
    [
        (local(10, 19, 18, 30), "uz", "bugun, 18:30"),
        (local(10, 19, 18, 30), "ru", "сегодня, 18:30"),
        (local(10, 19, 18, 30), "en", "today, 18:30"),
        (local(10, 20, 9, 0), "uz", "ertaga, 09:00"),
        (local(10, 25, 18, 30), "uz", "25-okt, 18:30"),
        (local(10, 25, 18, 30), "ru", "25 окт., 18:30"),
        (local(10, 25, 18, 30), "en", "25 Oct, 18:30"),
        (local(1, 5, 18, 0, year=2027), "uz", "5-yan, 2027, 18:00"),
        (local(1, 5, 18, 0, year=2027), "en", "5 Jan 2027, 18:00"),
    ],
)
def test_short_due(due, lang, expected):
    assert short_due(due, NOW, lang) == expected
