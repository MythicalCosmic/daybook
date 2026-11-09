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
from apps.learning.models import LIVE, Assignment, Course, CourseStep, Lesson, Status, Video
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


@dataclass(frozen=True)
class StepState:
    step: CourseStep
    done: bool
    done_at: datetime | None
    locked: bool


def step_states(
    course: Course, member: Membership, assignment: Assignment | None
) -> list[StepState]:
    """Each step of `course` for `member` in order: done (within `assignment`) and locked (a
    sequential course opens a step once every required step before it is done)."""
    steps = list(course.steps.select_related("lesson__video", "page", "quiz"))
    done: dict[int, datetime] = {}
    if assignment is not None:
        done = {row.step_id: row.done_at for row in assignment.completions.all()}
    states = []
    blocked = False
    for step in steps:
        finished = step.pk in done
        states.append(
            StepState(
                step=step,
                done=finished,
                done_at=done.get(step.pk),
                locked=course.sequential and blocked and not finished,
            )
        )
        if step.required and not finished:
            blocked = True
    return states


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


# The dashboard --------------------------------------------------------------------------


def person_ref(member: Membership) -> dict:
    """`{id, name, photo_url, position, branch}`: how the dashboard names a learner (no phone,
    no pay)."""
    photo = getattr(member.user, "photo", None)
    return {
        "id": member.pk,
        "name": str(member),
        "photo_url": photo.url if photo else None,
        "position": member.position.name if member.position_id else None,
        "branch": member.home_branch.name if member.home_branch_id else None,
    }


def people_in_scope(company, *, branch_ids: list[int] | None) -> QuerySet[Membership]:
    """Approved people the viewer sees (people are branch-bound by their branches)."""
    return scope.restrict(approved(company), branch_ids, field="branches").select_related(
        "user", "position", "home_branch"
    )


def assignment_row(row: Assignment, now: datetime) -> dict:
    late = is_late(row, now)
    return {
        "id": row.pk,
        "state": row.state,
        "source": row.source,
        "cycle": row.cycle,
        "percent": row.percent,
        "steps_done": row.steps_done,
        "steps_total": row.steps_total,
        "assigned_at": row.assigned_at,
        "due_at": row.due_at,
        "late": late,
        "days_late": days_late(row.company, row.due_at, now) if late else 0,
        "started_at": row.started_at,
        "last_activity_at": row.last_activity_at,
        "completed_at": row.completed_at,
        "certificate_no": row.certificate_no,
        "expires_at": row.expires_at,
        "exempt_reason": row.exempt_reason,
    }


def _newest(rows) -> dict[tuple[int, int], Assignment]:
    newest: dict[tuple[int, int], Assignment] = {}
    for row in rows.order_by("course_id", "membership_id", "-cycle"):
        newest.setdefault((row.course_id, row.membership_id), row)
    return newest


def course_stats(company, *, branch_ids: list[int] | None, now: datetime) -> dict[int, dict]:
    """{course id: {people, completed, in_progress, overdue, percent}}: the current cycle of
    the people in scope (exempt and cancelled ones don't count)."""
    people = people_in_scope(company, branch_ids=branch_ids).values("pk")
    stats: dict[int, dict] = defaultdict(
        lambda: {"people": 0, "completed": 0, "in_progress": 0, "overdue": 0, "percent": 0}
    )
    rows = Assignment.objects.filter(company=company, membership_id__in=people).select_related(
        "company"
    )
    for (course_id, _member_id), row in _newest(rows).items():
        if row.state not in HELD:
            continue
        found = stats[course_id]
        found["people"] += 1
        if row.state == Assignment.State.COMPLETED:
            found["completed"] += 1
        elif is_late(row, now):
            found["overdue"] += 1
        else:
            found["in_progress"] += 1
    for found in stats.values():
        found["percent"] = found["completed"] * 100 // found["people"] if found["people"] else 0
    return dict(stats)


EMPTY_STATS = {"people": 0, "completed": 0, "in_progress": 0, "overdue": 0, "percent": 0}


