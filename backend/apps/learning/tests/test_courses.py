"""Courses and assignments (docs/PLAN-LEARNING.md §4.4, §4.5): steps from lessons, pages and
quizzes, completion with a certificate number, renewals, audiences, managers' actions."""

import threading
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.knowledge import services as knowledge
from apps.knowledge.tests.factories import PageFactory
from apps.learning import conf, courses, queries
from apps.learning.models import Assignment, Attempt, CourseStep, LessonProgress, Status
from apps.learning.tests.factories import (
    AssignmentFactory,
    AttemptFactory,
    CourseFactory,
    CourseStepFactory,
    LessonFactory,
    QuizFactory,
)
from apps.learning.tests.helpers_courses import manager, turn_on
from apps.members.models import Position

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(company, member):
    turn_on(company)
    return manager(company, member)


def watched(lesson, person, at=None):
    at = at or timezone.now()
    return LessonProgress.objects.create(
        company=lesson.company,
        lesson=lesson,
        membership=person,
        percent=100,
        watched_seconds=lesson.duration_seconds,
        first_at=at,
        last_at=at,
        completed_at=at,
    )


def passed(quiz, person, at):
    return AttemptFactory(
        quiz=quiz,
        membership=person,
        state=Attempt.State.FINISHED,
        passed=True,
        percent=90,
        started_at=at - timedelta(minutes=5),
        finished_at=at,
    )


def test_a_draft_course_cant_be_assigned_and_publishing_needs_a_step(company, boss, member):
    course = courses.create_course(company, by=boss, title="Kassa qoidalari")
    with pytest.raises(DomainError, match="Publish"):
        courses.assign(course, [member(company)], by=boss)
    with pytest.raises(DomainError, match="step"):
        courses.publish_course(course, by=boss)
    courses.add_step(course, by=boss, kind="lesson", target_id=LessonFactory(company=company).pk)
    assert courses.publish_course(course, by=boss).status == Status.PUBLISHED


def test_assigning_twice_gives_one_assignment_with_the_deadline_at_the_end_of_the_day(
    company, boss, member
):
    course = CourseFactory(company=company, due_days=14)
    CourseStepFactory(course=course)
    person = member(company)
    first = courses.assign(course, [person, person], by=boss)
    assert len(first) == 1
    assert courses.assign(course, [person], by=boss) == []
    due = timezone.localtime(first[0].due_at, queries.zone(company))
    today = queries.local_day(company, timezone.now())
    assert (due.date() - today).days == 14 and (due.hour, due.minute) == (23, 59)
    assert first[0].state == Assignment.State.ASSIGNED and first[0].steps_total == 1
    assert AuditLog.objects.filter(action="learning.assigned").count() == 1


def test_people_outside_a_managers_branches_cant_be_assigned(company, member):
    turn_on(company)
    north = company.branches.first()
    south = Branch.objects.create(company=company, name="Yunusobod")
    lead = manager(company, member, branches=[north])
    mine, theirs = member(company), member(company)
    mine.branches.set([north])
    theirs.branches.set([south])
    course = CourseFactory(company=company)
    CourseStepFactory(course=course)
    assert len(courses.assign(course, [mine], by=lead)) == 1
    with pytest.raises(PermissionDenied):
        courses.assign(course, [theirs], by=lead)
    with pytest.raises(PermissionDenied):
        courses.assign(course, [member(company)], by=member(company))  # no learning.manage


def test_sequential_steps_open_one_after_another(company, boss, member):
    course = CourseFactory(company=company, sequential=True)
    first = CourseStepFactory(course=course)
    optional = CourseStepFactory(course=course, required=False)
    last = CourseStepFactory(course=course)
    person = member(company)
    assignment = courses.assign(course, [person], by=boss)[0]
    states = {row.step.pk: row for row in queries.step_states(course, person, assignment)}
    assert (states[first.pk].locked, states[optional.pk].locked, states[last.pk].locked) == (
        False,
        True,
        True,
    )
    watched(first.lesson, person)
    assignment = courses.refresh(assignment)
    states = {row.step.pk: row for row in queries.step_states(course, person, assignment)}
    # An optional step never holds the next one back.
    assert states[first.pk].done and not states[optional.pk].locked and not states[last.pk].locked
    assert (assignment.steps_done, assignment.steps_total, assignment.percent) == (1, 2, 50)
    loose = CourseFactory(company=company, sequential=False)
    CourseStepFactory(course=loose)
    CourseStepFactory(course=loose)
    assert not any(row.locked for row in queries.step_states(loose, person, None))


