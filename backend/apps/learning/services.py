"""Business logic of learning: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

The services live in modules by subject (docs/PLAN-LEARNING.md §10):

- package Q1 (courses, lessons, videos): `courses.py` (courses, steps, assignments, step
  completions), `lessons.py`, `media.py` (uploads, processing, serving), `progress.py` (who
  watched what), `certificates.py`, `reminders.py`;
- package Q2 (quizzes, the tutor): `quizzes.py` (questions, quizzes), `attempts.py` and
  `grading.py`, `daily.py` (the question of the day), `checks.py` (regular checks),
  `skills.py` (mastery), `suggestions.py`, `drafting.py` (questions from a page or a lesson).

This module only keeps what both share.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from apps.members.models import Membership
from apps.members.permissions import Perm


def ensure_manager(by: Membership | None) -> None:
    """Only holders of `learning.manage` (or the system) make and change learning content."""
    if by is not None and not by.has_perm(Perm.LEARNING_MANAGE):
        raise PermissionDenied(_("Only people who manage training can do this."))
