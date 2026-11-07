"""Business logic of recognition: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

**The contract other apps call** (docs/PLAN-LEARNING.md §7.4; signatures fixed, pinned by
`tests/test_contract.py`):

    award(member, reason=PointsEntry.Reason.QUIZ, key=f"quiz:attempt:{attempt.pk}")
    touch_streak(member, day)                 # the company's date of something learned

Both are safe to call from anywhere, any number of times: they do nothing while the company's
`recognition` module is off (or its points are), and `key` / `day` make a repeat a no-op.
"""

from __future__ import annotations

from datetime import date, datetime

from apps.members.models import Membership
from apps.recognition.models import PointsEntry, Streak


def award(
    member: Membership,
    *,
    reason: str,
    key: str,
    points: int | None = None,
    note: str = "",
    at: datetime | None = None,
    by: Membership | None = None,
) -> PointsEntry | None:
    """Give `member` points for one thing, once per `key` in the company.

    `points` defaults to the company's points for `reason` (`RecognitionSettings.points_table`,
    else the defaults of `apps.recognition.rules`). Returns the new entry, or None when nothing
    was given: the module or its points are off, `member` isn't approved, or `key` was already
    used. After commit it checks the badges the award may have earned and the level reached,
    and tells the person (one message, never more than one a minute). Must stay cheap: called
    in the request that finished the lesson or the quiz."""
    return None  # Package R fills this in (v8/recognition).


def touch_streak(member: Membership, day: date, *, kind: str = "learning") -> Streak | None:
    """Count `day` (the company's date) for `member`'s streak of `kind`: the run grows by one
    when the last counted day was the previous workday (days off, holidays and approved leave
    in between don't break it), stays when `day` was already counted, starts again at 1
    otherwise. Streak milestones (7, 30, 100 days) award points and badges. Returns the streak,
    or None while the module is off."""
    return None  # Package R fills this in (v8/recognition).
