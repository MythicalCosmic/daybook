"""Suspension (docs/PLAN-OWNER.md §13.4): suspend, reinstate, and what stops meanwhile."""

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient, force_authenticate
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from apps.announcements import services as announcements
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.api import IsCompanyMember
from apps.members.audit_actions import MemberAction
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.signals import member_reinstated, member_suspended
from apps.reminders.engine import send_due_reminders
from apps.tasks import offdays
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner", first_name="Olim")


@pytest.fixture
def worker(company, member):
    return member.registered(company, first_name="Aziz")


@pytest.fixture
def heard():
    """member_suspended and member_reinstated as they arrive."""
    calls = []

    def suspended(sender, membership, by, until, reason, **kwargs):
        calls.append(("suspended", membership.pk, by, until, reason))

    def reinstated(sender, membership, by, **kwargs):
        calls.append(("reinstated", membership.pk, by))

    member_suspended.connect(suspended, dispatch_uid="t-suspended")
    member_reinstated.connect(reinstated, dispatch_uid="t-reinstated")
    yield calls
    member_suspended.disconnect(dispatch_uid="t-suspended")
    member_reinstated.disconnect(dispatch_uid="t-reinstated")


def today(company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def api_for(membership: Membership) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(membership.user)}")
    return api


def test_suspending_pauses_access_and_is_announced_on_commit(
    company, owner, worker, heard, sent_messages, django_capture_on_commit_callbacks
):
    until = today(company) + timedelta(days=7)

    with django_capture_on_commit_callbacks(execute=True):
        services.suspend(worker, by=owner, until=until, reason="Cash shortage under review")

    worker.refresh_from_db()
    assert worker.status == Membership.Status.SUSPENDED
    assert worker.suspended_until == until
    assert not worker.has_perm(Perm.FINANCE_CLAIM)
    assert heard == [("suspended", worker.pk, owner, until, "Cash shortage under review")]
    entry = AuditLog.objects.get(action=MemberAction.SUSPENDED)
    assert entry.actor == owner.user
    assert entry.details == {"until": until.isoformat(), "reason": "Cash shortage under review"}
    assert entry.action_label == "Suspended a member"
    [message] = sent_messages
    assert message["chat_id"] == worker.user.telegram_id
    assert f"paused until {until:%d.%m.%Y}" in message["text"]


def test_reinstating_gives_access_back(
    company, owner, worker, heard, sent_messages, django_capture_on_commit_callbacks
):
    services.suspend(worker, by=owner, until=None, reason="Investigation")
    sent_messages.clear()
    heard.clear()

    with django_capture_on_commit_callbacks(execute=True):
        services.reinstate(worker, by=owner)

    worker.refresh_from_db()
    assert worker.status == Membership.Status.APPROVED
    assert worker.suspended_until is None
    assert heard == [("reinstated", worker.pk, owner)]
    assert AuditLog.objects.filter(action=MemberAction.REINSTATED, actor=owner.user).exists()
    [message] = sent_messages
    assert "is back" in message["text"]


def test_the_system_can_reinstate(
    company, owner, worker, heard, django_capture_on_commit_callbacks
):
    services.suspend(worker, by=owner, until=today(company), reason="One day")

    with django_capture_on_commit_callbacks(execute=True):
        services.reinstate(worker, by=None)

    assert heard[-1] == ("reinstated", worker.pk, None)
    assert AuditLog.objects.get(action=MemberAction.REINSTATED).actor is None


def test_suspending_needs_hr_suspend(company, member, worker):
    manager = member.registered(company, "Manager")  # no hr.suspend by default

    with pytest.raises(PermissionDenied):
        services.suspend(worker, by=manager, until=None, reason="x")
    with pytest.raises(PermissionDenied):
        services.reinstate(worker, by=manager)


def test_someone_from_another_company_cannot_suspend(worker, other_company, member):
    stranger = member.registered(other_company, "Owner")

    with pytest.raises(PermissionDenied):
        services.suspend(worker, by=stranger, until=None, reason="x")


def test_suspension_rules(company, member, owner, worker):
    with pytest.raises(DomainError, match="why"):
        services.suspend(worker, by=owner, until=None, reason="   ")
    with pytest.raises(DomainError, match="past"):
        services.suspend(worker, by=owner, until=today(company) - timedelta(days=1), reason="x")
    with pytest.raises(DomainError, match="yourself"):
        services.suspend(owner, by=owner, until=None, reason="x")
    with pytest.raises(DomainError, match="isn't suspended"):
        services.reinstate(worker, by=owner)
    pending = member(company, status=Membership.Status.PENDING)
    with pytest.raises(DomainError, match="current members"):
        services.suspend(pending, by=owner, until=None, reason="x")

    services.suspend(worker, by=owner, until=None, reason="x")
    with pytest.raises(DomainError, match="current members"):
        services.suspend(worker, by=owner, until=None, reason="again")


