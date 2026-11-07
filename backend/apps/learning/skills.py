"""Mastery: how well each person knows each topic, from the questions they answered
(package Q2; docs/PLAN-LEARNING.md §4.6).

**The contract other packages call** (pinned by tests/test_contract.py):

    mastery(company, member_ids=[3, 7], topic_ids=None) -> {(member_id, topic_id): Mastery}
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# A topic is rated after this many answers; below WEAK it is weak, from STRONG strong.
MIN_ANSWERS = 3
WEAK = 60
STRONG = 85


@dataclass(frozen=True)
class Mastery:
    score: int | None  # 0 to 100, None while unrated (fewer than MIN_ANSWERS answers)
    answers: int
    last_at: datetime | None
    band: str  # "weak" | "ok" | "strong" | "unrated"


def mastery(
    company,
    *,
    member_ids: list[int] | None = None,
    topic_ids: list[int] | None = None,
    since: datetime | None = None,
) -> dict[tuple[int, int], Mastery]:
    """Each (person, topic) with at least one answer: the weighted share of points earned over
    their last 20 answers in the topic, the newest weighing most (§4.6)."""
    return {}  # Package Q2 fills this in (v8/quizzes).
