"""Task changes keep the reminder schedule right; plus the API around reminders."""

from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.companies.services import create_company
from apps.core.exceptions import DomainError
from apps.reminders.models import ReminderPolicy
from apps.reminders.policies import default_policy
from apps.tasks import services
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory

pytestmark = pytest.mark.django_db


def client_for(membership) -> APIClient:
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(membership.user).access_token}"
    )
    return api


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def in_hours(hours: float):
    return timezone.now() + timedelta(hours=hours)


def test_every_company_starts_with_a_default_policy():
    company = create_company(name="Fresh", slug="fresh")

    policy = ReminderPolicy.objects.get(company=company)
    assert policy.is_default
    assert policy.repeat_every_minutes == 20
    assert policy.escalate_after == 3


def test_new_task_is_reminded_at_its_deadline(manager, worker):
    due = in_hours(3)

    task = services.create_task(by=manager, assignee=worker, title="Call", due_at=due)

    assert task.next_reminder_at == due


def test_heads_up_policy_moves_the_first_reminder_earlier(company, manager, worker):
    policy = default_policy(company.pk)
    policy.heads_up_minutes = 30
    policy.save()
    due = in_hours(3)

    task = services.create_task(by=manager, assignee=worker, title="Call", due_at=due)

    assert task.next_reminder_at == due - timedelta(minutes=30)


def test_new_deadline_starts_the_count_over(manager, worker):
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        due_at=in_hours(-1),
        reminders_sent=4,
        escalated_at=timezone.now(),
    )
    later = in_hours(5)

    task = services.update_task(task, by=manager, due_at=later)

    assert (task.reminders_sent, task.escalated_at, task.next_reminder_at) == (0, None, later)


@pytest.mark.parametrize("finish", ["complete", "cancel"])
def test_finished_work_stops_the_reminders(manager, worker, finish):
    task = TaskFactory(
        assignee=worker, created_by=manager, due_at=in_hours(1), next_reminder_at=in_hours(1)
    )

    if finish == "complete":
        task = services.complete_task(task, by=worker)
    else:
        task = services.cancel_task(task, by=manager)

    assert task.next_reminder_at is None


def test_sent_back_past_its_deadline_reminders_pick_up_again(manager, worker):
    task = TaskFactory(
        assignee=worker, created_by=manager, due_at=in_hours(-2), status=Task.Status.REVIEW
    )

    task = services.return_task(task, by=manager, reason="Redo it")

    assert abs(task.next_reminder_at - in_hours(20 / 60)) < timedelta(seconds=30)


def test_snooze_holds_reminders_and_is_limited(manager, worker):
    task = TaskFactory(
        assignee=worker, created_by=manager, due_at=in_hours(-1), next_reminder_at=in_hours(-1)
    )

    task = services.snooze_task(task, by=worker)

    assert abs(task.next_reminder_at - in_hours(0.5)) < timedelta(seconds=30)
    assert task.snoozed_until == task.next_reminder_at
    with pytest.raises(DomainError, match="No snoozes left"):
        services.snooze_task(task, by=worker)


def test_only_the_assignee_snoozes(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager, due_at=in_hours(-1))

    with pytest.raises(PermissionDenied):
        services.snooze_task(task, by=manager)


def test_generated_daily_tasks_are_scheduled_with_the_templates_contact(company, member, worker):
    shift_lead = member.registered(company)
    TaskTemplateFactory(company=company, assignees=[worker], escalate_to=shift_lead)
    day = date(2030, 10, 21)

    generate_daily_tasks(company, day)

    task = Task.objects.get(kind=Task.Kind.DAILY)
    assert task.next_reminder_at == task.due_at
    assert task.escalate_to == shift_lead


# API


def test_task_detail_explains_the_reminders(company, manager, worker):
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        due_at=in_hours(-1),
        next_reminder_at=in_hours(0.2),
        reminders_sent=1,
    )
    url = f"/api/v1/companies/{company.pk}/tasks/"

    detail = client_for(worker).get(f"{url}{task.pk}/").data["reminder"]
    listed = client_for(worker).get(url).data["results"][0]["reminder"]

    assert detail["every_minutes"] == 20
    assert detail["sent"] == 1
    assert detail["escalate_after"] == 3
    assert detail["escalate_to"] == str(manager)
    assert detail["snoozes_left"] == 1
    assert listed is None


def test_snooze_endpoint(company, manager, worker):
    task = TaskFactory(
        assignee=worker, created_by=manager, due_at=in_hours(-1), next_reminder_at=in_hours(-1)
    )

    response = client_for(worker).post(f"/api/v1/companies/{company.pk}/tasks/{task.pk}/snooze/")

    assert response.status_code == 200
    assert response.data["reminder"]["snoozes_left"] == 0
    assert response.data["reminder"]["snoozed_until"] is not None


def test_policies_need_the_reminders_permission(company, member, worker):
    owner = member.registered(company, "Owner")
    url = f"/api/v1/companies/{company.pk}/reminder-policies/"

    assert client_for(worker).get(url).status_code == 403

    [policy] = client_for(owner).get(url).data
    response = client_for(owner).patch(
        f"{url}{policy['id']}/", {"repeat_every_minutes": 10}, format="json"
    )
    assert response.data["repeat_every_minutes"] == 10
    assert client_for(owner).delete(f"{url}{policy['id']}/").status_code == 400

    created = client_for(owner).post(
        url, {"name": "Gentle", "repeat_every_minutes": 60}, format="json"
    )
    assert created.status_code == 201
    assert created.data["is_default"] is False


def test_summary_shows_quiet_hours(company, worker):
    data = client_for(worker).get(f"/api/v1/companies/{company.pk}/summary/").data

    assert (data["quiet_from"], data["quiet_until"]) == ("22:00:00", "08:00:00")
