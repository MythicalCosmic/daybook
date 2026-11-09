"""Courses, their steps and who takes them (package Q1; docs/PLAN-LEARNING.md §4.4 and §4.5).

**The contract other packages call** (signatures fixed, pinned by tests/test_contract.py):

    assign(course, members, by=manager, source=Assignment.Source.TUTOR, due_at=None)
    on_attempt_finished(attempt)          # quizzes call it when any attempt ends

A course is steps in order: lessons, knowledge base pages and quizzes. Each person's run through
it is an **assignment** (one per cycle). A step is done when:

- a lesson: the person watched it (`LessonProgress.completed_at`, any time);
- a page: they confirmed its current version (the knowledge base's acknowledgement);
- a quiz: an attempt passed that finished after the assignment began (`on_attempt_finished`).

A renewal (the next cycle of a course that renews) asks for it all again: its lessons start
over for the person (their watched ranges; the first completion date stays) and a page counts
once opened again after the renewal began.

`refresh(assignment)` recounts from those facts, so a lesson watched or a page read before the
assignment existed counts at once, and finishes the course when every required step is done:
the certificate number (`<prefix>-<year>-<number>`, the settings row's counter under a row
lock), `expires_at` for courses that renew, points, the certificate notice.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from dateutil.relativedelta import relativedelta
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch, Company, Feature
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.knowledge import topics as knowledge_topics
from apps.knowledge.models import Page, PageAck, PageView
from apps.learning import conf, media, notify_courses, queries
from apps.learning.audit_actions import CourseAction
from apps.learning.models import (
    LIVE,
    Assignment,
    Attempt,
    Course,
    CourseStep,
    LearningSettings,
    Lesson,
    LessonProgress,
    Quiz,
    Status,
    StepCompletion,
)
from apps.learning.services import ensure_manager
from apps.members.models import Membership, Position
from apps.members.queries import in_scope

logger = logging.getLogger(__name__)

PULSE_KEY = "learning.courses"
MAX_TITLE = 200
RENEW_AHEAD = timedelta(days=14)
CHANGEABLE = {
    "title",
    "emoji",
    "color",
    "description",
    "mandatory",
    "audience_all",
    "position_ids",
    "branch_ids",
    "due_days",
    "renew_months",
    "sequential",
    "certificate",
}


# Helpers --------------------------------------------------------------------------------


def _record(action: str, target, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=target.company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )
    company_id = target.company_id
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))


def _clean_title(title: str) -> str:
    title = " ".join((title or "").split())
    if not title:
        raise DomainError(_("Give it a title."))
    if len(title) > MAX_TITLE:
        raise DomainError(_("Keep the title under %(n)d characters.") % {"n": MAX_TITLE})
    return title


def _clean_emoji(emoji: str) -> str:
    emoji = (emoji or "").strip()
    if len(emoji) > 16:
        raise DomainError(_("Pick one emoji."))
    return emoji


def _clean_color(color: str) -> str:
    color = (color or "").strip()
    if color and color not in knowledge_topics.COLORS:
        raise DomainError(_("Pick one of the colours."))
    return color


def _clean_days(value, *, most: int, message: str) -> int | None:
    if value in (None, "", 0):
        return None
    value = int(value)
    if not 1 <= value <= most:
        raise DomainError(message)
    return value


def _positions(company_id: int, ids) -> list[Position]:
    wanted = {int(pk) for pk in ids or ()}
    found = list(Position.objects.filter(company_id=company_id, pk__in=wanted))
    if len(found) != len(wanted):
        raise DomainError(_("Pick positions of this company."))
    return found


def _branches(company_id: int, ids) -> list[Branch]:
    wanted = {int(pk) for pk in ids or ()}
    found = list(Branch.objects.filter(company_id=company_id, pk__in=wanted))
    if len(found) != len(wanted):
        raise DomainError(_("Pick branches of this company."))
    return found


def _ensure_sees(by: Membership | None, person: Membership) -> None:
    if by is not None and not in_scope(by, person):
        raise PermissionDenied(_("You can only do this for people you see."))


def end_of_day(company, day) -> datetime:
    """The last second of `day` in the company's time."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=queries.zone(company))


