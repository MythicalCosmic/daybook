from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.tasks.callbacks import DuePreset
from apps.tasks.dates import parse_due, resolve_preset

TASHKENT = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 10, 19, 14, 30, tzinfo=TASHKENT)


def local(month, day, hour, minute, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TASHKENT)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("18:30", local(10, 19, 18, 30)),
        ("9.05", local(10, 20, 9, 5)),  # already past today, so tomorrow
        ("14:30", local(10, 20, 14, 30)),  # right now counts as past
        ("25.10 18:00", local(10, 25, 18, 0)),
        ("01.03 08:00", local(3, 1, 8, 0, year=2027)),  # past date without a year: next year
        ("25.10.2027 18:00", local(10, 25, 18, 0, year=2027)),
        ("  25.10 9:00 ", local(10, 25, 9, 0)),
    ],
)
def test_parse_due(text, expected):
    assert parse_due(text, now=NOW) == expected


@pytest.mark.parametrize("text", ["", "tomorrow", "25:00", "18:61", "31.02 10:00", "18"])
def test_parse_due_rejects_nonsense(text):
    assert parse_due(text, now=NOW) is None


@pytest.mark.parametrize(
    ("preset", "now", "expected"),
    [
        (DuePreset.IN_AN_HOUR, NOW, local(10, 19, 15, 30)),
        (DuePreset.TODAY_EVENING, NOW, local(10, 19, 18, 0)),
        (DuePreset.TODAY_EVENING, local(10, 19, 19, 0), local(10, 20, 18, 0)),
        (DuePreset.TOMORROW_MORNING, NOW, local(10, 20, 9, 0)),
        (DuePreset.NONE, NOW, None),
    ],
)
def test_presets(preset, now, expected):
    assert resolve_preset(preset, now=now) == expected
