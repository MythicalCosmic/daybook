"""Deadlines (docs/PLAN-LEARNING.md §4.5): one reminder before, late notices on the first late
day then every 3 days (at most 3), one digest per manager, nothing on time off or before the
morning hour, nothing while the module is off."""

from datetime import date, datetime, time, timedelta

import pytest
from django.utils import timezone

from apps.inbox.models import Notification
from apps.learning import conf, queries, reminders
from apps.learning.models import Assignment
from apps.learning.tests.factories import AssignmentFactory, CourseFactory, CourseStepFactory
from apps.learning.tests.helpers_courses import manager, turn_on
from apps.members.models import Department
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db


def at(company, day: date, hour: int = 10) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=queries.zone(company))


@pytest.fixture
def course(company):
    turn_on(company)
    course = CourseFactory(company=company, mandatory=True, title="Sovuq zanjir")
    CourseStepFactory(course=course)
    return course


def due(course, person, day: date) -> Assignment:
    return AssignmentFactory(
        course=course,
        membership=person,
        due_at=datetime.combine(day, time(23, 59, 59), tzinfo=queries.zone(course.company)),
        steps_total=1,
    )


def kinds(person) -> list[str]:
    return list(
        Notification.objects.filter(recipient=person).order_by("pk").values_list("kind", flat=True)
    )


def test_one_reminder_before_the_deadline(company, course, member):
    person = member(company)
    today = date(2026, 11, 9)
    row = due(course, person, today + timedelta(days=2))
    reminders.send_reminders(now=at(company, today - timedelta(days=1)))  # 3 days left
    assert kinds(person) == []
    reminders.send_reminders(now=at(company, today))
    reminders.send_reminders(now=at(company, today, 15))
    reminders.send_reminders(now=at(company, today + timedelta(days=1)))
    assert kinds(person) == ["learning.due_soon"]
    row.refresh_from_db()
    assert row.reminded_at is not None


def test_late_notices_on_the_first_late_day_then_every_three_days_at_most_three(
    company, course, member
):
    person = member(company)
    deadline = date(2026, 11, 2)
    due(course, person, deadline)
    settings_row = conf.get_settings(company)
    settings_row.escalate_after_days = 0
    settings_row.save()
    for offset in range(1, 16):
        reminders.send_reminders(now=at(company, deadline + timedelta(days=offset)))
    sent = Notification.objects.filter(recipient=person, kind="learning.overdue").order_by("pk")
    days = [queries.local_day(company, row.created_at) for row in sent]
    assert len(days) == 3
    assert sent.first().title == "Training is late: Sovuq zanjir"


def test_a_manager_hears_once_in_one_digest(company, course, member):
    lead = manager(company, member)
    late = [member(company, first_name=name) for name in ("Alisher", "Nigora")]
    deadline = date(2026, 11, 2)
    for person in late:
        due(course, person, deadline)
    for offset in range(1, 8):
        reminders.send_reminders(now=at(company, deadline + timedelta(days=offset)))
    digests = Notification.objects.filter(recipient=lead, kind="learning.escalated")
    assert digests.count() == 1
    digest = digests.get()
    assert digest.title == "2 people are late with training"
    assert "Alisher" in digest.body and "Nigora" in digest.body
    assert all(
        Assignment.objects.get(membership=person).escalated_at is not None for person in late
    )


def test_a_department_head_hears_instead_of_every_manager(company, course, member):
    lead = manager(company, member)
    head = member(company, first_name="Bekzod")
    department = Department.objects.create(company=company, name="Chilonzor", head=head)
    person = member(company, department=department)
    due(course, person, date(2026, 11, 2))
    for offset in range(1, 8):
        reminders.send_reminders(now=at(company, date(2026, 11, 2) + timedelta(days=offset)))
    assert Notification.objects.filter(recipient=head, kind="learning.escalated").count() == 1
    assert not Notification.objects.filter(recipient=lead, kind="learning.escalated").exists()


def test_nothing_on_a_day_of_time_off_or_before_the_morning(company, course, member):
    person = member(company)
    today = date(2026, 11, 9)
    due(course, person, today + timedelta(days=1))
    TimeOff.objects.create(
        company=company,
        membership=person,
        first_day=today,
        last_day=today,
        status=TimeOff.Status.APPROVED,
    )
    reminders.send_reminders(now=at(company, today))
    assert kinds(person) == []
    reminders.send_reminders(now=at(company, today + timedelta(days=1), hour=7))  # before 09:00
    assert kinds(person) == []
    reminders.send_reminders(now=at(company, today + timedelta(days=1)))
    assert kinds(person) == ["learning.due_soon"]


def test_suspended_people_and_switched_off_companies_get_nothing(
    company, other_company, course, member
):
    person = member(company, status="suspended")
    due(course, person, date(2026, 11, 2))
    elsewhere = CourseFactory(company=other_company)  # learning is off there
    someone = member(other_company)
    due(elsewhere, someone, date(2026, 11, 2))
    assert reminders.send_reminders(now=at(company, date(2026, 11, 6))) == 0
    assert kinds(person) == kinds(someone) == []


def test_a_new_deadline_starts_the_reminders_over(company, course, member):
    from apps.learning import courses

    lead = manager(company, member)
    person = member(company)
    row = due(course, person, date(2026, 11, 2))
    reminders.send_reminders(now=at(company, date(2026, 11, 3)))
    courses.move_due(row, by=lead, due_at=at(company, date(2026, 11, 12), 23))
    row.refresh_from_db()
    assert (row.overdue_notices, row.reminded_at) == (0, None)
    reminders.send_reminders(now=at(company, date(2026, 11, 10)))
    assert kinds(person)[-1] == "learning.due_soon"


def test_the_job_runs_with_the_company_clock(company, course, member):
    company.morning_report_at = time(8, 0)
    company.save()
    person = member(company)
    due(course, person, timezone.localdate() + timedelta(days=1))
    local = at(company, timezone.localdate(), hour=8)
    assert reminders.send_reminders(now=local + timedelta(minutes=17)) == 1
