"""Who watched what: the lesson player's reports (docs/PLAN-LEARNING.md §4.2).

The player reports every 10 s while playing, on pause, on seek and on leaving:
`{session, position, duration, ranges, playing}`, where `ranges` are the stretches of the video
played since its previous report (media seconds) and `session` is a random id per opening.

- Each range is clipped to `[0, duration]` and rounded to whole seconds (a boundary two
  reports share rounds the same way, so back-to-back reports stay back to back).
- A report counts at most `elapsed x max_speed_percent / 100 + 5` seconds of playing, where
  `elapsed` is the time since the person's previous report (capped at `FIRST_WINDOW` for the
  first report of a new session, so a report sent the day after can't claim the whole night).
  The excess is cut from the end of the newest range: skipping ahead, playing faster than
  twice the speed or a forged report can't fill the bar faster than real time at that speed.
- What is left joins the person's ranges (merged, sorted): `watched_seconds` is their union,
  `percent` = floor(watched / duration x 100), `position` is where to resume (the start again
  within 5 s of the end), `spent_seconds` grows by the seconds counted, `sessions` counts the
  openings.
- At `completion_percent` (90) the lesson is **watched**: `completed_at` is set once and never
  unset, the points (`lesson`) come, and every open course holding the lesson moves.

YouTube lessons learn their duration from the first report (when the lesson has none). A video
still being processed can't be watched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.learning import conf, lessons, media, queries
from apps.learning.models import Lesson, LessonProgress
from apps.members.models import Membership

SLACK = 5
FIRST_WINDOW = 30
RESUME_TAIL = 5
MAX_RANGES = 50
# A learning day for the streak: at least this many seconds watched (or a lesson finished).
STREAK_SECONDS = 60


@dataclass(frozen=True)
class Reported:
    percent: int
    position: int
    completed: bool
    completed_now: bool
    points: int | None


def _seconds(value) -> int | None:
    """A media time as whole seconds (half up), or None for anything that isn't a number."""
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(number):
        return None
    return math.floor(number + 0.5)


def clip(ranges, duration: int) -> list[list[int]]:
    """The report's ranges as whole seconds within `[0, duration]`, in the order played."""
    found = []
    for item in list(ranges or [])[:MAX_RANGES]:
        if not isinstance(item, list | tuple) or len(item) != 2:
            continue
        start, end = _seconds(item[0]), _seconds(item[1])
        if start is None or end is None:
            continue
        start, end = max(0, start), min(duration, end)
        if end > start:
            found.append([start, end])
    return found


def merge(ranges) -> list[list[int]]:
    """Sorted and merged; ranges that touch join."""
    merged: list[list[int]] = []
    for start, end in sorted([list(item) for item in ranges]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def length(ranges) -> int:
    return sum(end - start for start, end in merge(ranges))


def trim(ranges: list[list[int]], allowance: int) -> list[list[int]]:
    """At most `allowance` seconds played in all: the excess is cut from the end of the newest
    range, then the one before, and so on."""
    ranges = [list(item) for item in ranges]
    for index in range(len(ranges) - 1, -1, -1):
        if length(ranges) <= allowance:
            break
        start, end = ranges[index]
        low, high = start, end  # the furthest end that still fits
        while low < high:
            middle = (low + high + 1) // 2
            ranges[index][1] = middle
            if length(ranges) <= allowance:
                low = middle
            else:
                high = middle - 1
        ranges[index][1] = low
    return [item for item in ranges if item[1] > item[0]]


def _duration(lesson: Lesson, reported) -> int:
    """The lesson's length; a YouTube lesson without one takes the player's (kept)."""
    if lesson.source == Lesson.Source.UPLOAD:
        return lesson.video.duration_seconds if lesson.video else 0
    if lesson.duration_seconds:
        return lesson.duration_seconds
    seconds = _seconds(reported)
    if seconds is None or not 0 < seconds <= media.MAX_DURATION_SECONDS:
        return 0
    with transaction.atomic():
        locked = Lesson.objects.select_for_update().get(pk=lesson.pk)
        if not locked.duration_seconds:
            locked.duration_seconds = seconds
            locked.save(update_fields=["duration_seconds", "updated_at"])
        return locked.duration_seconds


def report(
    lesson: Lesson,
    member: Membership,
    *,
    session: str,
    position,
    duration,
    ranges,
    playing: bool = False,
    now=None,
) -> Reported:
    """Take one report of the player (see the module's docstring)."""
    from apps.learning import courses
    from apps.recognition import services as recognition

    now = now or timezone.now()
    if lessons.processing(lesson):
        raise DomainError(_("This video is still being prepared. Try again in a few minutes."))
    if not lessons.ready_for_watching(lesson):
        raise DomainError(_("This lesson has no video to watch yet."))
    settings_row = conf.get_settings(lesson.company)
    total = _duration(lesson, duration)
    session = str(session or "")[:40]
    with transaction.atomic():
        row, created = LessonProgress.objects.select_for_update().get_or_create(
            lesson=lesson,
            membership=member,
            defaults={"company_id": lesson.company_id, "first_at": now, "last_at": now},
        )
        new_session = created or session != row.last_session
        if row.last_report_at is None:
            elapsed = FIRST_WINDOW
        else:
            elapsed = max(0.0, (now - row.last_report_at).total_seconds())
            if new_session:
                elapsed = min(elapsed, FIRST_WINDOW)
        allowance = math.floor(elapsed * settings_row.max_speed_percent / 100 + SLACK)
        played = trim(clip(ranges, total), allowance) if total else []
        counted = length(played)
        union = merge([*row.ranges, *played])
        row.ranges = union
        row.watched_seconds = length(union)
        row.percent = min(100, row.watched_seconds * 100 // total) if total else 0
        resume = _seconds(position) or 0
        resume = max(0, min(resume, total)) if total else 0
        if total and resume >= total - RESUME_TAIL:
            resume = 0
        row.position = resume
        row.spent_seconds += counted
        if new_session:
            row.sessions += 1
        row.last_session = session
        row.last_report_at = now
        if counted:
            row.last_at = now
        completed_now = False
        if row.completed_at is None and total and row.percent >= settings_row.completion_percent:
            row.completed_at = now
            completed_now = True
        row.save()
        points = None
        if completed_now:
            entry = recognition.award(
                member, reason="lesson", key=f"lesson:{lesson.pk}:{member.pk}", at=now
            )
            points = entry.points if entry is not None else None
        if counted or completed_now:
            courses.on_lesson_progress(member, lesson, now=now)
        if completed_now:
            company_id = lesson.company_id
            transaction.on_commit(lambda: pulse.bump(company_id, media.PULSE_KEY))
    _streak(member, counted, now, finished=completed_now)
    return Reported(
        percent=row.percent,
        position=row.position,
        completed=row.completed_at is not None,
        completed_now=completed_now,
        points=points,
    )


def _streak(member: Membership, seconds: int, now, *, finished: bool) -> None:
    """A learning day for the streak (recognition): a minute watched, or a lesson finished."""
    from apps.recognition import services as recognition

    if seconds <= 0 and not finished:
        return
    day = queries.local_day(member.company, now)
    key = f"learning:watched:{member.pk}:{day.isoformat()}"
    if cache.get(f"{key}:streak"):
        return
    cache.add(key, 0, timeout=2 * 24 * 3600)
    try:
        total = cache.incr(key, seconds)
    except ValueError:
        total = seconds
    if (total >= STREAK_SECONDS or finished) and cache.add(f"{key}:streak", 1, 2 * 24 * 3600):
        recognition.touch_streak(member, day)
