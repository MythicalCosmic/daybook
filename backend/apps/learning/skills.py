"""Mastery: how well each person knows each topic, from the questions they answered
(package Q2; docs/PLAN-LEARNING.md §4.6).

**The contract other packages call** (pinned by tests/test_contract.py):

    mastery(company, member_ids=[3, 7], topic_ids=None) -> {(member_id, topic_id): Mastery}

Every answered question (an attempt, a check, the question of the day) is an `AnswerLog` with
the question's topic at that time and the share of its points earned. A person's mastery of a
topic is the weighted mean of that share over their last 20 answers in it, the newest weighing
1 and each older one 0.85 of the one after it, times 100, rounded (half up). It is rated from
`MIN_ANSWERS` answers: weak below `WEAK`, strong from `STRONG`, ok between.

The skill matrix (`matrix`) is people x topics for the dashboard: each cell the score, its
band and the number of answers; each topic its average over the people rated in it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Count, F, Window
from django.db.models.functions import RowNumber

from apps.knowledge import topics as topic_services
from apps.learning.models import AnswerLog
from apps.members import queries as member_queries
from apps.members.models import Membership

# A topic is rated after this many answers; below WEAK it is weak, from STRONG strong.
MIN_ANSWERS = 3
WEAK = 60
STRONG = 85
# The answers that count, newest first, and how much less each older one weighs.
RECENT = 20
DECAY = 0.85

WEAK_BAND, OK_BAND, STRONG_BAND, UNRATED = "weak", "ok", "strong", "unrated"


@dataclass(frozen=True)
class Mastery:
    score: int | None  # 0 to 100, None while unrated (fewer than MIN_ANSWERS answers)
    answers: int
    last_at: datetime | None
    band: str  # "weak" | "ok" | "strong" | "unrated"


def band(score: int | None) -> str:
    if score is None:
        return UNRATED
    if score < WEAK:
        return WEAK_BAND
    if score >= STRONG:
        return STRONG_BAND
    return OK_BAND


def score_of(shares_newest_first: list[float]) -> int:
    """The weighted mean of `shares` (0 to 1, newest first) as a whole percent."""
    weights = [DECAY**age for age in range(len(shares_newest_first))]
    total = sum(weight * share for weight, share in zip(weights, shares_newest_first, strict=True))
    return math.floor(total / sum(weights) * 100 + 0.5)


def mastery(
    company,
    *,
    member_ids: list[int] | None = None,
    topic_ids: list[int] | None = None,
    since: datetime | None = None,
) -> dict[tuple[int, int], Mastery]:
    """Each (person, topic) with at least one answer: the weighted share of points earned over
    their last 20 answers in the topic, the newest weighing most (§4.6)."""
    rows = AnswerLog.objects.filter(company=company, topic__isnull=False)
    if member_ids is not None:
        rows = rows.filter(membership_id__in=list(member_ids))
    if topic_ids is not None:
        rows = rows.filter(topic_id__in=list(topic_ids))
    if since is not None:
        rows = rows.filter(at__gte=since)
    partition = [F("membership_id"), F("topic_id")]
    ranked = rows.annotate(
        rank=Window(RowNumber(), partition_by=partition, order_by=[F("at").desc(), F("pk").desc()]),
        total=Window(Count("pk"), partition_by=partition),
    )
    recent = ranked.filter(rank__lte=RECENT).values_list(
        "membership_id", "topic_id", "rank", "share", "at", "total"
    )
    found: dict[tuple[int, int], list] = defaultdict(list)
    totals: dict[tuple[int, int], tuple[int, datetime]] = {}
    for member_id, topic_id, rank, share, at, total in recent:
        key = (member_id, topic_id)
        found[key].append((rank, float(share)))
        if rank == 1:
            totals[key] = (total, at)
    result = {}
    for key, shares in found.items():
        total, last_at = totals[key]
        shares.sort()
        score = score_of([share for _rank, share in shares]) if total >= MIN_ANSWERS else None
        result[key] = Mastery(score=score, answers=total, last_at=last_at, band=band(score))
    return result


# The matrix --------------------------------------------------------------------------------


def people(
    company,
    *,
    branch_ids: list[int] | None,
    branch: list[int] | None = None,
    position_id: int | None = None,
):
    """Approved people the viewer sees (`branch_ids`), narrowed to `branch` and a position."""
    return (
        member_queries.directory(
            company, branch_ids=branch_ids, branch=branch, position_id=position_id
        )
        .filter(status=Membership.Status.APPROVED)
        .order_by("first_name", "last_name", "pk")
    )


def cell(found: Mastery | None) -> dict:
    if found is None:
        return {"score": None, "answers": 0, "band": UNRATED, "last_at": None}
    return {
        "score": found.score,
        "answers": found.answers,
        "band": found.band,
        "last_at": found.last_at,
    }


def matrix(
    company,
    *,
    branch_ids: list[int] | None,
    branch: list[int] | None = None,
    position_id: int | None = None,
    topic_ids: list[int] | None = None,
    sort_topic: int | None = None,
) -> dict:
    """The skill matrix: `topics` (live ones, each with its average over the people rated in
    it) and `people` (each with a cell per topic). `sort_topic`: that topic's weakest first
    (unrated last); else by name."""
    topics = list(topic_services.topics(company))
    if topic_ids:
        topics = [topic for topic in topics if topic.pk in set(topic_ids)]
    members = list(people(company, branch_ids=branch_ids, branch=branch, position_id=position_id))
    found = mastery(
        company,
        member_ids=[member.pk for member in members],
        topic_ids=[topic.pk for topic in topics],
    )
    rows = []
    for member in members:
        cells = {topic.pk: cell(found.get((member.pk, topic.pk))) for topic in topics}
        rated = [value["score"] for value in cells.values() if value["score"] is not None]
        rows.append(
            {
                "member": member,
                "cells": cells,
                "average": math.floor(sum(rated) / len(rated) + 0.5) if rated else None,
                "answers": sum(value["answers"] for value in cells.values()),
            }
        )
    columns = []
    for topic in topics:
        scores = [row["cells"][topic.pk]["score"] for row in rows]
        rated = [score for score in scores if score is not None]
        columns.append(
            {
                "topic": topic,
                "average": math.floor(sum(rated) / len(rated) + 0.5) if rated else None,
                "rated": len(rated),
                "weak": sum(1 for score in rated if score < WEAK),
                "strong": sum(1 for score in rated if score >= STRONG),
            }
        )
    if sort_topic is not None and any(topic.pk == sort_topic for topic in topics):
        rows.sort(
            key=lambda row: (
                row["cells"][sort_topic]["score"] is None,
                row["cells"][sort_topic]["score"] or 0,
            )
        )
    return {"topics": columns, "people": rows}


def weakest_topics(company, *, branch_ids: list[int] | None, limit: int = 3) -> list[dict]:
    """Topics with the lowest average mastery among the people `branch_ids` covers (rated
    people only), each with how many are weak in it: for the overview card and the tutor."""
    found = matrix(company, branch_ids=branch_ids)
    rated = [column for column in found["topics"] if column["average"] is not None]
    rated.sort(key=lambda column: (column["average"], -column["weak"]))
    return rated[:limit]


def of_person(member: Membership) -> list[dict]:
    """`member`'s mastery of every topic they answered in, weakest first (unrated last)."""
    found = mastery(member.company, member_ids=[member.pk])
    names = {
        topic.pk: topic for topic in topic_services.topics(member.company, include_archived=True)
    }
    rows = [
        {"topic": names[topic_id], **cell(value)}
        for (_member, topic_id), value in found.items()
        if topic_id in names
    ]
    rows.sort(key=lambda row: (row["score"] is None, row["score"] or 0, row["topic"].name))
    return rows
