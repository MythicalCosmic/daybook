from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.models import Membership
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner", first_name="Dilnoza")


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager", first_name="Mona")


@pytest.fixture
def leaver(company, member):
    return member.registered(company, first_name="Ali", last_name="Valiyev")


def to(sent_messages, member) -> list[dict]:
    return [m for m in sent_messages if m["chat_id"] == member.user.telegram_id]


def test_offboarding_hands_the_work_back(
    company, owner, manager, leaver, sent_messages, django_capture_on_commit_callbacks
):
    soon = timezone.now() + timedelta(hours=2)
    given = TaskFactory(assignee=leaver, created_by=manager, due_at=soon, needs_confirmation=True)
    started = TaskFactory(
        assignee=leaver,
        created_by=manager,
        due_at=soon,
        status=Task.Status.IN_PROGRESS,
        started_at=timezone.now(),
    )
    waiting = TaskFactory(assignee=leaver, created_by=manager, status=Task.Status.REVIEW)
    daily = TaskFactory(assignee=leaver, created_by=owner, kind=Task.Kind.DAILY, due_at=soon)
    own = TaskFactory(assignee=leaver, due_at=soon)
    template = TaskTemplateFactory(company=company, created_by=owner, assignees=[leaver, manager])
    repeating = TaskTemplateFactory(company=company, created_by=leaver, personal=True)
    today = timezone.localdate(timezone=ZoneInfo(company.timezone))
    future_off = TimeOff.objects.create(
        company=company,
        membership=leaver,
        first_day=today + timedelta(days=3),
        last_day=today + timedelta(days=4),
        status=TimeOff.Status.APPROVED,
    )

    with django_capture_on_commit_callbacks(execute=True):
        services.offboard(leaver, by=owner.user)

    leaver.refresh_from_db()
    assert leaver.status == Membership.Status.LEFT
    for task in (given, started):
        task.refresh_from_db()
        assert (task.assignee, task.kind, task.status) == (
            manager,
            Task.Kind.PERSONAL,
            Task.Status.TODO,
        )
        assert task.next_reminder_at is not None
        assert task.started_at is None
    assert given.needs_confirmation is False
    waiting.refresh_from_db()
    assert (waiting.assignee, waiting.status) == (leaver, Task.Status.REVIEW)  # finished work stays
    for task in (daily, own):
        task.refresh_from_db()
        assert (task.status, task.next_reminder_at) == (Task.Status.CANCELLED, None)
    assert list(template.assignees.all()) == [manager]
    repeating.refresh_from_db()
    assert not repeating.is_active
    future_off.refresh_from_db()
    assert future_off.status == TimeOff.Status.CANCELLED
    entry = AuditLog.objects.get(action=AuditLog.Action.MEMBER_LEFT)
    assert entry.actor == owner.user

    [came_back] = to(sent_messages, manager)
    assert "Ali Valiyev has left the team" in came_back["text"]
    opened = [
        TaskCallback.unpack(row[0]["callback_data"])
        for row in came_back["reply_markup"]["inline_keyboard"]
    ]
    assert {data.task_id for data in opened} == {given.pk, started.pk}
    assert {data.action for data in opened} == {TaskAction.OPEN}
    [goodbye] = to(sent_messages, leaver)
    assert "no longer on the team" in goodbye["text"]
    assert goodbye["reply_markup"] == {"remove_keyboard": True}


def test_work_from_someone_who_left_too_is_cancelled(company, member, owner, leaver):
    gone = member(company, "Manager", status=Membership.Status.LEFT)
    task = TaskFactory(assignee=leaver, created_by=gone, kind=Task.Kind.ASSIGNED)

    services.offboard(leaver, by=owner.user)

    task.refresh_from_db()
    assert task.status == Task.Status.CANCELLED


def test_only_people_who_manage_members_offboard(company, member, owner, manager, leaver):
    for someone in (member.registered(company), manager):  # managers can't by default
        with pytest.raises(PermissionDenied):
            services.offboard(leaver, by=someone.user)
    with pytest.raises(DomainError):
        services.offboard(owner, by=owner.user)
    second_owner = member.registered(company, "Owner")
    services.offboard(second_owner, by=owner.user)  # an owner may offboard another owner
    with pytest.raises(DomainError):
        services.offboard(second_owner, by=owner.user)  # already gone


def test_blocking_hands_the_work_back_too(
    company, owner, manager, leaver, django_capture_on_commit_callbacks
):
    task = TaskFactory(assignee=leaver, created_by=manager)

    with django_capture_on_commit_callbacks(execute=True):
        services.block(leaver, by=owner.user)

    task.refresh_from_db()
    assert task.assignee == manager


def test_access_ends_at_once(company, owner, leaver):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(leaver.user).access_token}")
    summary = f"/api/v1/companies/{company.pk}/summary/"
    assert api.get(summary).status_code == 200

    services.offboard(leaver, by=owner.user)

    assert api.get(summary).status_code == 404