def due_from(course: Course, start: datetime) -> datetime | None:
    """`due_days` after `start`, at the end of that day in the company's time."""
    if not course.due_days:
        return None
    day = queries.local_day(course.company, start) + timedelta(days=course.due_days)
    return end_of_day(course.company, day)


# Courses --------------------------------------------------------------------------------


def _apply(course: Course, changes: dict) -> None:
    if "title" in changes:
        course.title = _clean_title(changes["title"])
    if "emoji" in changes:
        course.emoji = _clean_emoji(changes["emoji"])
    if "color" in changes:
        course.color = _clean_color(changes["color"])
    if "description" in changes:
        course.description = (changes["description"] or "").strip()[:2000]
    for flag in ("mandatory", "audience_all", "sequential", "certificate"):
        if flag in changes:
            setattr(course, flag, bool(changes[flag]))
    if "due_days" in changes:
        course.due_days = _clean_days(
            changes["due_days"], most=365, message=_("Give 1–365 days to finish, or none.")
        )
    if "renew_months" in changes:
        course.renew_months = _clean_days(
            changes["renew_months"], most=60, message=_("Renew after 1–60 months, or never.")
        )


def _check_audience(course: Course) -> None:
    if not course.audience_all and not course.positions.exists():
        raise DomainError(_("Pick who the course is for: everyone or some positions."))


@transaction.atomic
def create_course(company, *, by: Membership | None, title: str, **fields) -> Course:
    """A draft course; `fields` are any of `CHANGEABLE`."""
    media.ensure_on(company)
    ensure_manager(by)
    unknown = set(fields) - CHANGEABLE
    if unknown:
        raise ValueError(f"Can't set {sorted(unknown)} on a course.")
    top = Course.objects.filter(company=company).aggregate(top=Max("position"))["top"]
    course = Course(
        company=company,
        status=Status.DRAFT,
        position=(top or 0) + 1,
        created_by=by,
        updated_by=by,
    )
    _apply(course, {"title": title, **fields})
    course.save()
    course.positions.set(_positions(company.pk, fields.get("position_ids")))
    course.branches.set(_branches(company.pk, fields.get("branch_ids")))
    _check_audience(course)
    _record(CourseAction.COURSE_CREATED, course, by, title=course.title)
    return course


@transaction.atomic
def update_course(course: Course, *, by: Membership | None, **changes) -> Course:
    ensure_manager(by)
    unknown = set(changes) - CHANGEABLE
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} on a course.")
    course = Course.objects.select_for_update().get(pk=course.pk)
    _apply(course, changes)
    course.updated_by = by
    course.save()
    if "position_ids" in changes:
        course.positions.set(_positions(course.company_id, changes["position_ids"]))
    if "branch_ids" in changes:
        course.branches.set(_branches(course.company_id, changes["branch_ids"]))
    _check_audience(course)
    _record(CourseAction.COURSE_CHANGED, course, by, changed=sorted(changes))
    if queries.is_live(course) and course.mandatory:
        transaction.on_commit(lambda: sync_course(course))
    return course


@transaction.atomic
def publish_course(course: Course, *, by: Membership | None) -> Course:
    """Open the course; a mandatory one reaches its audience at once."""
    ensure_manager(by)
    course = Course.objects.select_for_update().get(pk=course.pk)
    if course.status == Status.PUBLISHED:
        return course
    if course.status == Status.ARCHIVED:
        raise DomainError(_("This course is archived. Restore it first."))
    if not course.steps.exists():
        raise DomainError(_("Add at least one step before publishing the course."))
    course.status = Status.PUBLISHED
    course.published_at = timezone.now()
    course.updated_by = by
    course.save(update_fields=["status", "published_at", "updated_by", "updated_at"])
    _record(CourseAction.COURSE_PUBLISHED, course, by)
    if course.mandatory:
        transaction.on_commit(lambda: sync_course(course))
    return course


