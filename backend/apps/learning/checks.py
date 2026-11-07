"""Regular checks: "mandatory stuff asking" (package Q2; docs/PLAN-LEARNING.md §4.9).

A check sends its quiz to its audience every week (a weekday) or month (a day 1 to 28) at `at`,
to answer within `answer_within_hours`. Each sending is a round with an entry per person.

    rows = checks.my_checks(member)          # the app's list: open rounds and the last closed
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.learning.models import CheckEntry
from apps.members.models import Membership

# Closed rounds the app still lists, and for how long.
RECENT_CLOSED = 5
RECENT_DAYS = 14


def my_checks(member: Membership, now: datetime | None = None) -> list[dict]:
    """`member`'s check entries: the open rounds (soonest due first), then the last closed ones."""
    now = now or timezone.now()
    rows = CheckEntry.objects.filter(membership=member).select_related(
        "check_round__regular_check", "attempt"
    )
    open_rows = rows.filter(
        check_round__closed_at__isnull=True,
        check_round__starts_at__lte=now,
        check_round__due_at__gt=now,
    ).order_by("check_round__due_at", "pk")
    closed = (
        rows.filter(check_round__starts_at__gte=now - timedelta(days=RECENT_DAYS))
        .filter(Q(check_round__closed_at__isnull=False) | Q(check_round__due_at__lte=now))
        .order_by("-check_round__due_at", "-pk")[:RECENT_CLOSED]
    )
    return [card(entry) for entry in [*open_rows, *closed]]


def card(entry: CheckEntry) -> dict:
    attempt = entry.attempt
    done = attempt is not None and attempt.finished_at is not None
    check = entry.check_round.regular_check
    return {
        "entry_id": entry.pk,
        "title": check.title,
        "quiz_id": check.quiz_id,
        "due_at": entry.check_round.due_at,
        "done": done,
        "passed": bool(attempt.passed) if done else None,
    }