def overview(company, *, branch_ids: list[int] | None, now: datetime | None = None) -> dict:
    """The learning overview: mandatory compliance, who is late, time watched this week and by
    day (two weeks), each live course's completion, and what there is."""
    from datetime import timedelta

    from apps.learning.models import LessonProgress

    now = now or timezone.now()
    report = compliance(company, branch_ids=branch_ids, now=now)
    people = list(people_in_scope(company, branch_ids=branch_ids).values_list("pk", flat=True))
    today = local_day(company, now)
    first = today - timedelta(days=13)
    week = today - timedelta(days=today.weekday())
    seconds: dict[str, int] = defaultdict(int)
    lessons: dict[str, int] = defaultdict(int)
    since = datetime.combine(first, datetime.min.time(), tzinfo=zone(company))
    for days, done_at in LessonProgress.objects.filter(
        company=company, membership_id__in=people, last_at__gte=since
    ).values_list("days", "completed_at"):
        for key, value in (days or {}).items():
            if key >= first.isoformat():
                seconds[key] += int(value)
        if done_at is not None and done_at >= since:
            lessons[local_day(company, done_at).isoformat()] += 1
    finished: dict[str, int] = defaultdict(int)
    for done_at in Assignment.objects.filter(
        company=company,
        membership_id__in=people,
        state=Assignment.State.COMPLETED,
        completed_at__gte=since,
    ).values_list("completed_at", flat=True):
        finished[local_day(company, done_at).isoformat()] += 1
    activity = []
    for offset in range(14):
        key = (first + timedelta(days=offset)).isoformat()
        activity.append(
            {"day": key, "seconds": seconds[key], "lessons": lessons[key], "courses": finished[key]}
        )
    stats = course_stats(company, branch_ids=branch_ids, now=now)
    live = Course.objects.filter(company=company).filter(LIVE).order_by("position", "pk")
    names = {
        person.pk: person
        for person in people_in_scope(company, branch_ids=branch_ids).filter(
            pk__in=[item.membership_id for item in report.late[:10]]
        )
    }
    return {
        "compliance": {
            "people": report.people,
            "completed": report.completed,
            "overdue_people": report.overdue_people,
            "percent": report.completed * 100 // report.people if report.people else 0,
        },
        "late": [
            {
                "member": person_ref(names[item.membership_id]),
                "course": {"id": item.course_id, "title": item.course_title},
                "due_at": item.due_at,
                "days_late": item.days_late,
            }
            for item in report.late[:10]
            if item.membership_id in names
        ],
        "watched_week_seconds": sum(
            value for key, value in seconds.items() if key >= week.isoformat()
        ),
        "activity": activity,
        "courses": [
            {
                "id": course.pk,
                "title": course.title,
                "emoji": course.emoji,
                "color": course.color,
                "mandatory": course.mandatory,
                **stats.get(course.pk, EMPTY_STATS),
            }
            for course in live
        ],
        "counts": {
            "courses": Course.objects.filter(company=company)
            .exclude(status=Status.ARCHIVED)
            .count(),
            "published_courses": live.count(),
            "lessons": Lesson.objects.filter(company=company)
            .exclude(status=Status.ARCHIVED)
            .count(),
            "published_lessons": Lesson.objects.filter(company=company).filter(LIVE).count(),
            "processing_videos": Video.objects.filter(
                company=company, state__in=(Video.State.UPLOADING, Video.State.PROCESSING)
            ).count(),
        },
    }


def course_people(course: Course, *, branch_ids: list[int] | None, now: datetime) -> list[dict]:
    """Everyone with an assignment of `course` (its newest cycle), in scope: the People tab."""
    people = {
        person.pk: person
        for person in people_in_scope(course.company, branch_ids=branch_ids).filter(
            learning_assignments__course=course
        )
    }
    rows = Assignment.objects.filter(course=course, membership_id__in=list(people)).select_related(
        "company"
    )
    found = [
        {"assignment": assignment_row(row, now), "member": person_ref(people[member_id])}
        for (_course_id, member_id), row in _newest(rows).items()
    ]
    order = {"in_progress": 0, "assigned": 1, "completed": 2, "exempt": 3, "cancelled": 4}
    found.sort(
        key=lambda item: (
            not item["assignment"]["late"],
            order.get(item["assignment"]["state"], 9),
            item["member"]["name"].lower(),
        )
    )
    return found


def lesson_viewers(lesson: Lesson, *, branch_ids: list[int] | None) -> list[dict]:
    """Who watched what (§4.2): everyone the lesson is for or with it in an open course, and
    anyone who watched it, in scope: never opened, watching (percent, ranges) or watched."""
    from apps.learning.models import LessonProgress

    wanted = set(
        Assignment.objects.filter(
            company_id=lesson.company_id, state__in=OPEN, course__steps__lesson=lesson
        ).values_list("membership_id", flat=True)
    )
    if is_live(lesson):
        wanted |= set(lesson_audience(lesson).values_list("pk", flat=True))
    watched = {row.membership_id: row for row in LessonProgress.objects.filter(lesson=lesson)}
    wanted |= set(watched)
    rows = []
    for person in people_in_scope(lesson.company, branch_ids=branch_ids).filter(pk__in=wanted):
        row = watched.get(person.pk)
        state = "never" if row is None else ("watched" if row.completed_at else "watching")
        rows.append(
            {
                "member": person_ref(person),
                "state": state,
                "percent": row.percent if row else 0,
                "ranges": row.ranges if row else [],
                "watched_seconds": row.watched_seconds if row else 0,
                "spent_seconds": row.spent_seconds if row else 0,
                "sessions": row.sessions if row else 0,
                "first_at": row.first_at if row else None,
                "last_at": row.last_at if row else None,
                "completed_at": row.completed_at if row else None,
            }
        )
    order = {"watching": 0, "never": 1, "watched": 2}
    rows.sort(key=lambda item: (order[item["state"]], item["member"]["name"].lower()))
    return rows


