"""Read functions of learning's courses and lessons (package Q1), for other apps, the
dashboard, the tutor and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

**The contract other packages call** (docs/PLAN-LEARNING.md §10; pinned by
tests/test_contract.py): `compliance`, `open_assignments`, `courses_for_topic`,
`lessons_for_topic`, `can_open_lesson`.

Who a course or lesson is for (its **audience**, §4.5): everyone (`audience_all`) or the
holders of its positions; a course narrows that to its branches when it has any (a person's
branches are `Membership.branches` and the home branch). Approved members only.
"""

from __future__ import annotations

import zoneinfo
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.learning import conf
from apps.learning.models import LIVE, Assignment, Course, Lesson, Status, Video
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

OPEN = (Assignment.State.ASSIGNED, Assignment.State.IN_PROGRESS)
# Assignments that hold someone to a course (open, or finished in this cycle).
HELD = (*OPEN, Assignment.State.COMPLETED)


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


# Time -----------------------------------------------------------------------------------


def zone(company) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(company.timezone)


def local_day(company, moment: datetime) -> date:
    return timezone.localtime(moment, zone(company)).date()


def days_late(company, due_at: datetime, now: datetime) -> int:
    """Whole company days since the deadline's day (0 on the day itself)."""
    return (local_day(company, now) - local_day(company, due_at)).days


def is_late(assignment: Assignment, now: datetime) -> bool:
    return assignment.state in OPEN and assignment.due_at is not None and assignment.due_at < now


# Audiences ------------------------------------------------------------------------------


def approved(company) -> QuerySet[Membership]:
    return Membership.objects.filter(company=company, status=Membership.Status.APPROVED)


def course_audience(course: Course) -> QuerySet[Membership]:
    """Approved people the course is for."""
    people = approved(course.company_id)
    if not course.audience_all:
        people = people.filter(position__in=course.positions.all())
    branch_ids = list(course.branches.values_list("pk", flat=True))
    if branch_ids:
        people = people.filter(
            Q(branches__in=branch_ids) | Q(home_branch_id__in=branch_ids)
        ).distinct()
    return people


def in_course_audience(member: Membership, course: Course) -> bool:
    if member.status != Membership.Status.APPROVED or member.company_id != course.company_id:
        return False
    if not course.audience_all and not course.positions.filter(pk=member.position_id).exists():
        return False
    branch_ids = set(course.branches.values_list("pk", flat=True))
    if not branch_ids:
        return True
    mine = set(member.branches.values_list("pk", flat=True))
    if member.home_branch_id is not None:
        mine.add(member.home_branch_id)
    return bool(mine & branch_ids)


def lesson_audience(lesson: Lesson) -> QuerySet[Membership]:
    people = approved(lesson.company_id)
    if not lesson.audience_all:
        people = people.filter(position__in=lesson.positions.all())
    return people


def in_lesson_audience(member: Membership, lesson: Lesson) -> bool:
    if lesson.audience_all:
        return True
    return (
        member.position_id is not None and lesson.positions.filter(pk=member.position_id).exists()
    )


def is_live(item) -> bool:
    return item.status == Status.PUBLISHED and item.archived_at is None


# The contract ---------------------------------------------------------------------------


def current_assignments(company, member_ids=None) -> dict[tuple[int, int], Assignment]:
    """{(course id, member id): the newest cycle's assignment} for live courses."""
    rows = Assignment.objects.filter(company=company).filter(
        course__status=Status.PUBLISHED, course__archived_at__isnull=True
    )
    if member_ids is not None:
        rows = rows.filter(membership_id__in=member_ids)
    newest: dict[tuple[int, int], Assignment] = {}
    for row in rows.select_related("course").order_by("course_id", "membership_id", "-cycle"):
        newest.setdefault((row.course_id, row.membership_id), row)
    return newest