@transaction.atomic
def archive_course(course: Course, *, by: Membership | None) -> Course:
    """Hide the course from everyone; assignments stay (and come back with it)."""
    ensure_manager(by)
    course = Course.objects.select_for_update().get(pk=course.pk)
    if course.status != Status.ARCHIVED:
        course.status = Status.ARCHIVED
        course.archived_at = timezone.now()
        course.updated_by = by
        course.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
        _record(CourseAction.COURSE_ARCHIVED, course, by)
    return course


@transaction.atomic
def restore_course(course: Course, *, by: Membership | None) -> Course:
    ensure_manager(by)
    course = Course.objects.select_for_update().get(pk=course.pk)
    if course.status == Status.ARCHIVED:
        course.status = Status.PUBLISHED if course.published_at else Status.DRAFT
        course.archived_at = None
        course.updated_by = by
        course.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
        _record(CourseAction.COURSE_CHANGED, course, by, changed=["status"])
    return course


@transaction.atomic
def reorder_courses(company, ids: list[int], *, by: Membership | None) -> None:
    ensure_manager(by)
    rows = {row.pk: row for row in Course.objects.filter(company=company, pk__in=ids)}
    for index, pk in enumerate(ids):
        course = rows.get(int(pk))
        if course is not None and course.position != index:
            course.position = index
            course.save(update_fields=["position", "updated_at"])
    if rows:
        transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_KEY))


# Steps ----------------------------------------------------------------------------------


def step_target(company_id: int, kind: str, target_id: int):
    """The lesson, page or quiz a new step points at: of this company and not archived."""
    if kind == CourseStep.Kind.LESSON:
        found = Lesson.objects.filter(
            company_id=company_id, pk=target_id, archived_at__isnull=True
        ).first()
    elif kind == CourseStep.Kind.PAGE:
        found = Page.objects.filter(
            company_id=company_id, pk=target_id, archived_at__isnull=True
        ).first()
    elif kind == CourseStep.Kind.QUIZ:
        found = Quiz.objects.filter(
            company_id=company_id, pk=target_id, archived_at__isnull=True
        ).first()
    else:
        raise DomainError(_("A step is a lesson, a page or a quiz."))
    if found is None or getattr(found, "status", None) == Status.ARCHIVED:
        raise DomainError(_("Pick a lesson, page or quiz of this company that isn't archived."))
    return found


def _recount_open(course: Course) -> None:
    for assignment in Assignment.objects.filter(course=course, state__in=queries.OPEN):
        refresh(assignment)


@transaction.atomic
def add_step(
    course: Course, *, by: Membership | None, kind: str, target_id: int, required: bool = True
) -> CourseStep:
    ensure_manager(by)
    course = Course.objects.select_for_update().get(pk=course.pk)
    if course.status == Status.ARCHIVED:
        raise DomainError(_("This course is archived. Restore it first."))
    target = step_target(course.company_id, kind, int(target_id))
    if CourseStep.objects.filter(course=course, **{kind: target}).exists():
        raise DomainError(_("This is already a step of the course."))
    top = course.steps.aggregate(top=Max("position"))["top"]
    step = CourseStep.objects.create(
        company_id=course.company_id,
        course=course,
        kind=kind,
        position=(top if top is not None else -1) + 1,
        required=bool(required),
        **{kind: target},
    )
    _record(CourseAction.COURSE_CHANGED, course, by, changed=["steps"], added=step.pk)
    _recount_open(course)
    return step


@transaction.atomic
def update_step(step: CourseStep, *, by: Membership | None, required: bool) -> CourseStep:
    ensure_manager(by)
    step = (
        CourseStep.objects.select_for_update(of=("self",)).select_related("course").get(pk=step.pk)
    )
    if step.required != bool(required):
        step.required = bool(required)
        step.save(update_fields=["required", "updated_at"])
        _record(CourseAction.COURSE_CHANGED, step.course, by, changed=["steps"], step=step.pk)
        _recount_open(step.course)
    return step


