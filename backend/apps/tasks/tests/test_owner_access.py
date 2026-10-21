"""Every package B owner endpoint (docs/PLAN-OWNER.md §2.3 rule 21, §4.5, §5): another company's
id answers 404, another company's rows answer 404 inside your own company, and each endpoint
needs its permission (403 without it)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.members.models import AccessRole
from apps.members.permissions import Perm
from apps.reminders.models import ReminderPolicy
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def days(shop) -> dict[str, str]:
    today = timezone.localdate(timezone=ZoneInfo(shop.company.timezone))
    return {"from": (today - timedelta(days=6)).isoformat(), "to": today.isoformat()}


def reads(shop, task_id: int, routine_id: int, policy_id: int) -> list[tuple[str, dict]]:
    window = days(shop)
    return [
        ("tasks/", {}),
        ("tasks/board/", {}),
        ("tasks/calendar/", window),
        ("tasks/summary/", {}),
        ("tasks/reviews/", {}),
        ("tasks/options/", {}),
        (f"tasks/{task_id}/", {}),
        (f"tasks/{task_id}/timeline/", {}),
        ("proofs/", {}),
        ("routines/", {}),
        (f"routines/{routine_id}/", {}),
        (f"routines/{routine_id}/preview/", {}),
        (f"routines/{routine_id}/compliance/", window),
        ("routines/day/", {}),
        ("routines/history/", {}),
        ("routines/to-confirm/", {}),
        ("reminder-policies/", {}),
        (f"reminder-policies/{policy_id}/", {}),
        ("reminder-log/", {}),
        ("blocked-bot/", {}),
        ("reports/team/", {"preset": "last_30"}),
        ("reports/routines/", {"preset": "last_30"}),
    ]


def writes(task_id: int, routine_id: int, policy_id: int) -> list[tuple[str, str, dict]]:
    return [
        ("post", "tasks/", {"title": "Shelves", "assignee_ids": [1]}),
        ("patch", f"tasks/{task_id}/", {"title": "Shelves"}),
        ("post", f"tasks/{task_id}/confirm/", {}),
        ("post", f"tasks/{task_id}/return/", {"reason": "Again"}),
        ("post", f"tasks/{task_id}/cancel/", {}),
        ("post", f"tasks/{task_id}/reassign/", {"assignee_id": 1}),
        ("post", f"tasks/{task_id}/nudge/", {}),
        ("post", f"tasks/{task_id}/comment/", {"text": "Hi"}),
        ("post", f"tasks/{task_id}/move/", {"to": "done"}),
        ("post", "tasks/bulk/", {"ids": [task_id], "action": "cancel"}),
        ("post", "routines/", {"title": "Shelves", "due_time": "10:00"}),
        ("patch", f"routines/{routine_id}/", {"title": "Shelves"}),
        ("delete", f"routines/{routine_id}/", {}),
        ("post", f"routines/{routine_id}/give-today/", {}),
        ("post", "reminder-policies/", {"name": "Soft"}),
        ("patch", f"reminder-policies/{policy_id}/", {"name": "Soft"}),
        ("delete", f"reminder-policies/{policy_id}/", {}),
        ("post", f"reminder-policies/{policy_id}/make-default/", {}),
    ]


def call(client, method, url, data):
    if method == "get":
        return client.get(url, data)
    return getattr(client, method)(url, data, format="json")


def rows_of(company, owner):
    task = TaskFactory(assignee=owner, created_by=owner, kind=Task.Kind.ASSIGNED)
    routine = TaskTemplateFactory(company=company, assignees=[owner])
    policy = ReminderPolicy.objects.create(company=company, name="Strict")
    return task.pk, routine.pk, policy.pk


def test_another_companys_id_is_not_found_everywhere(shop, owner_api, other_company, member):
    stranger = member.registered(other_company, "Owner")
    ids = rows_of(other_company, stranger)
    client = owner_api(shop.owner)
    base = f"/api/v1/owner/companies/{other_company.pk}/"
    for path, params in reads(shop, *ids):
        assert client.get(base + path, params).status_code == 404, path
    for method, path, data in writes(*ids):
        assert call(client, method, base + path, data).status_code == 404, path


def test_another_companys_rows_are_not_found_in_your_company(
    shop, owner_api, other_company, member
):
    stranger = member.registered(other_company, "Owner")
    task_id, routine_id, policy_id = rows_of(other_company, stranger)
    client = owner_api(shop.owner)
    base = f"/api/v1/owner/companies/{shop.company.pk}/"
    for path, params in reads(shop, task_id, routine_id, policy_id):
        if str(task_id) in path or str(routine_id) in path or str(policy_id) in path:
            assert client.get(base + path, params).status_code == 404, path
    for method, path, data in writes(task_id, routine_id, policy_id):
        if any(f"/{pk}/" in f"/{path}" for pk in (task_id, routine_id, policy_id)):
            assert call(client, method, base + path, data).status_code == 404, path
    # Ids inside a payload are checked too: no task for someone of another company, and a bulk
    # action never reaches another company's task.
    response = client.post(
        base + "tasks/", {"title": "Shelves", "assignee_ids": [stranger.pk]}, format="json"
    )
    assert response.status_code == 400
    body = client.post(
        base + "tasks/bulk/", {"ids": [task_id], "action": "cancel"}, format="json"
    ).json()
    assert body["results"] == [{"id": task_id, "ok": False, "error": "Not found."}]
    assert Task.objects.get(pk=task_id).status == Task.Status.TODO


def test_each_endpoint_needs_its_permission(shop, owner_api, member):
    ids = rows_of(shop.company, shop.owner)
    base = f"/api/v1/owner/companies/{shop.company.pk}/"
    # Dashboard access alone: no tasks, routines, reminders or reports.
    AccessRole.objects.create(
        company=shop.company, name="Viewer", permissions=[Perm.DASHBOARD_ACCESS]
    )
    viewer = owner_api(member.registered(shop.company, "Viewer"))
    open_to_any = {"tasks/reviews/"}  # each sees only the checks waiting for them (none)
    for path, params in reads(shop, *ids):
        expected = 200 if path in open_to_any else (404, 403)
        status = viewer.get(base + path, params).status_code
        if expected == 200:
            assert status == 200, path
        else:
            # A task they can't see is not found; everything else is forbidden.
            assert status in expected, (path, status)
    # Employees have no dashboard at all.
    employee = owner_api(member.registered(shop.company, "Employee"))
    for path, params in reads(shop, *ids):
        assert employee.get(base + path, params).status_code == 403, path
    for method, path, data in writes(*ids):
        assert call(employee, method, base + path, data).status_code == 403, path


def test_branch_scope_hides_other_branches_rows(shop, owner_api):
    """A branch lead (only `here`) gets 404 for a task, routine or its history at `there`."""
    theirs = TaskFactory(
        assignee=shop.colleague,
        created_by=shop.owner,
        kind=Task.Kind.ASSIGNED,
        branch=shop.there,
    )
    routine = TaskTemplateFactory(
        company=shop.company, assignees=[shop.colleague], branch=shop.there
    )
    client = owner_api(shop.lead)
    base = f"/api/v1/owner/companies/{shop.company.pk}/"
    for path in (
        f"tasks/{theirs.pk}/",
        f"tasks/{theirs.pk}/timeline/",
        f"routines/{routine.pk}/",
        f"routines/{routine.pk}/preview/",
    ):
        assert client.get(base + path).status_code == 404, path
    history = client.get(base + "audit/records/", {"target_type": "task", "target_id": theirs.pk})
    assert history.status_code in (403, 404)
    assert client.post(base + f"tasks/{theirs.pk}/nudge/").status_code == 404
    assert owner_api(shop.owner).get(base + f"tasks/{theirs.pk}/").status_code == 200
