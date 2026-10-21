"""Routines in the mini app (the employee API): every task says which routine made it, and a
manager confirms a routine's finished runs together, by the same rules as one task at a time."""

from datetime import date

import pytest

from apps.audit.models import AuditLog
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory
from apps.tasks.tests.test_api import client_for, tasks_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def people(company, member):
    return [member.registered(company) for _ in range(3)]


def run(template, person, *, status=Task.Status.REVIEW, **fields):
    """One day's task of a routine, finished and waiting for a check unless told otherwise."""
    fields.setdefault("for_date", date(2026, 10, 21))
    return TaskFactory(
        assignee=person,
        created_by=template.created_by,
        kind=Task.Kind.DAILY,
        template=template,
        title=template.title,
        status=status,
        proof=Proof.PHOTO,
        needs_confirmation=True,
        **fields,
    )


def confirm(member, ids):
    return client_for(member).post(
        tasks_url(member.company, "confirm"), {"ids": ids}, format="json"
    )


def test_a_task_names_the_routine_that_made_it(company, manager, people):
    fridge = TaskTemplateFactory(company=company, title="Fridge temperature", created_by=manager)
    routine_run = run(fridge, people[0], status=Task.Status.TODO)
    one_off = TaskFactory(assignee=people[0], created_by=manager)
    mine = TaskFactory(assignee=people[0])
    repeating_own = TaskTemplateFactory(company=company, personal=True, created_by=people[0])
    own_repeat = TaskFactory(assignee=people[0], kind=Task.Kind.PERSONAL, template=repeating_own)

    rows = {
        row["id"]: row["routine"]
        for row in client_for(people[0]).get(tasks_url(company)).data["results"]
    }

    assert rows[routine_run.pk] == fridge.pk
    # One-off work, and a person's own repeating task, aren't routines.
    assert rows[one_off.pk] is None
    assert rows[mine.pk] is None
    assert rows[own_repeat.pk] is None
    assert (
        client_for(people[0]).get(tasks_url(company, routine_run.pk)).data["routine"] == fridge.pk
    )


def test_a_manager_confirms_a_routines_runs_together(company, manager, people):
    fridge = TaskTemplateFactory(company=company, title="Fridge temperature", created_by=manager)
    runs = [run(fridge, person) for person in people]

    response = confirm(manager, [task.pk for task in runs])

    assert response.status_code == 200
    assert response.data["done"] == 3
    assert response.data["failed"] == 0
    for task in Task.objects.filter(pk__in=[task.pk for task in runs]):
        assert task.status == Task.Status.DONE
        assert task.confirmed_by_id == manager.pk
    # Audited one by one, exactly as confirming each task would be.
    assert AuditLog.objects.filter(action="task.confirmed").count() == 3


def test_each_run_is_confirmed_or_refused_on_its_own(
    company, other_company, member, manager, people
):
    fridge = TaskTemplateFactory(company=company, title="Fridge temperature", created_by=manager)
    waiting = run(fridge, people[0])
    already = run(fridge, people[1], status=Task.Status.DONE)
    own = run(fridge, manager)  # nobody confirms their own work
    elsewhere = run(TaskTemplateFactory(company=other_company), member.registered(other_company))

    response = confirm(manager, [waiting.pk, already.pk, own.pk, elsewhere.pk])

    results = {row["id"]: row for row in response.data["results"]}
    assert response.status_code == 200
    assert response.data["done"] == 1
    assert results[waiting.pk]["ok"]
    assert not results[already.pk]["ok"] and results[already.pk]["error"]
    assert not results[own.pk]["ok"] and results[own.pk]["error"]
    assert results[elsewhere.pk] == {"id": elsewhere.pk, "ok": False, "error": "Not found."}
    own.refresh_from_db()
    elsewhere.refresh_from_db()
    assert own.status == Task.Status.REVIEW
    assert elsewhere.status == Task.Status.REVIEW


def test_only_people_who_may_confirm_can(company, manager, people):
    fridge = TaskTemplateFactory(company=company, created_by=manager)
    theirs = run(fridge, people[1])

    response = confirm(people[0], [theirs.pk])

    assert response.status_code == 200
    assert response.data["done"] == 0
    theirs.refresh_from_db()
    assert theirs.status == Task.Status.REVIEW
    assert not AuditLog.objects.filter(action="task.confirmed").exists()


@pytest.mark.parametrize("ids", [[], ["x"], list(range(1, 102))])
def test_the_list_of_tasks_is_checked(company, manager, ids):
    assert confirm(manager, ids).status_code == 400