@transaction.atomic
def remove_step(step: CourseStep, *, by: Membership | None) -> None:
    """Take a step out; open assignments recount (its completions no longer count)."""
    ensure_manager(by)
    step = (
        CourseStep.objects.select_for_update(of=("self",)).select_related("course").get(pk=step.pk)
    )
    course = step.course
    if course.status == Status.PUBLISHED and course.steps.count() == 1:
        raise DomainError(_("A published course needs at least one step."))
    removed = step.pk
    step.delete()
    _record(CourseAction.COURSE_CHANGED, course, by, changed=["steps"], removed=removed)
    _recount_open(course)


@transaction.atomic
def reorder_steps(course: Course, ids: list[int], *, by: Membership | None) -> None:
    ensure_manager(by)
    course = Course.objects.select_for_update().get(pk=course.pk)
    steps = {step.pk: step for step in course.steps.all()}
    if set(int(pk) for pk in ids) != set(steps):
        raise DomainError(_("Give every step of the course, in the new order."))
    for index, pk in enumerate(ids):
        step = steps[int(pk)]
        if step.position != index:
            step.position = index
            step.save(update_fields=["position", "updated_at"])
    _record(CourseAction.COURSE_CHANGED, course, by, changed=["steps"])
    _recount_open(course)


# Who has done which step ------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    at: datetime
    version: int | None = None  # the page version confirmed


def _facts(assignment: Assignment, steps: list[CourseStep]) -> dict[int, Fact]:
    """Steps the person has done in fact (a lesson watched, a page confirmed), by step id."""
    member_id = assignment.membership_id
    renewal = assignment.source == Assignment.Source.RENEWAL
    found: dict[int, Fact] = {}
    lessons = {step.lesson_id: step for step in steps if step.kind == CourseStep.Kind.LESSON}
    if lessons:
        threshold = conf.get_settings(assignment.course.company).completion_percent
        for row in LessonProgress.objects.filter(
            membership_id=member_id, lesson_id__in=list(lessons)
        ):
            if renewal:
                if row.percent >= threshold and row.last_at >= assignment.assigned_at:
                    found[lessons[row.lesson_id].pk] = Fact(row.last_at)
            elif row.completed_at is not None:
                found[lessons[row.lesson_id].pk] = Fact(row.completed_at)
    pages = {step.page_id: step for step in steps if step.kind == CourseStep.Kind.PAGE}
    if pages:
        current = dict(Page.objects.filter(pk__in=list(pages)).values_list("pk", "ack_version"))
        newest: dict[int, PageAck] = {}
        for ack in PageAck.objects.filter(
            membership_id=member_id, page_id__in=list(pages)
        ).order_by("page_id", "-version"):
            newest.setdefault(ack.page_id, ack)
        seen_since = set()
        if renewal:
            seen_since = set(
                PageView.objects.filter(
                    membership_id=member_id,
                    page_id__in=list(pages),
                    last_at__gte=assignment.assigned_at,
                ).values_list("page_id", flat=True)
            )
        for page_id, ack in newest.items():
            if ack.version < current.get(page_id, ack.version + 1):
                continue
            if renewal and page_id not in seen_since:
                continue
            found[pages[page_id].pk] = Fact(ack.at, ack.version)
    return found