def test_a_quiz_step_needs_a_pass_after_the_assignment_began(company, boss, member):
    quiz = QuizFactory(company=company)
    course = CourseFactory(company=company)
    step = CourseStepFactory(course=course, kind=CourseStep.Kind.QUIZ, lesson=None, quiz=quiz)
    person = member(company)
    early = passed(quiz, person, timezone.now() - timedelta(days=1))
    assignment = courses.assign(course, [person], by=boss)[0]
    assert courses.on_attempt_finished(early) == []
    failed = passed(quiz, person, timezone.now())
    failed.passed = False
    failed.save()
    assert courses.on_attempt_finished(failed) == []
    assignment.refresh_from_db()
    assert assignment.state == Assignment.State.IN_PROGRESS  # trying counts as activity
    made = courses.on_attempt_finished(passed(quiz, person, timezone.now() + timedelta(seconds=1)))
    assert [row.step_id for row in made] == [step.pk]
    assignment.refresh_from_db()
    assert assignment.state == Assignment.State.COMPLETED
    in_progress = AttemptFactory(quiz=quiz, membership=person)  # not finished: nothing to do
    assert courses.on_attempt_finished(in_progress) == []
    assert courses.on_attempt_finished(AttemptFactory(company=company)) == []  # unrelated


def test_a_confirmed_page_is_a_done_step(company, boss, member, django_capture_on_commit_callbacks):
    page = PageFactory(space__company=company)
    course = CourseFactory(company=company)
    CourseStepFactory(course=course, kind=CourseStep.Kind.PAGE, lesson=None, page=page)
    person = member(company)
    assignment = courses.assign(course, [person], by=boss)[0]
    with django_capture_on_commit_callbacks(execute=True):
        knowledge.acknowledge(page, by=person)
    assignment.refresh_from_db()
    assert assignment.state == Assignment.State.COMPLETED


def test_what_was_done_before_the_assignment_counts_at_once(company, boss, member):
    course = CourseFactory(company=company, certificate=False)
    step = CourseStepFactory(course=course)
    person = member(company)
    watched(step.lesson, person, at=timezone.now() - timedelta(days=30))
    assignment = courses.assign(course, [person], by=boss)[0]
    assert assignment.state == Assignment.State.COMPLETED and assignment.certificate_no == ""


def test_completion_gives_a_certificate_number_points_and_a_renewal_date(
    company, boss, member, monkeypatch
):
    awarded = []
    monkeypatch.setattr(
        "apps.recognition.services.award",
        lambda member, **kwargs: awarded.append(kwargs["key"]),
    )
    row = conf.get_settings(company)
    row.certificate_prefix, row.next_certificate_number = "DRX", 41
    row.save()
    course = CourseFactory(company=company, renew_months=12)
    step = CourseStepFactory(course=course)
    person = member(company)
    assignment = courses.assign(course, [person], by=boss)[0]
    watched(step.lesson, person)
    assignment = courses.refresh(assignment)
    year = queries.local_day(company, timezone.now()).year
    assert assignment.certificate_no == f"DRX-{year}-0041"
    assert 364 <= (assignment.expires_at - assignment.completed_at).days <= 366
    assert f"course:{assignment.pk}" in awarded
    assert conf.get_settings(company).next_certificate_number == 42
    courses.refresh(assignment)  # finished once: nothing more happens
    assert conf.get_settings(company).next_certificate_number == 42


