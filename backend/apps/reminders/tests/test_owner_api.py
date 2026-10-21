"""Reminder policies, the reminder log and the blocked-bot list from the owner console
(docs/PLAN-OWNER.md §4.5)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.reminders.models import ReminderLog, ReminderPolicy
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, make_shop

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def url(company, path):
    return f"/api/v1/owner/companies/{company.pk}/{path}"


POLICY = {
    "name": "Strict: tills and opening",
    "heads_up_minutes": 15,
    "repeat_every_minutes": 10,
    "max_reminders": 8,
    "escalate_after": 2,
    "quiet_from": "23:00",
    "quiet_until": "07:00",
    "quiet_days": [6],
    "snooze_minutes": 10,
    "max_snoozes": 1,
    "texts": [
        {"from_step": 1, "text": "{name}, {task} was due at {due}."},
        {"from_step": 3, "text": "{task} is {late} late. Your manager knows."},
    ],
}


def test_create_with_texts_then_edit(shop, owner_api):
    client = owner_api(shop.owner)
    response = client.post(url(shop.company, "reminder-policies/"), POLICY, format="json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["texts"] == POLICY["texts"] and body["is_default"] is False
    assert body["quiet_days"] == [6]

    edited = client.patch(
        url(shop.company, f"reminder-policies/{body['id']}/"),
        {"repeat_every_minutes": 15, "texts": [{"from_step": 2, "text": "Hurry, {name}!"}]},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.json()["texts"] == [{"from_step": 2, "text": "Hurry, {name}!"}]
    changes = AuditLog.objects.get(action="policy.changed", target_id=body["id"]).details["changes"]
    assert set(changes) == {"repeat_every_minutes", "texts"}


def test_bad_values_are_refused(shop, owner_api):
    client = owner_api(shop.owner)
    unknown = POLICY | {"texts": [{"from_step": 1, "text": "Hello {boss}"}]}
    assert (
        client.post(url(shop.company, "reminder-policies/"), unknown, format="json").status_code
        == 400
    )
    too_often = POLICY | {"repeat_every_minutes": 1}
    response = client.post(url(shop.company, "reminder-policies/"), too_often, format="json")
    assert response.status_code == 400 and "repeat_every_minutes" in response.json()
    half_quiet = POLICY | {"quiet_until": None}
    assert (
        client.post(url(shop.company, "reminder-policies/"), half_quiet, format="json").status_code
        == 400
    )
    every_day_quiet = POLICY | {"quiet_days": [0, 1, 2, 3, 4, 5, 6]}
    assert (
        client.post(
            url(shop.company, "reminder-policies/"), every_day_quiet, format="json"
        ).status_code
        == 400
    )


def test_the_default_stays_and_can_be_moved(shop, owner_api):
    client = owner_api(shop.owner)
    default = ReminderPolicy.objects.get(company=shop.company, is_default=True)
    assert client.delete(url(shop.company, f"reminder-policies/{default.pk}/")).status_code == 400
    other = client.post(url(shop.company, "reminder-policies/"), POLICY, format="json").json()
    made = client.post(url(shop.company, f"reminder-policies/{other['id']}/make-default/"))
    assert made.json()["is_default"] is True
    default.refresh_from_db()
    assert default.is_default is False
    assert client.delete(url(shop.company, f"reminder-policies/{default.pk}/")).status_code == 204


def test_usage_counts_routines_and_the_default_covers_the_rest(shop, owner_api):
    policy = ReminderPolicy.objects.create(company=shop.company, name="Gentle")
    TaskTemplateFactory(company=shop.company, reminder_policy=policy, assignees=[shop.worker])
    TaskTemplateFactory(company=shop.company, assignees=[shop.worker])
    rows = {
        row["name"]: row
        for row in owner_api(shop.owner).get(url(shop.company, "reminder-policies/")).json()
    }
    assert rows["Gentle"]["usage"]["routines"] == 1
    default = next(row for row in rows.values() if row["is_default"])
    assert default["usage"]["routines"] == 1


def test_policies_need_reminders_configure_and_stay_in_the_company(
    shop, owner_api, member, other_company
):
    accountant = member.registered(shop.company, "Accountant")
    assert owner_api(accountant).get(url(shop.company, "reminder-policies/")).status_code == 403
    theirs = ReminderPolicy.objects.create(company=other_company, name="Theirs")
    response = owner_api(shop.owner).patch(
        url(shop.company, f"reminder-policies/{theirs.pk}/"), {"name": "Mine"}, format="json"
    )
    assert response.status_code == 404


def test_the_log_follows_task_visibility(shop, owner_api):
    here = TaskFactory(
        assignee=shop.worker,
        created_by=shop.owner,
        branch=shop.here,
        due_at=timezone.now() - timedelta(hours=1),
    )
    there = TaskFactory(assignee=shop.colleague, created_by=shop.owner, branch=shop.there)
    personal = TaskFactory(assignee=shop.worker, branch=shop.here)
    for task in (here, there, personal):
        ReminderLog.objects.create(
            task=task, kind=ReminderLog.Kind.REMINDER, step=1, recipient=task.assignee
        )
    ReminderLog.objects.create(
        task=here, kind=ReminderLog.Kind.ESCALATION, step=3, recipient=shop.manager
    )

    def titles(member, **params):
        body = owner_api(member).get(url(shop.company, "reminder-log/"), params).json()
        return [row["task"]["id"] for row in body["results"]]

    assert set(titles(shop.lead)) == {here.pk}
    assert set(titles(shop.manager)) == {here.pk, there.pk}  # not someone's personal task
    assert set(titles(shop.owner)) == {here.pk, there.pk, personal.pk}
    assert titles(shop.owner, kind="escalation") == [here.pk]
    first = owner_api(shop.owner).get(url(shop.company, "reminder-log/")).json()["results"][0]
    assert first["recipient"]["id"] and first["branch"] is not None


def test_blocked_bot_lists_people_in_scope(shop, owner_api, member):
    for person in (shop.worker, shop.colleague):
        person.user.employee_bot_blocked_at = timezone.now()
        person.user.save()
    TaskFactory(
        assignee=shop.worker, created_by=shop.owner, due_at=timezone.now() - timedelta(hours=1)
    )
    rows = owner_api(shop.lead).get(url(shop.company, "blocked-bot/")).json()
    assert [row["member"]["id"] for row in rows] == [shop.worker.pk]
    assert rows[0]["open_tasks"] == 1 and rows[0]["late_tasks"] == 1
    assert len(owner_api(shop.owner).get(url(shop.company, "blocked-bot/")).json()) == 2
    employee = member.registered(shop.company, "Accountant")
    employee.role.permissions = ["dashboard.access"]
    employee.role.save()
    assert owner_api(employee).get(url(shop.company, "blocked-bot/")).status_code == 403


def test_copy_setup_takes_the_policies_with_their_texts(shop, member, other_company, owner_api):
    from apps.console import registry

    owner_api(shop.owner).post(url(shop.company, "reminder-policies/"), POLICY, format="json")
    target_owner = member.registered(other_company, "Owner", user=shop.owner.user)
    copied = registry.run_copy(shop.company, other_company, ["reminders.policies"], by=target_owner)
    assert copied["reminders.policies"] == 2  # the default comes across under another name
    copy = ReminderPolicy.objects.get(company=other_company, name=POLICY["name"])
    assert copy.texts.count() == 2 and copy.is_default is False
    assert ReminderPolicy.objects.filter(company=other_company, is_default=True).count() == 1
    assert Task.objects.filter(company=other_company).count() == 0