def test_owners_are_suspended_only_by_owners_and_never_the_last_one(company, member, owner):
    suspender_role = owner.role.__class__.objects.create(
        company=company, name="HR", permissions=["hr.suspend"]
    )
    hr = member.registered(company, "HR")
    assert hr.role == suspender_role

    with pytest.raises(PermissionDenied):
        services.suspend(owner, by=hr, until=None, reason="x")

    second = member.registered(company, "Owner")
    services.suspend(second, by=owner, until=None, reason="x")  # another owner remains
    with pytest.raises(DomainError, match="only owner"):
        services.suspend(owner, by=None, until=None, reason="x")  # not even the system


def test_suspended_people_get_no_daily_tasks(company, owner, worker):
    template = TaskTemplateFactory(
        company=company, created_by=owner, assignees=[worker], due_time=time(23, 59)
    )
    day = today(company)
    services.suspend(worker, by=owner, until=None, reason="x")

    generate_daily_tasks(company, day)

    assert not Task.objects.filter(template=template).exists()
    assert worker.pk in offdays.people_off(company, day)


def test_todays_routine_already_made_is_cancelled(company, owner, worker):
    day = today(company)
    routine = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, for_date=day)
    yesterday = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, for_date=day - timedelta(days=1))
    given = TaskFactory(assignee=worker, created_by=owner)

    services.suspend(worker, by=owner, until=None, reason="x")

    routine.refresh_from_db()
    yesterday.refresh_from_db()
    given.refresh_from_db()
    assert routine.status == Task.Status.CANCELLED
    assert yesterday.status == Task.Status.TODO  # history stays as it was
    assert given.status == Task.Status.TODO  # handed-out work waits for them


def test_the_offdays_provider_follows_the_suspension_dates(company, owner, worker):
    day = today(company)
    services.suspend(worker, by=owner, until=day + timedelta(days=2), reason="x")

    assert worker.pk in offdays.people_off(company, day + timedelta(days=2))
    assert worker.pk not in offdays.people_off(company, day + timedelta(days=3))


def test_suspended_people_get_no_reminders(company, owner, worker):
    now = timezone.now()
    task = TaskFactory(
        assignee=worker,
        created_by=owner,
        due_at=now - timedelta(minutes=5),
        next_reminder_at=now - timedelta(minutes=1),
    )
    services.suspend(worker, by=owner, until=None, reason="x")

    assert send_due_reminders(now) == 0
    task.refresh_from_db()
    assert task.next_reminder_at is None


def test_suspended_people_get_no_announcements(company, member, owner, worker):
    colleague = member.registered(company)
    services.suspend(worker, by=owner, until=None, reason="x")

    announcement = announcements.publish(owner, "Shop closes at 18:00 today.")

    recipients = set(announcement.receipts.values_list("membership_id", flat=True))
    assert recipients == {colleague.pk}


def test_the_employee_api_answers_403_suspended(company, owner, worker):
    services.suspend(worker, by=owner, until=date(2099, 1, 31), reason="x")
    api = api_for(worker)

    for path in ("summary/", "tasks/", "positions/", "holidays/"):
        response = api.get(f"/api/v1/companies/{company.pk}/{path}")
        assert response.status_code == 403, path
        assert response.data["code"] == "suspended"
        assert response.data["until"] == "2099-01-31"
        assert "paused until 31.01.2099" in response.data["detail"]


def test_until_further_notice_is_null(company, owner, worker):
    services.suspend(worker, by=owner, until=None, reason="x")

    response = api_for(worker).get(f"/api/v1/companies/{company.pk}/tasks/")

    assert response.status_code == 403
    assert response.data == {
        "code": "suspended",
        "detail": f"Your access to {company.name} is paused until further notice.",
        "until": None,
    }


def test_me_still_works_and_shows_the_suspension(company, owner, worker):
    services.suspend(worker, by=owner, until=None, reason="x")

    response = api_for(worker).get("/api/v1/me/")

    assert response.status_code == 200
    [membership] = response.data["memberships"]
    assert membership["status"] == "suspended"
    assert membership["suspended_until"] is None
    assert membership["permissions"] == []


def test_views_may_let_suspended_people_read(company, owner, worker, rf):
    class Wallet(APIView):
        permission_classes = (IsCompanyMember,)
        allow_suspended = True

        def get(self, request, company_id):
            return Response({"member": self.membership.pk})

        def post(self, request, company_id):
            return Response({"changed": True})

    services.suspend(worker, by=owner, until=None, reason="x")
    view = Wallet.as_view()

    def call(method):
        request = getattr(rf, method)("/")
        force_authenticate(request, user=worker.user)
        return view(request, company_id=company.pk)

    assert call("get").data == {"member": worker.pk}
    assert call("post").status_code == 403


def test_suspended_people_still_count_as_members_for_offboarding(company, owner, worker):
    services.suspend(worker, by=owner, until=None, reason="x")

    services.offboard(worker, by=owner.user)

    worker.refresh_from_db()
    assert worker.status == Membership.Status.LEFT
    assert worker.suspended_until is None
