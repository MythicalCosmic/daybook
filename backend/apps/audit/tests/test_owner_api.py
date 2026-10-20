import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.audit import registry
from apps.audit import services as audit
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


def owner_client(membership: Membership) -> APIClient:
    """Authenticated as the member; the dashboard token itself is apps.signin's business."""
    api = APIClient()
    api.force_authenticate(membership.user)
    return api


def records_url(company_id: int, target_type="membership", target_id=None) -> str:
    url = f"/api/v1/owner/companies/{company_id}/audit/records/?target_type={target_type}"
    return url if target_id is None else f"{url}&target_id={target_id}"


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner", first_name="Olim")


@pytest.fixture
def worker(company, member):
    return member.registered(company, first_name="Aziz")


@pytest.fixture
def history(company, owner, worker):
    audit.record("member.approved", company_id=company.pk, actor=owner.user, target=worker)
    audit.record(
        "member.changed",
        company_id=company.pk,
        actor=None,
        target=worker,
        required_perm=Perm.PAYROLL_VIEW,
        changes={"salary": ["1", "2"]},
    )


def test_an_auditor_sees_a_records_history_newest_first(company, owner, worker, history):
    response = owner_client(owner).get(records_url(company.pk, target_id=worker.pk))

    assert response.status_code == 200
    rows = response.data["results"]
    assert [row["action"] for row in rows] == ["member.changed", "member.approved"]
    approved = rows[1]
    assert approved["action_label"] == "Approved a join request"
    assert approved["actor"] == {"id": owner.pk, "name": owner.full_name}
    assert approved["target"] == str(worker)
    assert rows[0]["actor"] is None


def test_rows_needing_a_permission_the_caller_lacks_are_absent(company, member, worker, history):
    auditor_role = AccessRole.objects.create(
        company=company,
        name="Auditor",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.AUDIT_VIEW],
    )
    auditor = member.registered(company, "Auditor")
    assert auditor.role == auditor_role

    response = owner_client(auditor).get(records_url(company.pk, target_id=worker.pk))

    assert response.status_code == 200
    assert [row["action"] for row in response.data["results"]] == ["member.approved"]
    assert "salary" not in str(response.data)


def test_without_audit_view_or_a_history_permission_it_is_forbidden(company, member, worker):
    manager = member.registered(company, "Manager")  # dashboard.access, no audit.view

    response = owner_client(manager).get(records_url(company.pk, target_id=worker.pk))

    assert response.status_code == 403


def test_without_dashboard_access_it_is_forbidden(company, worker):
    response = owner_client(worker).get(records_url(company.pk, target_id=worker.pk))

    assert response.status_code == 403


def test_another_companys_history_does_not_exist(owner, other_company, worker, history):
    response = owner_client(owner).get(records_url(other_company.pk, target_id=worker.pk))

    assert response.status_code == 404


def test_a_registered_history_permission_opens_that_records_history(
    company, member, worker, monkeypatch
):
    manager = member.registered(company, "Manager")
    task = TaskFactory(assignee=worker, created_by=manager)
    audit.record("task.assigned", company_id=company.pk, actor=manager.user, target=task)
    checked = []

    def in_scope(viewer, task_id):
        checked.append((viewer.pk, task_id))
        return task_id == task.pk

    monkeypatch.setitem(
        registry._targets, "task", registry.Target("task", Perm.TASKS_VIEW_ALL, in_scope)
    )

    allowed = owner_client(manager).get(records_url(company.pk, "task", task.pk))
    hidden = owner_client(manager).get(records_url(company.pk, "task", task.pk + 1000))
    other = owner_client(manager).get(records_url(company.pk, "membership", worker.pk))

    assert allowed.status_code == 200
    assert [row["action"] for row in allowed.data["results"]] == ["task.assigned"]
    assert hidden.status_code == 404
    assert other.status_code == 403
    assert checked == [(manager.pk, task.pk), (manager.pk, task.pk + 1000)]


def test_target_parameters_are_required(company, owner):
    response = owner_client(owner).get(f"/api/v1/owner/companies/{company.pk}/audit/records/")

    assert response.status_code == 400
    assert set(response.data) == {"target_type", "target_id"}


def test_a_mini_app_token_is_refused(company, owner):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(owner.user)}")

    response = api.get(records_url(company.pk, target_id=owner.pk))

    assert response.status_code == 401


def test_target_registration_rules(monkeypatch):
    monkeypatch.setattr(registry, "_targets", {})
    registry.register_target("task", Perm.TASKS_VIEW_ALL)

    with pytest.raises(registry.DuplicateTarget):
        registry.register_target("task", Perm.TASKS_VIEW_ALL)
    with pytest.raises(ValueError):
        registry.register_target("Task", Perm.TASKS_VIEW_ALL)
    assert registry.target("task").perm == Perm.TASKS_VIEW_ALL
    assert registry.target("membership") is None