def refresh(assignment: Assignment, *, now=None, activity: bool = False) -> Assignment:
    """Recount an open assignment from what the person has done; `activity` (they watched,
    read or answered something of the course) moves it to in progress. Finishes the course
    when every required step is done."""
    now = now or timezone.now()
    with transaction.atomic():
        assignment = (
            Assignment.objects.select_for_update(of=("self",))
            .select_related("course__company", "membership__user")
            .get(pk=assignment.pk)
        )
        if assignment.state not in queries.OPEN:
            return assignment
        steps = list(assignment.course.steps.all())
        done = {row.step_id for row in assignment.completions.all()}
        made = []
        for step_id, fact in _facts(assignment, steps).items():
            if step_id in done:
                continue
            try:
                with transaction.atomic():
                    StepCompletion.objects.create(
                        company_id=assignment.company_id,
                        assignment=assignment,
                        step_id=step_id,
                        done_at=fact.at,
                    )
            except IntegrityError:
                pass  # recorded by a report at the same moment
            done.add(step_id)
            made.append((step_id, fact))
        required = [step for step in steps if step.required]
        assignment.steps_total = len(required)
        assignment.steps_done = sum(1 for step in required if step.pk in done)
        assignment.percent = (
            assignment.steps_done * 100 // assignment.steps_total if assignment.steps_total else 0
        )
        if activity or made:
            if assignment.state == Assignment.State.ASSIGNED:
                assignment.state = Assignment.State.IN_PROGRESS
                assignment.started_at = assignment.started_at or now
            assignment.last_activity_at = now
        finished = assignment.steps_total > 0 and assignment.steps_done == assignment.steps_total
        if finished:
            _complete(assignment, now)
        assignment.save()
        _award_pages(assignment, steps, made)
        if made or finished or activity:
            company_id = assignment.company_id
            transaction.on_commit(lambda: pulse.bump(company_id, PULSE_KEY))
    return assignment


def _award_pages(assignment: Assignment, steps: list[CourseStep], made) -> None:
    from apps.recognition import services as recognition

    pages = {step.pk: step.page_id for step in steps if step.kind == CourseStep.Kind.PAGE}
    for step_id, fact in made:
        if step_id in pages and fact.version is not None:
            member = assignment.membership
            recognition.award(
                member,
                reason="page",
                key=f"page:{pages[step_id]}:v{fact.version}:{member.pk}",
                at=fact.at,
            )


def next_certificate_number(company, now: datetime) -> str:
    """`<prefix>-<year>-<number>`, the next number of the company's counter (row lock: two
    courses finishing at the same moment never share one)."""
    row = conf.get_settings(company)
    row = LearningSettings.objects.select_for_update().get(pk=row.pk)
    number = row.next_certificate_number
    row.next_certificate_number = number + 1
    row.save(update_fields=["next_certificate_number"])
    year = queries.local_day(company, now).year
    return f"{row.certificate_prefix or 'SRT'}-{year}-{number:04d}"


def _complete(assignment: Assignment, now: datetime) -> None:
    """Every required step is done (the row is locked by the caller)."""
    from apps.learning import certificates
    from apps.recognition import services as recognition

    course = assignment.course
    company = course.company
    assignment.state = Assignment.State.COMPLETED
    assignment.completed_at = now
    assignment.percent = 100
    assignment.started_at = assignment.started_at or now
    if course.certificate and conf.get_settings(company).certificates:
        assignment.certificate_no = next_certificate_number(company, now)
    if course.renew_months:
        assignment.expires_at = now + relativedelta(months=course.renew_months)
    recognition.award(assignment.membership, reason="course", key=f"course:{assignment.pk}", at=now)
    if assignment.certificate_no:
        assignment_id = assignment.pk
        transaction.on_commit(lambda: certificates.issued(assignment_id))


# Events from lessons, pages and quizzes ---------------------------------------------------


def _open_with(member_id: int, **step) -> list[Assignment]:
    return list(
        Assignment.objects.filter(membership_id=member_id, state__in=queries.OPEN)
        .filter(course__status=Status.PUBLISHED, course__archived_at__isnull=True)
        .filter(**{f"course__steps__{key}": value for key, value in step.items()})
        .distinct()
    )


def on_lesson_progress(member: Membership, lesson: Lesson, *, now=None) -> None:
    """The person watched some of `lesson` (or finished it): the courses holding it move."""
    for assignment in _open_with(member.pk, lesson=lesson):
        refresh(assignment, now=now, activity=True)


def on_page_ack(ack: PageAck) -> None:
    """The person confirmed a page (the knowledge base's acknowledgement)."""
    if not conf.is_on(ack.page.company):
        return
    for assignment in _open_with(ack.membership_id, page_id=ack.page_id):
        refresh(assignment, activity=True)