@pytest.mark.django_db(transaction=True)
def test_courses_finishing_at_the_same_moment_never_share_a_number(company, member, monkeypatch):
    monkeypatch.setattr("apps.learning.certificates.issued", lambda assignment_id: None)
    turn_on(company)
    course = CourseFactory(company=company)
    step = CourseStepFactory(course=course)
    people = [member(company) for _ in range(4)]
    rows = [AssignmentFactory(course=course, membership=person) for person in people]
    for person in people:
        watched(step.lesson, person)
    barrier = threading.Barrier(len(rows) + 1)

    def finish(assignment):
        try:
            barrier.wait()
            courses.refresh(assignment)  # and the same one twice
            courses.refresh(assignment)
        finally:
            connection.close()

    threads = [threading.Thread(target=finish, args=(row,)) for row in rows]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    numbers = list(
        Assignment.objects.filter(course=course).values_list("certificate_no", flat=True)
    )
    assert len(set(numbers)) == 4 and all(numbers)
    assert conf.get_settings(company).next_certificate_number == 5


def test_a_renewal_opens_the_next_cycle_14_days_early(company, boss, member):
    course = CourseFactory(company=company, renew_months=12, mandatory=True)
    step = CourseStepFactory(course=course)
    person = member(company)
    progress = watched(step.lesson, person)
    done = AssignmentFactory(
        course=course,
        membership=person,
        state=Assignment.State.COMPLETED,
        completed_at=timezone.now() - timedelta(days=355),
        expires_at=timezone.now() + timedelta(days=20),
    )
    assert courses.renew_due() == 0  # 20 days left: not yet
    Assignment.objects.filter(pk=done.pk).update(expires_at=timezone.now() + timedelta(days=13))
    done.refresh_from_db()
    assert courses.renew_due() == 1
    renewal = Assignment.objects.get(course=course, membership=person, cycle=2)
    assert renewal.source == Assignment.Source.RENEWAL and renewal.due_at == done.expires_at
    # The lesson starts over; the first completion date stays.
    progress.refresh_from_db()
    assert (progress.percent, progress.ranges, progress.completed_at) == (
        0,
        [],
        progress.completed_at,
    )
    assert renewal.state == Assignment.State.ASSIGNED
    assert courses.renew_due() == 0


def test_the_audience_sync_assigns_new_people_once_and_tells_them_once(
    company, boss, member, django_capture_on_commit_callbacks
):
    pharmacist = Position.objects.create(company=company, name="Pharmacist")
    cold = CourseFactory(company=company, mandatory=True, audience_all=False, title="Sovuq zanjir")
    cold.positions.set([pharmacist])
    CourseStepFactory(course=cold)
    everyone = CourseFactory(company=company, mandatory=True, title="Yangi xodim kursi")
    CourseStepFactory(course=everyone)
    newcomer = member(company, position=pharmacist)
    courier = member(company)
    with django_capture_on_commit_callbacks(execute=True):
        made = courses.sync_audiences()
    assert made >= 3  # the newcomer twice, the courier once (and anyone else of the company)
    assert Assignment.objects.filter(membership=newcomer).count() == 2
    assert Assignment.objects.filter(membership=courier).count() == 1
    assert Notification.objects.filter(recipient=newcomer, kind="learning.assigned").count() == 1
    # Exempted or cancelled people aren't given it again.
    courses.exempt(Assignment.objects.get(membership=courier), by=boss, reason="Kuryer")
    with django_capture_on_commit_callbacks(execute=True):
        assert courses.sync_audiences() == 0


def test_a_course_for_some_branches_reaches_only_their_people(company, boss, member):
    north = company.branches.first()
    south = Branch.objects.create(company=company, name="Yunusobod")
    course = CourseFactory(company=company, mandatory=True)
    course.branches.set([south])
    CourseStepFactory(course=course)
    here, there = member(company), member(company, home_branch=south)
    here.branches.set([north])
    assert {row.membership_id for row in courses.sync_course(course)} == {there.pk}


