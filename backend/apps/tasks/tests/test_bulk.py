"""Bulk actions (docs/PLAN-OWNER.md §1.3): one action on many tasks, a result per id, every change
audited by the service it went through, one refusal never stopping the others."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.tasks import services
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def bulk(owner_api, member, body):
    return owner_api(member).post(
        f"/api/v1/owner/companies/{member.company_id}/tasks/bulk/", body, format="json"
    )


def open_task(shop, person=None, **fields):
    person = person or shop.worker
    fields.setdefault("due_at", timezone.now() + timedelta(hours=3))
    return TaskFactory(assignee=person, created_by=shop.owner, branch=person.home_branch, **fields)


def test_results_per_id_and_an_audit_row_per_change(shop, owner_api):
    first, second = open_task(shop), open_task(shop)
    done = open_task(shop, status=Task.Status.DONE)
    response = bulk(
        owner_api, shop.owner, {"ids": [first.pk, second.pk, done.pk, 999999], "action": "cancel"}
    )
    assert response.status_code == 200
    body = response.json()
    results = {row["id"]: row for row in body["results"]}
    assert body["done"] == 2 and body["failed"] == 2
    assert results[first.pk]["ok"] and results[second.pk]["ok"]
    assert not results[done.pk]["ok"] and results[done.pk]["error"]
    assert results[999999] == {"id": 999999, "ok": False, "error": "Not found."}
    assert AuditLog.objects.filter(action="task.cancelled").count() == 2


def test_reassign_reschedule_priority(shop, owner_api):
    tasks = [open_task(shop) for _ in range(3)]
    ids = [task.pk for task in tasks]
    assert (
        bulk(
            owner_api,
            shop.owner,
            {"ids": ids, "action": "priority", "payload": {"priority": "urgent"}},
        ).json()["done"]
        == 3
    )
    assert set(Task.objects.filter(pk__in=ids).values_list("priority", flat=True)) == {"urgent"}

    before = {task.pk: task.due_at for task in tasks}
    moved = bulk(
        owner_api, shop.owner, {"ids": ids, "action": "reschedule", "payload": {"shift_days": 1}}
    )
    assert moved.json()["done"] == 3
    for task in Task.objects.filter(pk__in=ids):
        assert task.due_at == before[task.pk] + timedelta(days=1)

    given = bulk(
        owner_api,
        shop.owner,
        {"ids": ids, "action": "reassign", "payload": {"assignee_id": shop.colleague.pk}},
    )
    assert given.json()["done"] == 3
    assert set(Task.objects.filter(pk__in=ids).values_list("assignee", flat=True)) == {
        shop.colleague.pk
    }
    assert set(Task.objects.filter(pk__in=ids).values_list("branch", flat=True)) == {shop.here.pk}
    assert AuditLog.objects.filter(action="tasks.reassigned").count() == 3


def test_confirm_many_checks(shop, owner_api):
    waiting = [
        open_task(shop, status=Task.Status.REVIEW, needs_confirmation=True) for _ in range(2)
    ]
    not_waiting = open_task(shop)
    response = bulk(
        owner_api,
        shop.owner,
        {"ids": [*[t.pk for t in waiting], not_waiting.pk], "action": "confirm"},
    )
    assert response.json()["done"] == 2
    assert set(
        Task.objects.filter(pk__in=[t.pk for t in waiting]).values_list("status", flat=True)
    ) == {"done"}


def test_tasks_outside_the_scope_count_as_not_found(shop, owner_api):
    there = open_task(shop, shop.colleague)
    here = open_task(shop)
    response = bulk(owner_api, shop.lead, {"ids": [there.pk, here.pk], "action": "cancel"})
    results = {row["id"]: row for row in response.json()["results"]}
    assert not results[there.pk]["ok"] and results[here.pk]["ok"]
    there.refresh_from_db()
    assert there.status == Task.Status.TODO


def test_payloads_are_checked(shop, owner_api):
    task = open_task(shop)
    assert bulk(owner_api, shop.owner, {"ids": [task.pk], "action": "reassign"}).status_code == 400
    assert (
        bulk(owner_api, shop.owner, {"ids": [task.pk], "action": "reschedule"}).status_code == 400
    )
    assert bulk(owner_api, shop.owner, {"ids": [], "action": "cancel"}).status_code == 400
    assert bulk(owner_api, shop.owner, {"ids": [task.pk], "action": "explode"}).status_code == 400


def test_bulk_needs_assign_or_confirm(shop, owner_api, member):
    accountant = member.registered(shop.company, "Accountant")
    assert (
        bulk(owner_api, accountant, {"ids": [open_task(shop).pk], "action": "cancel"}).status_code
        == 403
    )


def test_the_service_contract(shop):
    task = open_task(shop)
    results = services.bulk(by=shop.owner, ids=[task.pk], action="nudge", payload={})
    assert results == [services.BulkResult(task.pk, True)]
    again = services.bulk(by=shop.owner, ids=[task.pk], action="nudge", payload={})
    assert not again[0].ok  # nudged a moment ago
