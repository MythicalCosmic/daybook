"""Courses, their steps and who takes them (package Q1; docs/PLAN-LEARNING.md §4.4 and §4.5).

**The contract other packages call** (signatures fixed, pinned by tests/test_contract.py):

    assign(course, members, by=manager, source=Assignment.Source.TUTOR, due_at=None)
    on_attempt_finished(attempt)          # quizzes call it when any attempt ends
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from apps.learning.models import Assignment, Attempt, Course, StepCompletion
from apps.members.models import Membership


def assign(
    course: Course,
    members: Iterable[Membership],
    *,
    by: Membership | None,
    source: str = Assignment.Source.MANUAL,
    due_at: datetime | None = None,
) -> list[Assignment]:
    """Give `course` to each of `members` who has no open assignment of it (not started or in
    progress) and hasn't finished the current cycle; returns the assignments made. `due_at`
    defaults to now + `course.due_days` (none without `due_days`). `by` needs `learning.manage`
    and must see each member (branch scope), except for the system (`None`). The course must be
    published. Each person hears about it once (one notification per person per burst)."""
    raise NotImplementedError("Package Q1 fills this in (v8/learning).")


def on_attempt_finished(attempt: Attempt) -> list[StepCompletion]:
    """A quiz attempt ended (finished or expired): every open assignment of the attempt's
    person whose course has a step with that quiz gets the step done when the attempt passed
    (an attempt finished before the assignment began doesn't count). Moves the assignments'
    progress, finishes courses whose required steps are all done (certificate, points), and
    returns the step completions made. Idempotent; never raises for an attempt it has nothing
    to do with."""
    return []  # Package Q1 fills this in (v8/learning).