def on_attempt_finished(attempt: Attempt) -> list[StepCompletion]:
    """A quiz attempt ended (finished or expired): every open assignment of the attempt's
    person whose course has a step with that quiz gets the step done when the attempt passed
    (an attempt finished before the assignment began doesn't count). Moves the assignments'
    progress, finishes courses whose required steps are all done (certificate, points), and
    returns the step completions made. Idempotent; never raises for an attempt it has nothing
    to do with."""
    if attempt.state not in (Attempt.State.FINISHED, Attempt.State.EXPIRED):
        return []
    made: list[StepCompletion] = []
    for assignment in _open_with(attempt.membership_id, quiz_id=attempt.quiz_id):
        with transaction.atomic():
            locked = Assignment.objects.select_for_update().get(pk=assignment.pk)
            counts = (
                attempt.passed
                and attempt.finished_at is not None
                and attempt.finished_at >= locked.assigned_at
            )
            if counts:
                for step in locked.course.steps.filter(quiz_id=attempt.quiz_id):
                    completion, created = StepCompletion.objects.get_or_create(
                        assignment=locked,
                        step=step,
                        defaults={
                            "company_id": locked.company_id,
                            "done_at": attempt.finished_at,
                            "attempt": attempt,
                        },
                    )
                    if created:
                        made.append(completion)
            refresh(locked, now=attempt.finished_at, activity=True)
    return made


# Assignments ----------------------------------------------------------------------------


def latest(course: Course, member: Membership, *, lock: bool = False) -> Assignment | None:
    rows = Assignment.objects.filter(course=course, membership=member)
    if lock:
        rows = rows.select_for_update()
    return rows.order_by("-cycle").first()


def holds(row: Assignment | None, now: datetime) -> bool:
    """Whether `row` already covers the person: open, or finished and not run out."""
    if row is None:
        return False
    if row.state in queries.OPEN:
        return True
    return row.state == Assignment.State.COMPLETED and not (
        row.expires_at is not None and row.expires_at <= now
    )


def _create(
    course: Course,
    member: Membership,
    *,
    by: Membership | None,
    source: str,
    due_at: datetime | None,
    now: datetime,
    cycle: int,
) -> Assignment | None:
    try:
        with transaction.atomic():
            return Assignment.objects.create(
                company_id=course.company_id,
                course=course,
                membership=member,
                cycle=cycle,
                state=Assignment.State.ASSIGNED,
                source=source,
                assigned_by=by,
                assigned_at=now,
                due_at=due_at,
                steps_total=course.steps.filter(required=True).count(),
            )
    except IntegrityError:
        return None  # made at the same moment by another run


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
    if not conf.is_on(course.company):
        raise PermissionDenied(_("Training isn't switched on for this company."))
    ensure_manager(by)
    if not queries.is_live(course):
        raise DomainError(_("Publish the course before assigning it."))
    if source not in Assignment.Source.values:
        raise ValueError(f"Unknown assignment source {source!r}.")
    now = timezone.now()
    people = list({member.pk: member for member in members}.values())
    for member in people:
        if member.company_id != course.company_id:
            raise DomainError(_("Pick people of this company."))
        _ensure_sees(by, member)
    made: list[Assignment] = []
    with transaction.atomic():
        for member in people:
            if member.status != Membership.Status.APPROVED:
                continue
            last = latest(course, member, lock=True)
            if holds(last, now):
                continue
            row = _create(
                course,
                member,
                by=by,
                source=source,
                due_at=due_at or due_from(course, now),
                now=now,
                cycle=(last.cycle + 1) if last else 1,
            )
            if row is not None:
                made.append(row)
        if made:
            _record(
                CourseAction.ASSIGNED,
                course,
                by,
                people=len(made),
                source=source,
                members=[row.membership_id for row in made][:50],
            )
            notify_courses.assigned(made)
    return [refresh(row, now=now) for row in made]


