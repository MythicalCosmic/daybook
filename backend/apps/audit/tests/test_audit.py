from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.models import AuditLog
from apps.groups import services as groups
from apps.groups.models import GroupEvent
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members import services as members
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory
from apps.reminders.policies import default_policy
from apps.tasks import services as tasks
from apps.tasks.models import Task, TaskTemplate
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

Action = AuditLog.Action


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


@pytest.fixture
def worker(company, member):
    return member.registered(company)


def client_for(membership: Membership) -> APIClient:
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(membership.user).access_token}"
    )
    return api


def entries() -> list[tuple]:
    return [
        (entry.action, entry.actor_id, entry.target, entry.details)
        for entry in AuditLog.objects.order_by("pk")
    ]


def test_join_decisions_are_logged(company, manager, owner):
    approved = MembershipFactory(company=company, first_name="Aziz")
    rejected = MembershipFactory(company=company, first_name="Bekzod")

    members.approve(approved, by=manager.user)
    members.reject(rejected, by=manager.user)
    members.block(approved, by=owner.user)  # blocking takes members.manage

    assert entries() == [
        (Action.MEMBER_APPROVED, manager.user_id, "Aziz", {}),
        (Action.MEMBER_REJECTED, manager.user_id, "Bekzod", {}),
        (Action.MEMBER_BLOCKED, owner.user_id, "Aziz", {}),
    ]
    assert {entry.company_id for entry in AuditLog.objects.all()} == {company.pk}


def test_a_refused_action_leaves_no_trace(company, worker):
    request = MembershipFactory(company=company)

    with pytest.raises(PermissionDenied):
        members.approve(request, by=worker.user)

    assert not AuditLog.objects.exists()


def test_managing_someones_work_is_logged(company, manager, worker):
    due = timezone.now() + timedelta(hours=2)
    task = tasks.create_task(by=manager, title="Count stock", assignee=worker, due_at=due)
    later = due + timedelta(hours=1)
    tasks.update_task(task, by=manager, due_at=later)
    task.status, task.needs_confirmation = Task.Status.REVIEW, True
    task.save()
    tasks.return_task(task, by=manager, reason="Shelf 3 is missing")
    tasks.cancel_task(task, by=manager)

    assert entries() == [
        (Action.TASK_ASSIGNED, manager.user_id, "Count stock", {"assignee": str(worker)}),
        (
            Action.TASK_CHANGED,
            manager.user_id,
            "Count stock",
            {"changes": {"due_at": [due.isoformat(), later.isoformat()]}},
        ),
        (Action.TASK_RETURNED, manager.user_id, "Count stock", {"reason": "Shelf 3 is missing"}),
        (Action.TASK_CANCELLED, manager.user_id, "Count stock", {}),
    ]


def test_accepting_work_is_logged(company, manager, worker):
    task = TaskFactory(
        assignee=worker, created_by=manager, status=Task.Status.REVIEW, needs_confirmation=True
    )

    tasks.confirm_task(task, by=manager)

    assert [entry[0] for entry in entries()] == [Action.TASK_CONFIRMED]


def test_peoples_own_tasks_are_not_logged(company, worker):
    task = tasks.create_task(by=worker, title="Call the bank")
    tasks.update_task(task, by=worker, title="Call the bank again")
    tasks.cancel_task(task, by=worker)

    assert entries() == []


def test_daily_task_templates_are_logged_with_their_changes(company, manager, worker):
    url = f"/api/v1/companies/{company.pk}/task-templates/"
    api = client_for(manager)

    created = api.post(url, {"title": "Open the shop", "due_time": "09:00"}, format="json")
    api.patch(
        f"{url}{created.data['id']}/",
        {"due_time": "08:30", "assignee_ids": [worker.pk]},
        format="json",
    )
    api.patch(f"{url}{created.data['id']}/", {"due_time": "08:30"}, format="json")  # no change
    api.delete(f"{url}{created.data['id']}/")

    assert entries() == [
        (Action.TEMPLATE_CREATED, manager.user_id, "Open the shop", {}),
        (
            Action.TEMPLATE_CHANGED,
            manager.user_id,
            "Open the shop",
            {"changes": {"due_time": ["09:00:00", "08:30:00"], "assignees": [[], [worker.pk]]}},
        ),
        (Action.TEMPLATE_DELETED, manager.user_id, "Open the shop", {}),
    ]
    assert not TaskTemplate.objects.exists()


def test_reminder_settings_are_logged(company, owner):
    url = f"/api/v1/companies/{company.pk}/reminder-policies/"
    policy = default_policy(company.pk)

    client_for(owner).patch(f"{url}{policy.pk}/", {"repeat_every_minutes": 10}, format="json")
    refused = client_for(owner).delete(f"{url}{policy.pk}/")

    assert refused.status_code == 400
    assert entries() == [
        (
            Action.POLICY_CHANGED,
            owner.user_id,
            "Default",
            {"changes": {"repeat_every_minutes": [20, 10]}},
        ),
    ]


def test_group_changes_are_logged(company, manager, member):
    group = groups.connect(-1_001, "Shop team", by=manager.user)
    groups.toggle_event(group, GroupEvent.MORNING, by=manager.user)
    groups.disconnect(group, by=manager.user)
    groups.connect(-1_001, "Shop team", by=manager.user)
    remover = member.registered(company).user
    groups.bot_removed(-1_001, by=remover)
    groups.bot_removed(-1_001, by=remover)  # already off: nothing new

    assert entries() == [
        (Action.GROUP_CONNECTED, manager.user_id, "Shop team", {}),
        (Action.GROUP_CHANGED, manager.user_id, "Shop team", {"event": "morning", "on": True}),
        (Action.GROUP_DISCONNECTED, manager.user_id, "Shop team", {}),
        (Action.GROUP_CONNECTED, manager.user_id, "Shop team", {}),
        (Action.GROUP_REMOVED, remover.pk, "Shop team", {}),
    ]


def test_admin_edits_are_logged(admin_client, admin_user, company, worker):
    group = TelegramGroupFactory(company=company, title="Shop team", events=[])

    admin_client.post(
        f"/admin/groups/telegramgroup/{group.pk}/change/",
        {"company": company.pk, "title": "Shop team", "events": ["late"], "is_active": "on"},
    )

    [entry] = AuditLog.objects.all()
    assert entry.action == Action.ADMIN_CHANGED
    assert entry.actor == admin_user
    assert entry.company == company
    assert entry.details == {"fields": ["events"]}


def test_the_log_cannot_be_edited_in_the_admin(admin_client, company, manager):
    members.approve(MembershipFactory(company=company), by=manager.user)
    entry = AuditLog.objects.get()

    assert admin_client.get("/admin/audit/auditlog/").status_code == 200
    assert admin_client.get(f"/admin/audit/auditlog/{entry.pk}/change/").status_code == 200
    assert admin_client.get("/admin/audit/auditlog/add/").status_code == 403
    assert admin_client.post(f"/admin/audit/auditlog/{entry.pk}/delete/").status_code == 403
    assert AuditLog.objects.filter(pk=entry.pk).exists()
