"""What points earn: the levels reached and the badges (docs/PLAN-LEARNING.md §7.2, §7.3).

`check(member)` runs after every award (a Celery job after commit, `tasks.check_member`) and in
the nightly sweep; it is idempotent: every level and badge is a row under a unique constraint,
so it comes once however often the check runs or races. New rows wait for the bot
(`notified_at`) and the app's celebration (`seen_at`).

The learning badges read learning's facts: the points ledger for lessons, tests and courses
(every award leaves a row, worth 0 when the company gives nothing for it), and learning's own
rows for the question of the day, early finishes and topic mastery (read only).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from apps.members.models import Membership
from apps.recognition import badges as catalogue
from apps.recognition import conf, rules
from apps.recognition.models import BadgeAward, Kudos, LevelUp, PointsEntry, Streak

logger = logging.getLogger(__name__)

KUDOS_FOR_BADGE = 10
DAILY_FOR_BADGE = 10
COURSES_FOR_GOLD = 5
EXPERT_SCORE = 90
EXPERT_ANSWERS = 10
EARLY_DAYS = 3
WEEK_TASKS = 5


def total_points(member: Membership) -> int:
    return (
        PointsEntry.objects.filter(membership=member).aggregate(total=Sum("points"))["total"] or 0
    )


def check(member: Membership, *, now: datetime | None = None) -> tuple[list, list]:
    """Record the levels and badges `member` has earned and hasn't got yet; returns the new
    (LevelUp rows, BadgeAward rows)."""
    if member.status != Membership.Status.APPROVED or not conf.is_on(member.company):
        return [], []
    now = now or timezone.now()
    return reach_levels(member, now=now), earn_badges(member, now=now)


def reach_levels(member: Membership, *, now: datetime) -> list[LevelUp]:
    number = rules.level_number(total_points(member))
    have = set(LevelUp.objects.filter(membership=member).values_list("number", flat=True))
    made = []
    for level in range(2, number + 1):
        if level in have:
            continue
        row = _create(
            LevelUp, company_id=member.company_id, membership=member, number=level, reached_at=now
        )
        if row is not None:
            made.append(row)
    return made


def give(member: Membership, key: str, ref: str = "", *, now: datetime) -> BadgeAward | None:
    """One badge of the catalogue, once (None when they have it already)."""
    if key not in catalogue.CATALOGUE:
        raise ValueError(f"Unknown badge {key!r}.")
    row = _create(
        BadgeAward,
        company_id=member.company_id,
        membership=member,
        badge=key,
        ref=str(ref)[:32],
        awarded_at=now,
    )
    if row is not None:
        _badge_points(member, row)
    return row


def earn_badges(member: Membership, *, now: datetime) -> list[BadgeAward]:
    earned = set(BadgeAward.objects.filter(membership=member).values_list("badge", "ref"))
    wanted: list[tuple[str, str]] = []

    def want(key: str, ref: str = "") -> None:
        if (key, ref) not in earned:
            wanted.append((key, ref))

    counts = dict(
        PointsEntry.objects.filter(membership=member)
        .values("reason")
        .annotate(n=Count("pk"))
        .values_list("reason", "n")
    )
    if counts.get(PointsEntry.Reason.LESSON):
        want("first_lesson")
    if counts.get(PointsEntry.Reason.QUIZ):
        want("first_quiz")
    if counts.get(PointsEntry.Reason.QUIZ_PERFECT):
        want("perfect_score")
    courses = counts.get(PointsEntry.Reason.COURSE, 0)
    if courses >= 1:
        want("course_finisher")
    if courses >= COURSES_FOR_GOLD:
        want("five_courses")

    best = (
        Streak.objects.filter(membership=member, kind="learning")
        .values_list("best", flat=True)
        .first()
        or 0
    )
    for length in rules.STREAK_MILESTONES:
        if best >= length:
            want(f"streak_{length}")

    shown = Kudos.objects.filter(hidden_at__isnull=True)
    if shown.filter(from_member=member).count() >= KUDOS_FOR_BADGE:
        want("helper")
    if shown.filter(to_member=member).count() >= KUDOS_FOR_BADGE:
        want("thanked")

    for key, ref in _learning_badges(member, earned):
        want(key, ref)

    made = []
    for key, ref in wanted:
        row = give(member, key, ref, now=now)
        if row is not None:
            made.append(row)
    return made


def _learning_badges(member: Membership, earned: set) -> list[tuple[str, str]]:
    """The badges learning's own rows decide, while the company runs learning."""
    from apps.learning import conf as learning_conf

    if not learning_conf.is_on(member.company):
        return []
    from apps.learning import skills
    from apps.learning.models import Assignment, DailyQuestion

    found = []
    if ("daily_10", "") not in earned:
        right = DailyQuestion.objects.filter(membership=member, correct=True).count()
        if right >= DAILY_FOR_BADGE:
            found.append(("daily_10", ""))
    if ("early_bird", "") not in earned:
        early = Assignment.objects.filter(
            membership=member,
            course__mandatory=True,
            completed_at__isnull=False,
            completed_at__lte=F("assigned_at") + timedelta(days=EARLY_DAYS),
        ).exists()
        if early:
            found.append(("early_bird", ""))
    try:
        scores = skills.mastery(member.company, member_ids=[member.pk])
    except Exception:  # learning's own bug must not stop the person's other badges
        logger.exception("Mastery failed for membership %s", member.pk)
        scores = {}
    for (member_id, topic_id), score in scores.items():
        if member_id != member.pk or score.score is None:
            continue
        if score.score >= EXPERT_SCORE and score.answers >= EXPERT_ANSWERS:
            found.append(("topic_expert", str(topic_id)))
    return found


def on_time_week(member: Membership, monday: date) -> bool:
    """Every shared task (routine work and tasks given by hand) due from `monday` to Sunday was
    finished on time, and there were at least WEEK_TASKS of them."""
    from zoneinfo import ZoneInfo

    from apps.tasks.models import Task

    tz = ZoneInfo(member.company.timezone)
    start = datetime.combine(monday, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=7)
    rows = list(
        Task.objects.filter(
            assignee=member,
            kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED),
            due_at__gte=start,
            due_at__lt=end,
        )
        .exclude(status=Task.Status.CANCELLED)
        .values_list("status", "completed_at", "due_at")
    )
    if len(rows) < WEEK_TASKS:
        return False
    finished = (Task.Status.DONE, Task.Status.REVIEW)
    return all(
        status in finished and completed_at is not None and completed_at <= due_at
        for status, completed_at, due_at in rows
    )


def _badge_points(member: Membership, row: BadgeAward) -> None:
    """Points for a badge, when the company gives any (none by default)."""
    from apps.recognition import services

    points = rules.points_for(conf.get_settings(member.company), "badge")
    if points:
        services.award(
            member,
            reason=PointsEntry.Reason.BADGE,
            key=f"badge:{row.pk}",
            points=points,
            at=row.awarded_at,
        )


def _create(model, **fields):
    try:
        with transaction.atomic():
            return model.objects.create(**fields)
    except IntegrityError:
        return None
