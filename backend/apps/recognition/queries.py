"""Read functions of recognition, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

**The contract other apps call** (docs/PLAN-LEARNING.md §7.4; pinned by tests/test_contract.py):
`summary(member)` (points, level and streak for a profile or a card) and `levels()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.members.models import Membership


@dataclass(frozen=True)
class Level:
    number: int
    name: str  # in the active language
    starts_at: int  # total points where it starts
    next_at: int | None  # where the next level starts (None: the top one)


@dataclass(frozen=True)
class Summary:
    points: int  # all-time total
    week_points: int  # since Monday (the company's week)
    level: Level
    streak: int
    best_streak: int
    badges: int
    badge_keys: list[str] = field(default_factory=list)  # the newest first


def levels() -> list[Level]:
    """Every level, lowest first, named in the active language (apps.recognition.rules)."""
    return []  # Package R fills this in (v8/recognition).


def summary(member: Membership) -> Summary | None:
    """`member`'s points, level, streak and badges; None while the module is off."""
    return None  # Package R fills this in (v8/recognition).