def viewer_counts(lessons, *, branch_ids: list[int] | None) -> dict[int, dict]:
    """{lesson id: {watched, watching}} among the people in scope."""
    from apps.learning.models import LessonProgress

    if not lessons:
        return {}
    people = people_in_scope(lessons[0].company, branch_ids=branch_ids)
    counts: dict[int, dict] = defaultdict(lambda: {"watched": 0, "watching": 0})
    for lesson_id, completed_at in LessonProgress.objects.filter(
        lesson__in=lessons, membership_id__in=people.values("pk")
    ).values_list("lesson_id", "completed_at"):
        counts[lesson_id]["watched" if completed_at else "watching"] += 1
    return dict(counts)


def people_grid(
    company,
    *,
    branch_ids: list[int] | None,
    now: datetime,
    position_id: int | None = None,
    q: str = "",
    late_only: bool = False,
) -> dict:
    """Every person in scope against the mandatory courses, with each state (the People page)."""
    live = list(
        Course.objects.filter(company=company, mandatory=True).filter(LIVE).order_by("position")
    )
    people = people_in_scope(company, branch_ids=branch_ids)
    if position_id:
        people = people.filter(position_id=position_id)
    if q:
        people = people.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q))
    people = list(people.order_by("first_name", "last_name", "pk"))
    rows = Assignment.objects.filter(
        company=company, membership_id__in=[person.pk for person in people]
    ).select_related("company")
    current = _newest(rows.filter(course__in=live))
    table = []
    for person in people:
        cells: dict[str, dict | None] = {}
        done = total = late = 0
        for course in live:
            row = current.get((course.pk, person.pk))
            if row is None or row.state not in HELD:
                cells[str(course.pk)] = (
                    {
                        "assignment_id": row.pk,
                        "state": row.state,
                        "percent": row.percent,
                        "due_at": row.due_at,
                        "late": False,
                    }
                    if row is not None
                    else None
                )
                continue
            total += 1
            done += row.state == Assignment.State.COMPLETED
            overdue = is_late(row, now)
            late += overdue
            cells[str(course.pk)] = {
                "assignment_id": row.pk,
                "state": row.state,
                "percent": row.percent,
                "due_at": row.due_at,
                "late": overdue,
            }
        if late_only and not late:
            continue
        table.append(
            {
                "member": person_ref(person),
                "cells": cells,
                "done": done,
                "total": total,
                "late": late,
            }
        )
    return {
        "courses": [
            {"id": course.pk, "title": course.title, "emoji": course.emoji, "color": course.color}
            for course in live
        ],
        "rows": table,
    }


def person_learning(member: Membership, *, now: datetime) -> dict:
    """One person's training: every assignment (newest first), the lessons they watched and the
    knowledge base pages they opened."""
    from apps.knowledge.models import PageView
    from apps.learning.models import LessonProgress

    assignments = list(
        Assignment.objects.filter(membership=member)
        .select_related("course", "company")
        .order_by("-assigned_at", "-pk")
    )
    progress = list(
        LessonProgress.objects.filter(membership=member)
        .select_related("lesson")
        .order_by("-last_at")[:100]
    )
    views = list(
        PageView.objects.filter(membership=member).select_related("page").order_by("-last_at")[:100]
    )
    current = _newest(Assignment.objects.filter(membership=member))
    held = [row for row in current.values() if row.state in HELD]
    return {
        "member": person_ref(member),
        "summary": {
            "open": sum(1 for row in held if row.state in OPEN),
            "completed": sum(1 for row in held if row.state == Assignment.State.COMPLETED),
            "late": sum(1 for row in held if is_late(row, now)),
            "certificates": sum(1 for row in assignments if row.certificate_no),
            "watched_seconds": sum(row.spent_seconds for row in progress),
            "lessons_watched": sum(1 for row in progress if row.completed_at),
        },
        "assignments": [
            {
                **assignment_row(row, now),
                "course": {
                    "id": row.course_id,
                    "title": row.course.title,
                    "emoji": row.course.emoji,
                    "mandatory": row.course.mandatory,
                },
            }
            for row in assignments
        ],
        "lessons": [
            {
                "lesson": {
                    "id": row.lesson_id,
                    "title": row.lesson.title,
                    "emoji": row.lesson.emoji,
                },
                "percent": row.percent,
                "ranges": row.ranges,
                "completed_at": row.completed_at,
                "last_at": row.last_at,
                "spent_seconds": row.spent_seconds,
                "sessions": row.sessions,
            }
            for row in progress
        ],
        "pages": [
            {
                "page": {"id": row.page_id, "title": row.page.title, "emoji": row.page.emoji},
                "visits": row.visits,
                "seconds": row.seconds,
                "scrolled": row.scrolled,
                "version": row.version,
                "last_at": row.last_at,
            }
            for row in views
            if row.page.archived_at is None
        ],
    }
