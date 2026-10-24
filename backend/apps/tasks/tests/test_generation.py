from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Proof, Task, TaskTemplate, Weekday
from apps.tasks.tests.factories import TaskTemplateFactory

pytestmark = pytest.mark.django_db

MONDAY = date(2030, 10, 21)  # far enough ahead that deadlines are in the future


def daily_tasks():
    return Task.objects.filter(kind=Task.Kind.DAILY)


def test_template_creates_one_task_per_person(company, member):
    ali, vali = member.registered(company), member.registered(company)
    template = TaskTemplateFactory(
        company=company, assignees=[ali, vali], proof=Proof.PHOTO, needs_confirmation=True
    )

    generate_daily_tasks(company, MONDAY)

    tasks = daily_tasks()
    assert {task.assignee for task in tasks} == {ali, vali}
    task = tasks.first()
    assert task.template == template
    assert task.for_date == MONDAY
    assert task.proof == Proof.PHOTO
    assert task.needs_confirmation
    expected_due = datetime.combine(MONDAY, time(18, 0), tzinfo=ZoneInfo(company.timezone))
    assert task.due_at == expected_due


def test_running_again_creates_nothing_new(company, member):
    TaskTemplateFactory(company=company, assignees=[member.registered(company)])

    generate_daily_tasks(company, MONDAY)
    generate_daily_tasks(company, MONDAY)

    assert daily_tasks().count() == 1


def test_weekdays_are_respected(company, member):
    TaskTemplateFactory(
        company=company,
        assignees=[member.registered(company)],
        weekdays=[Weekday.TUESDAY, Weekday.WEDNESDAY],
    )

    generate_daily_tasks(company, MONDAY)
    assert not daily_tasks().exists()

    generate_daily_tasks(company, MONDAY + timedelta(days=1))
    assert daily_tasks().count() == 1


def test_positions_bring_everyone_holding_them(company, member):
    cashier = PositionFactory(company=company, name="Cashier")
    maya = member.registered(company, position=cashier)
    member.registered(company)  # no position
    TaskTemplateFactory(company=company, positions=[cashier])

    generate_daily_tasks(company, MONDAY)

    assert [task.assignee for task in daily_tasks()] == [maya]


def test_only_registered_members_get_tasks(company, member):
    unregistered = member(company)
    left = member.registered(company, status=Membership.Status.LEFT)
    TaskTemplateFactory(company=company, assignees=[unregistered, left])

    generate_daily_tasks(company, MONDAY)

    assert not daily_tasks().exists()


def test_inactive_templates_are_skipped(company, member):
    TaskTemplateFactory(company=company, assignees=[member.registered(company)], is_active=False)

    generate_daily_tasks(company, MONDAY)

    assert not daily_tasks().exists()


def test_no_task_when_the_template_appeared_after_todays_deadline(company, member):
    today = timezone.localdate(timezone=ZoneInfo(company.timezone))
    template = TaskTemplateFactory(company=company, assignees=[member.registered(company)])
    TaskTemplate.objects.filter(pk=template.pk).update(
        created_at=datetime.combine(today, time(19, 0), tzinfo=ZoneInfo(company.timezone))
    )

    generate_daily_tasks(company, today)

    assert not daily_tasks().exists()


def test_no_task_for_someone_who_registered_after_the_deadline(company, member):
    deadline = datetime.combine(MONDAY, time(18, 0), tzinfo=ZoneInfo(company.timezone))
    late_joiner = member.registered(company, onboarded_at=deadline + timedelta(minutes=5))
    TaskTemplateFactory(company=company, assignees=[late_joiner])

    generate_daily_tasks(company, MONDAY)

    assert not daily_tasks().exists()


def test_new_routine_work_moves_the_dashboards_pulse(company, member, monkeypatch):
    """Audit X-13: bulk_create sends no post_save, so generation bumps the pulse itself."""
    TaskTemplateFactory(company=company, assignees=[member.registered(company)])
    bumped = []
    monkeypatch.setattr(
        "apps.tasks.generation.pulse.bump", lambda company_id, key: bumped.append((company_id, key))
    )

    generate_daily_tasks(company, MONDAY)

    assert bumped == [(company.pk, "tasks.tasks")]
