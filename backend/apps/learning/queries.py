"""Read functions of learning's courses and lessons (package Q1), for other apps, the
dashboard, the tutor and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

**The contract other packages call** (docs/PLAN-LEARNING.md §10; pinned by
tests/test_contract.py): `compliance`, `open_assignments`, `courses_for_topic`,
`lessons_for_topic`, `can_open_lesson`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.db.models import QuerySet

from apps.learning.models import Assignment, Course, Lesson
from apps.members.models import Membership


@dataclass(frozen=True)
class LatePerson:
    membership_id: int
    name: str
    course_id: int
    course_title: str
    due_at: datetime
    days_late: int


@dataclass(frozen=True)
class CourseCompliance:
    course_id: int
    title: str
    mandatory: bool
    people: int  # open or finished assignments of the current cycle
    completed: int
    in_progress: int
    overdue: int


@dataclass(frozen=True)
class Compliance:
    """Mandatory training of the people in `branch_ids` (None: everyone)."""

    people: int  # people with at least one mandatory course
    completed: int  # of them, people with every mandatory course finished
    overdue_people: int
    late: list[LatePerson] = field(default_factory=list)  # most days late first
    courses: list[CourseCompliance] = field(default_factory=list)


def compliance(company, *, branch_ids: list[int] | None, now: datetime | None = None) -> Compliance:
    """Where the company's mandatory training stands (approved people only)."""
    return Compliance(people=0, completed=0, overdue_people=0)  # Package Q1 fills this in.


def open_assignments(member: Membership) -> QuerySet[Assignment]:
    """`member`'s assignments not finished, exempt or cancelled, the soonest due first."""
    return Assignment.objects.none()  # Package Q1 fills this in.


def courses_for_topic(company, topic_id: int) -> list[Course]:
    """Published courses with a step about `topic_id` (a lesson, page or quiz of the topic)."""
    return []  # Package Q1 fills this in.


def lessons_for_topic(company, topic_id: int) -> list[Lesson]:
    """Published lessons of `topic_id`, the shortest first."""
    return []  # Package Q1 fills this in.


def can_open_lesson(member: Membership, lesson: Lesson) -> bool:
    """Whether `member` may watch `lesson`: a manager of learning, someone it is published for
    (its audience), or someone with an open or finished assignment of a course holding it."""
    return False  # Package Q1 fills this in.