def can_start(course: Course, member: Membership, *, now=None) -> bool:
    """Whether the person may start `course` on their own (`POST …/start/`)."""
    now = now or timezone.now()
    if not queries.is_live(course) or not queries.in_course_audience(member, course):
        return False
    last = latest(course, member)
    if last is not None and last.state in queries.OPEN:
        return False
    if holds(last, now):
        return False
    return course.mandatory or conf.get_settings(course.company).catalog_for_staff


def start(course: Course, member: Membership) -> Assignment:
    """The person starts a course of their audience (or continues the one they have)."""
    last = latest(course, member)
    if last is not None and last.state in queries.OPEN:
        return last
    if not can_start(course, member):
        raise PermissionDenied(_("This course isn't open to you."))
    source = Assignment.Source.AUDIENCE if course.mandatory else Assignment.Source.SELF
    made = assign(course, [member], by=None, source=source)
    if made:
        return made[0]
    return latest(course, member)


def _closing(assignment: Assignment, by: Membership | None) -> Assignment:
    ensure_manager(by)
    locked = (
        Assignment.objects.select_for_update(of=("self",))
        .select_related("membership", "course")
        .get(pk=assignment.pk)
    )
    _ensure_sees(by, locked.membership)
    if locked.state not in queries.OPEN:
        raise DomainError(_("This training is already closed."))
    return locked


@transaction.atomic
def exempt(assignment: Assignment, *, by: Membership | None, reason: str) -> Assignment:
    """Excuse the person from this course (a reason is required)."""
    reason = " ".join((reason or "").split())[:200]
    if not reason:
        raise DomainError(_("Say why they are excused."))
    row = _closing(assignment, by)
    row.state = Assignment.State.EXEMPT
    row.exempt_reason = reason
    row.closed_by = by
    row.save(update_fields=["state", "exempt_reason", "closed_by", "updated_at"])
    _record(CourseAction.EXEMPTED, row, by, reason=reason, course=row.course_id)
    return row


@transaction.atomic
def cancel(assignment: Assignment, *, by: Membership | None) -> Assignment:
    """Take the course back from the person."""
    row = _closing(assignment, by)
    row.state = Assignment.State.CANCELLED
    row.closed_by = by
    row.save(update_fields=["state", "closed_by", "updated_at"])
    _record(CourseAction.ASSIGNMENT_CANCELLED, row, by, course=row.course_id)
    return row


@transaction.atomic
def move_due(
    assignment: Assignment, *, by: Membership | None, due_at: datetime | None
) -> Assignment:
    """A new deadline (none: no deadline); its reminders start over."""
    row = _closing(assignment, by)
    old = row.due_at
    row.due_at = due_at
    row.reminded_at = None
    row.overdue_notices = 0
    row.escalated_at = None
    row.save(
        update_fields=["due_at", "reminded_at", "overdue_notices", "escalated_at", "updated_at"]
    )
    _record(
        CourseAction.DUE_CHANGED,
        row,
        by,
        course=row.course_id,
        old=old.isoformat() if old else None,
        new=due_at.isoformat() if due_at else None,
    )
    return row


def remind(course: Course, *, by: Membership, member_ids: list[int] | None = None) -> int:
    """A manager reminds the people of `course` with open training (those of `member_ids`)."""
    ensure_manager(by)
    rows = Assignment.objects.filter(course=course, state__in=queries.OPEN).select_related(
        "membership__user", "membership__company", "course"
    )
    if member_ids is not None:
        rows = rows.filter(membership_id__in=member_ids)
    sent = 0
    with transaction.atomic():
        people = [row for row in rows if in_scope(by, row.membership)]
        for row in people:
            if row.membership.status == Membership.Status.APPROVED:
                sent += notify_courses.remind(row.membership, [row], by=by)
        if people:
            _record(CourseAction.REMINDED, course, by, people=sent)
    return sent


# Jobs -----------------------------------------------------------------------------------


def companies_on():
    return Company.objects.filter(is_active=True, features__contains=[Feature.LEARNING])