def compliance(company, *, branch_ids: list[int] | None, now: datetime | None = None) -> Compliance:
    """Where the company's mandatory training stands (approved people only)."""
    now = now or timezone.now()
    people = {
        person.pk: person
        for person in scope.restrict(approved(company), branch_ids, field="branches")
    }
    current = current_assignments(company, list(people))
    per_person: dict[int, list[Assignment]] = defaultdict(list)
    per_course: dict[int, list[Assignment]] = defaultdict(list)
    late: list[LatePerson] = []
    for (course_id, member_id), row in current.items():
        if row.state not in HELD:
            continue  # exempt or cancelled: not theirs to do
        per_course[course_id].append(row)
        if not row.course.mandatory:
            continue
        per_person[member_id].append(row)
        if is_late(row, now):
            person = people[member_id]
            late.append(
                LatePerson(
                    membership_id=member_id,
                    name=str(person),
                    course_id=course_id,
                    course_title=row.course.title,
                    due_at=row.due_at,
                    days_late=days_late(company, row.due_at, now),
                )
            )
    late.sort(key=lambda item: (-item.days_late, item.name.lower(), item.course_title))
    courses = []
    for rows in per_course.values():
        course = rows[0].course
        overdue = sum(1 for row in rows if is_late(row, now))
        completed = sum(1 for row in rows if row.state == Assignment.State.COMPLETED)
        courses.append(
            CourseCompliance(
                course_id=course.pk,
                title=course.title,
                mandatory=course.mandatory,
                people=len(rows),
                completed=completed,
                in_progress=len(rows) - completed - overdue,
                overdue=overdue,
            )
        )
    courses.sort(key=lambda item: (not item.mandatory, item.title.lower()))
    return Compliance(
        people=len(per_person),
        completed=sum(
            1
            for rows in per_person.values()
            if all(row.state == Assignment.State.COMPLETED for row in rows)
        ),
        overdue_people=len({item.membership_id for item in late}),
        late=late,
        courses=courses,
    )


def open_assignments(member: Membership) -> QuerySet[Assignment]:
    """`member`'s assignments not finished, exempt or cancelled, the soonest due first."""
    return (
        Assignment.objects.filter(membership=member, state__in=OPEN)
        .filter(course__status=Status.PUBLISHED, course__archived_at__isnull=True)
        .select_related("course")
        .order_by(F("due_at").asc(nulls_last=True), "assigned_at", "pk")
    )


def courses_for_topic(company, topic_id: int) -> list[Course]:
    """Published courses with a step about `topic_id` (a lesson, page or quiz of the topic)."""
    about = (
        Q(steps__lesson__topics=topic_id)
        | Q(steps__page__topics=topic_id)
        | Q(steps__quiz__topics=topic_id)
    )
    return list(
        Course.objects.filter(company=company)
        .filter(LIVE)
        .filter(about)
        .distinct()
        .order_by("position", "pk")
    )


def watchable(lessons: QuerySet[Lesson]) -> QuerySet[Lesson]:
    """Lessons whose video can be played now (a link, or an upload that is ready)."""
    return lessons.filter(
        Q(source=Lesson.Source.YOUTUBE) & ~Q(youtube_id="")
        | Q(source=Lesson.Source.UPLOAD, video__state=Video.State.READY)
    )


def lessons_for_topic(company, topic_id: int) -> list[Lesson]:
    """Published lessons of `topic_id`, the shortest first."""
    lessons = Lesson.objects.filter(company=company).filter(LIVE).filter(topics=topic_id)
    return list(watchable(lessons).distinct().order_by("duration_seconds", "pk"))


def can_open_lesson(member: Membership, lesson: Lesson) -> bool:
    """Whether `member` may watch `lesson`: a manager of learning, someone it is published for
    (its audience), or someone with an open or finished assignment of a course holding it."""
    if member.company_id != lesson.company_id or member.status != Membership.Status.APPROVED:
        return False
    if not conf.is_on(member.company):
        return False
    if member.has_perm(Perm.LEARNING_MANAGE):
        return True
    if is_live(lesson) and in_lesson_audience(member, lesson):
        return True
    return Assignment.objects.filter(
        membership=member,
        state__in=HELD,
        course__status=Status.PUBLISHED,
        course__archived_at__isnull=True,
        course__steps__lesson=lesson,
    ).exists()