def test_removing_a_step_recounts_open_assignments_and_adding_one_reopens_nobody(
    company, boss, member
):
    course = CourseFactory(company=company, certificate=False)
    first = CourseStepFactory(course=course)
    second = CourseStepFactory(course=course)
    busy, finished = member(company), member(company)
    open_row = courses.assign(course, [busy], by=boss)[0]
    watched(first.lesson, finished)
    watched(second.lesson, finished)
    done_row = courses.assign(course, [finished], by=boss)[0]
    assert done_row.state == Assignment.State.COMPLETED
    watched(first.lesson, busy)
    courses.refresh(open_row)
    courses.remove_step(second, by=boss)
    open_row.refresh_from_db()
    assert open_row.state == Assignment.State.COMPLETED  # its last open step is gone
    courses.add_step(course, by=boss, kind="lesson", target_id=LessonFactory(company=company).pk)
    done_row.refresh_from_db()
    assert done_row.state == Assignment.State.COMPLETED


def test_exempt_cancel_and_a_new_deadline_are_audited(company, boss, member):
    course = CourseFactory(company=company)
    CourseStepFactory(course=course)
    a, b, c = (member(company) for _ in range(3))
    rows = courses.assign(course, [a, b, c], by=boss)
    with pytest.raises(DomainError):
        courses.exempt(rows[0], by=boss, reason="  ")
    courses.exempt(rows[0], by=boss, reason="Ta’tilda")
    courses.cancel(rows[1], by=boss)
    when = timezone.now() + timedelta(days=3)
    moved = courses.move_due(rows[2], by=boss, due_at=when)
    assert moved.due_at == when and moved.overdue_notices == 0
    with pytest.raises(DomainError):
        courses.cancel(rows[0], by=boss)  # already closed
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"learning.exempted", "learning.assignment_cancelled", "learning.due_changed"} <= actions
    # A fresh assignment after a cancelled one is the next cycle.
    again = courses.assign(course, [b], by=boss)
    assert again[0].cycle == 2


def test_starting_an_optional_course_on_ones_own(company, member):
    turn_on(company)
    course = CourseFactory(company=company)
    CourseStepFactory(course=course)
    person = member(company)
    assert courses.can_start(course, person)
    started = courses.start(course, person)
    assert started.source == Assignment.Source.SELF
    assert courses.start(course, person).pk == started.pk
    row = conf.get_settings(company)
    row.catalog_for_staff = False
    row.save()
    other = CourseFactory(company=company)
    CourseStepFactory(course=other)
    with pytest.raises(PermissionDenied):
        courses.start(other, person)


def test_the_contract_queries(company, boss, member):
    from apps.knowledge import topics

    cold = topics.create_topic(company, by=None, name="Sovuq zanjir")
    short = LessonFactory(company=company, duration_seconds=60)
    long = LessonFactory(company=company, duration_seconds=600)
    for lesson in (short, long):
        lesson.topics.add(cold)
    LessonFactory(company=company, status=Status.DRAFT).topics.add(cold)
    course = CourseFactory(company=company, mandatory=True, due_days=1)
    CourseStepFactory(course=course, lesson=long)
    assert queries.lessons_for_topic(company, cold.pk) == [short, long]
    assert queries.courses_for_topic(company, cold.pk) == [course]
    person = member(company)
    row = courses.assign(course, [person], by=boss)[0]
    assert list(queries.open_assignments(person)) == [row]
    Assignment.objects.filter(pk=row.pk).update(due_at=timezone.now() - timedelta(days=4))
    report = queries.compliance(company, branch_ids=None)
    assert (report.people, report.completed, report.overdue_people) == (1, 0, 1)
    assert report.late[0].membership_id == person.pk and report.late[0].days_late >= 3
    assert report.courses[0].overdue == 1
    assert queries.compliance(company, branch_ids=[]).people == 0
    draft = LessonFactory(company=company, status=Status.DRAFT, audience_all=True)
    assert not queries.can_open_lesson(person, draft)
    assert queries.can_open_lesson(boss, draft)
    hidden = LessonFactory(company=company, audience_all=False)
    CourseStepFactory(course=course, lesson=hidden)
    assert queries.can_open_lesson(person, hidden)  # through the course