def sync_course(course: Course) -> list[Assignment]:
    """Everyone in a mandatory course's audience who has never had it gets it."""
    course = Course.objects.select_related("company").get(pk=course.pk)
    if not course.mandatory or not queries.is_live(course) or not conf.is_on(course.company):
        return []
    had = set(Assignment.objects.filter(course=course).values_list("membership_id", flat=True))
    people = [person for person in queries.course_audience(course) if person.pk not in had]
    if not people:
        return []
    return assign(course, people, by=None, source=Assignment.Source.AUDIENCE)


def sync_audiences() -> int:
    """Hourly: mandatory courses reach the people who joined, or changed position or branch.
    Each person hears once about everything they got in this run."""
    made = 0
    for company in companies_on():
        with notify_courses.collecting():
            for course in Course.objects.filter(company=company, mandatory=True).filter(LIVE):
                try:
                    made += len(sync_course(course))
                except Exception:
                    logger.exception("Syncing the audience of course %s failed", course.pk)
    return made


def renew_due(now=None) -> int:
    """Daily: a course that renews opens its next cycle 14 days before the last one runs out,
    due when it runs out."""
    now = now or timezone.now()
    made = 0
    for company in companies_on():
        rows = (
            Assignment.objects.filter(
                company=company,
                state=Assignment.State.COMPLETED,
                expires_at__isnull=False,
                expires_at__lte=now + RENEW_AHEAD,
                course__renew_months__isnull=False,
            )
            .filter(course__status=Status.PUBLISHED, course__archived_at__isnull=True)
            .select_related("course__company", "membership")
        )
        with notify_courses.collecting():
            for row in rows:
                renewed = _renew(row, now)
                made += renewed is not None
    return made


def _renew(row: Assignment, now: datetime) -> Assignment | None:
    course, member = row.course, row.membership
    if member.status != Membership.Status.APPROVED:
        return None
    if course.mandatory and not queries.in_course_audience(member, course):
        return None
    with transaction.atomic():
        last = latest(course, member, lock=True)
        if last is None or last.pk != row.pk:
            return None  # a later cycle exists
        made = _create(
            course,
            member,
            by=None,
            source=Assignment.Source.RENEWAL,
            due_at=row.expires_at,
            now=now,
            cycle=row.cycle + 1,
        )
        if made is None:
            return None
        lesson_ids = list(
            course.steps.filter(kind=CourseStep.Kind.LESSON).values_list("lesson_id", flat=True)
        )
        # The lessons start over for the person; when they first finished them stays.
        LessonProgress.objects.filter(membership=member, lesson_id__in=lesson_ids).update(
            ranges=[], watched_seconds=0, percent=0, position=0
        )
        _record(
            CourseAction.ASSIGNED,
            course,
            None,
            people=1,
            source=Assignment.Source.RENEWAL,
            members=[member.pk],
        )
        notify_courses.assigned([made])
    return refresh(made, now=now)


# Settings -------------------------------------------------------------------------------

SETTINGS_FIELDS = {
    "completion_percent",
    "max_speed_percent",
    "remind_before_days",
    "escalate_after_days",
    "certificates",
    "certificate_prefix",
    "catalog_for_staff",
    "storage_limit_mb",
}


@transaction.atomic
def update_settings(company, *, by: Membership | None, **changes) -> LearningSettings:
    """The Settings > Training panel's fields (the daily question's belong to the quizzes)."""
    ensure_manager(by)
    unknown = set(changes) - SETTINGS_FIELDS
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} in the training settings.")
    row = conf.get_settings(company)
    row = LearningSettings.objects.select_for_update().get(pk=row.pk)
    for name, value in changes.items():
        setattr(row, name, value.upper() if name == "certificate_prefix" else value)
    row.save()
    audit.record(
        CourseAction.SETTINGS_CHANGED,
        company_id=company.pk,
        actor=by.user if by is not None else None,
        target=row,
        changed=sorted(changes),
    )
    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE_KEY))
    return row
