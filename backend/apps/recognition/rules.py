"""The numbers of recognition (docs/PLAN-LEARNING.md §7.1, §7.2): points per reason and levels.

    rules.points_for(settings, "quiz")         # 20, or what the company set
    rules.level_for(740)                       # Level(number=4, name="Bilimdon", ...)

**Points.** `POINTS` is the default table; a company changes any row in
`RecognitionSettings.points_table` (`{"quiz": 25}`), and a row it leaves out keeps the default.
Some reasons have more than one row: the question of the day gives `daily` for a right answer
and `daily_tried` for a wrong one, a streak gives `streak_7`, `streak_30` or `streak_100`.
Points are never money.

**Levels.** Ten, by all-time points. Their names are part of the product (like the badge
catalogue), so they live here in the three languages rather than in the .po files.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils import translation
from django.utils.translation import gettext_lazy as _

# Reason (or reason row) → points (§7.1).
POINTS: dict[str, int] = {
    "lesson": 10,
    "page": 5,
    "quiz": 20,
    "quiz_perfect": 10,
    "course": 50,
    "daily": 5,
    "daily_tried": 1,
    "check": 15,
    "streak_7": 20,
    "streak_30": 100,
    "streak_100": 300,
    "kudos": 5,
    "task": 2,
    "badge": 0,
}
# What each row of the table is for, in the settings panel.
POINT_LABELS = {
    "lesson": _("Lesson watched"),
    "page": _("Page read in a course"),
    "quiz": _("Quiz passed (first time)"),
    "quiz_perfect": _("Quiz with 100%"),
    "course": _("Course finished"),
    "daily": _("Question of the day, right"),
    "daily_tried": _("Question of the day, tried"),
    "check": _("Regular check passed"),
    "streak_7": _("7 days in a row"),
    "streak_30": _("30 days in a row"),
    "streak_100": _("100 days in a row"),
    "kudos": _("Kudos received"),
    "task": _("Task done on time"),
    "badge": _("Badge earned"),
}
MAX_POINTS = 1000  # per row of the table
MAX_ADJUST = 10000  # one correction, either way
STREAK_MILESTONES = (7, 30, 100)
TASKS_A_DAY = 10  # task points a person can get for one day's work

# Where each level starts (total points), lowest first.
LEVELS: tuple[int, ...] = (0, 100, 250, 500, 1000, 2000, 3500, 5500, 8000, 12000)
LEVEL_NAMES: dict[str, tuple[str, ...]] = {
    "en": (
        "Newcomer",
        "Learner",
        "Active",
        "Knowledgeable",
        "Experienced",
        "Specialist",
        "Mentor",
        "Expert",
        "Master",
        "Legend",
    ),
    "uz": (
        "Yangi boshlovchi",
        "O‘rganuvchi",
        "Faol",
        "Bilimdon",
        "Tajribali",
        "Mutaxassis",
        "Ustoz",
        "Ekspert",
        "Usta",
        "Afsona",
    ),
    "ru": (
        "Новичок",
        "Ученик",
        "Активный",
        "Знаток",
        "Опытный",
        "Специалист",
        "Наставник",
        "Эксперт",
        "Мастер",
        "Легенда",
    ),
}


def language(code: str | None = None) -> str:
    """ "uz", "ru" or "en": the active language (or `code`) as the catalogues know it."""
    code = (code or translation.get_language() or "en").lower()[:2]
    return code if code in LEVEL_NAMES else "en"


def table(points_table: dict | None) -> dict[str, int]:
    """The whole table: the defaults with the company's own rows over them (bad rows ignored)."""
    merged = dict(POINTS)
    for key, value in (points_table or {}).items():
        if key in merged and isinstance(value, int) and not isinstance(value, bool):
            merged[key] = max(0, min(MAX_POINTS, value))
    return merged


def points_for(settings, key: str) -> int:
    """The company's points for one row (`settings`: its `RecognitionSettings`, or None for the
    defaults). An unknown row is worth nothing."""
    return table(getattr(settings, "points_table", None)).get(key, 0)


def clean_table(value) -> dict[str, int]:
    """A points table as an owner sends it: known rows, whole numbers from 0 to MAX_POINTS.
    Rows equal to the default are left out, so a later change of a default reaches them."""
    if not isinstance(value, dict):
        raise ValueError("points_table")
    cleaned = {}
    for key, points in value.items():
        if key not in POINTS:
            raise ValueError(key)
        if isinstance(points, bool) or not isinstance(points, int):
            raise ValueError(key)
        if not 0 <= points <= MAX_POINTS:
            raise ValueError(key)
        if points != POINTS[key]:
            cleaned[key] = points
    return cleaned


@dataclass(frozen=True)
class LevelInfo:
    number: int  # 1 to 10
    starts_at: int
    next_at: int | None  # None: the top level


def level_number(total: int) -> int:
    """The level of `total` points: 1 (Newcomer) to 10 (Legend)."""
    number = 1
    for index, start in enumerate(LEVELS):
        if total >= start:
            number = index + 1
    return number


def level_info(number: int) -> LevelInfo:
    index = max(1, min(len(LEVELS), number)) - 1
    following = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
    return LevelInfo(number=index + 1, starts_at=LEVELS[index], next_at=following)


def level_name(number: int, code: str | None = None) -> str:
    names = LEVEL_NAMES[language(code)]
    return names[max(1, min(len(names), number)) - 1]
