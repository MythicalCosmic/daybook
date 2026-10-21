"""Routines from the owner console (docs/PLAN-OWNER.md §1.3, §4.5): CRUD with people, positions,
an optional branch and a checklist; "who gets it" preview matching daily generation; 30-day
completion and compliance."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.members.tests.factories import PositionFactory
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Task, TaskTemplate
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory, make_shop
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/routines/{path}"


def test_create_a_routine_with_a_branch_and_a_checklist(shop, owner_api):
    cashier = PositionFactory(company=shop.company, name="Cashier")
    response = owner_api(shop.owner).post(
        url(shop.company),
        {
            "title": "Close the till",
            "due_time": "21:15",
            "weekdays": [0, 1, 2, 3, 4, 5],
            "position_ids": [cashier.pk],
            "assignee_ids": [shop.worker.pk],
            "branch_id": shop.here.pk,
            "proof": "photo",
            "needs_confirmation": True,
            "checklist": ["Z-report", " ", "Terminal slip"],
            "escalate_to_id": shop.manager.pk,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["branch"]["id"] == shop.here.pk
    assert body["checklist"] == ["Z-report", "Terminal slip"]
    assert body["positions"] == [{"id": cashier.pk, "name": "Cashier"}]
    assert body["escalate_to"]["id"] == shop.manager.pk
    assert AuditLog.objects.filter(action="template.created", target_id=body["id"]).exists()


def test_a_routine_needs_someone_and_a_time(shop, owner_api):
    client = owner_api(shop.owner)
    assert (
        client.post(
            url(shop.company), {"title": "Nobody", "due_time": "10:00"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post(
            url(shop.company), {"title": "No time", "assignee_ids": [shop.worker.pk]}, format="json"
        ).status_code
        == 400
    )


def test_edit_pause_and_delete(shop, owner_api):
    routine = TaskTemplateFactory(
        company=shop.company, assignees=[shop.worker], created_by=shop.owner
    )
    client = owner_api(shop.owner)
    response = client.patch(
        url(shop.company, f"{routine.pk}/"),
        {"is_active": False, "due_time": "07:30"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False and response.json()["due_time"] == "07:30:00"
    changes = AuditLog.objects.get(action="template.changed", target_id=routine.pk).details[
        "changes"
    ]
    assert set(changes) == {"is_active", "due_time"}
    assert client.delete(url(shop.company, f"{routine.pk}/")).status_code == 204
    assert not TaskTemplate.objects.filter(pk=routine.pk).exists()


def test_routines_need_tasks_templates_and_stay_in_the_company(
    shop, owner_api, member, other_company
):
    accountant = member.registered(shop.company, "Accountant")
    assert owner_api(accountant).get(url(shop.company)).status_code == 403
    theirs = TaskTemplateFactory(company=other_company)
    assert owner_api(shop.owner).get(url(shop.company, f"{theirs.pk}/")).status_code == 404
    assert owner_api(shop.owner).get(url(other_company)).status_code == 404


def test_a_branch_lead_works_with_their_branchs_routines(shop, owner_api):
    here = TaskTemplateFactory(company=shop.company, branch=shop.here, assignees=[shop.worker])
    there = TaskTemplateFactory(company=shop.company, branch=shop.there, assignees=[shop.colleague])
    company_wide = TaskTemplateFactory(company=shop.company, assignees=[shop.worker])
    client = owner_api(shop.lead)
    assert {row["id"] for row in client.get(url(shop.company)).json()} == {here.pk}
    assert (
        client.patch(
            url(shop.company, f"{there.pk}/"), {"title": "Mine now"}, format="json"
        ).status_code
        == 404
    )
    assert company_wide.pk not in {row["id"] for row in client.get(url(shop.company)).json()}
    refused = client.post(
        url(shop.company),
        {"title": "X", "due_time": "10:00", "assignee_ids": [shop.worker.pk]},
        format="json",
    )
    assert refused.status_code == 400  # they must pick one of their branches


def test_onboarding_templates_are_a_separate_list(shop, owner_api):
    routine = TaskTemplateFactory(company=shop.company, assignees=[shop.worker])
    welcome = TaskTemplateFactory(company=shop.company, onboarding=True, due_after_days=2)
    TaskTemplateFactory(company=shop.company, personal=True, assignees=[shop.worker])
    client = owner_api(shop.owner)
    assert [row["id"] for row in client.get(url(shop.company)).json()] == [routine.pk]
    assert [row["id"] for row in client.get(url(shop.company), {"onboarding": "true"}).json()] == [
        welcome.pk
    ]
    created = client.post(
        url(shop.company),
        {
            "title": "Meet your manager",
            "due_time": "15:00",
            "onboarding": True,
            "due_after_days": 3,
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["onboarding"] is True and created.json()["due_after_days"] == 3


def test_the_preview_matches_daily_generation(shop, owner_api, member):
    cashier = PositionFactory(company=shop.company)
    away = member.registered(shop.company, position=cashier, home_branch=shop.here)
    elsewhere = member.registered(shop.company, position=cashier, home_branch=shop.there)
    shop.worker.position = cashier
    shop.worker.save()
    routine = TaskTemplateFactory(
        company=shop.company,
        positions=[cashier],
        branch=shop.here,
        due_time="18:00",
        created_by=shop.owner,
    )
    TaskTemplate.objects.filter(pk=routine.pk).update(created_at=timezone.now() - timedelta(days=2))
    day = timezone.localdate(timezone=ZoneInfo(shop.company.timezone)) + timedelta(days=1)
    TimeOff.objects.create(
        company=shop.company,
        membership=away,
        first_day=day,
        last_day=day,
        status=TimeOff.Status.APPROVED,
    )

    preview = (
        owner_api(shop.owner)
        .get(url(shop.company, f"{routine.pk}/preview/"), {"day": day.isoformat()})
        .json()
    )
    rows = {row["member"]["id"]: row for row in preview["people"]}
    assert rows[shop.worker.pk]["gets"] is True
    assert rows[away.pk] == rows[away.pk] | {"gets": False, "reason": "time_off"}
    assert rows[elsewhere.pk]["reason"] == "branch"

    generate_daily_tasks(shop.company, day)
    made = set(
        Task.objects.filter(template=routine, for_date=day).values_list("assignee", flat=True)
    )
    assert made == {pk for pk, row in rows.items() if row["gets"]}


def test_generation_copies_the_checklist(shop):
    routine = TaskTemplateFactory(
        company=shop.company,
        assignees=[shop.worker],
        checklist=["Lights", "Music"],
        created_by=shop.owner,
    )
    TaskTemplate.objects.filter(pk=routine.pk).update(created_at=timezone.now() - timedelta(days=2))
    day = timezone.localdate(timezone=ZoneInfo(shop.company.timezone)) + timedelta(days=1)
    generate_daily_tasks(shop.company, day)
    generate_daily_tasks(shop.company, day)  # reruns add nothing twice
    task = Task.objects.get(template=routine, for_date=day)
    assert [item.text for item in task.checklist.all()] == ["Lights", "Music"]


def test_list_stats_and_compliance(shop, owner_api):
    routine = TaskTemplateFactory(company=shop.company, assignees=[shop.worker], due_time="10:00")
    tz = ZoneInfo(shop.company.timezone)
    today = timezone.localdate(timezone=tz)
    for days_ago, outcome in [(1, "on_time"), (2, "late"), (3, "missed"), (4, "on_time")]:
        due = datetime.combine(today - timedelta(days=days_ago), time(10, 0), tzinfo=tz)
        completed = {
            "on_time": due - timedelta(minutes=5),
            "late": due + timedelta(hours=1),
            "missed": None,
        }[outcome]
        TaskFactory(
            assignee=shop.worker,
            created_by=shop.owner,
            kind=Task.Kind.DAILY,
            template=routine,
            for_date=due.date(),
            due_at=due,
            status=Task.Status.DONE if completed else Task.Status.TODO,
            completed_at=completed,
            branch=shop.here,
        )
    client = owner_api(shop.owner)
    stats = client.get(url(shop.company)).json()[0]["stats"]
    assert stats["made_30d"] == 4 and stats["done_30d"] == 3 and stats["completion_30d"] == 75.0
    assert len(stats["spark"]) == 14

    body = client.get(url(shop.company, f"{routine.pk}/compliance/")).json()
    assert body["totals"] == {
        "made": 4,
        "on_time": 2,
        "late": 1,
        "missed": 1,
        "on_time_percent": 50.0,
    }
    assert body["people"][0]["member"]["id"] == shop.worker.pk
    assert len(body["series"]) == 30
    ranged = client.get(
        url(shop.company, f"{routine.pk}/compliance/"),
        {"from": (today - timedelta(days=2)).isoformat(), "to": today.isoformat()},
    )
    assert ranged.json()["totals"]["made"] == 2


def test_copy_setup_takes_routines_without_people(shop, member, other_company):
    from apps.console import registry

    cashier_here = PositionFactory(company=shop.company, name="Cashier")
    PositionFactory(company=other_company, name="Cashier")
    TaskTemplateFactory(
        company=shop.company,
        title="Close the till",
        positions=[cashier_here],
        assignees=[shop.worker],
    )
    TaskTemplateFactory(company=shop.company, title="Read the rules", onboarding=True)
    TaskTemplateFactory(company=shop.company, title="Personal one", personal=True)
    target_owner = member.registered(other_company, "Owner", user=shop.owner.user)
    copied = registry.run_copy(
        shop.company, other_company, ["tasks.routines", "tasks.onboarding"], by=target_owner
    )
    assert copied == {"tasks.routines": 1, "tasks.onboarding": 1}
    till = TaskTemplate.objects.get(company=other_company, title="Close the till")
    assert till.assignees.count() == 0 and [p.name for p in till.positions.all()] == ["Cashier"]
    assert till.is_active
    assert not TaskTemplate.objects.filter(company=other_company, title="Personal one").exists()


def test_preview_defaults_to_tomorrow(shop, owner_api):
    routine = TaskTemplateFactory(
        company=shop.company, assignees=[shop.worker], weekdays=[0, 1, 2, 3, 4, 5, 6]
    )
    body = owner_api(shop.owner).get(url(shop.company, f"{routine.pk}/preview/")).json()
    tomorrow = timezone.localdate(timezone=ZoneInfo(shop.company.timezone)) + timedelta(days=1)
    assert body["day"] == tomorrow.isoformat() and body["due"] is True
    assert date.fromisoformat(body["day"]) == tomorrow


WED = date(2030, 10, 23)  # a Wednesday, far enough ahead


def _at(company, day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(company.timezone))


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_a_routine_made_after_its_time_starts_tomorrow_unless_given_today(
    shop, owner_api, monkeypatch
):
    company = shop.company
    monkeypatch.setattr("django.utils.timezone.now", lambda: _at(company, WED, 12, 30))
    client = owner_api(shop.owner)
    created = client.post(
        url(company),
        {
            "title": "Muddati yaqin dorilarni tekshirish",
            "due_time": "09:00",
            "assignee_ids": [shop.worker.pk, shop.owner.pk],
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert _moment(body["next_run"]) == _at(company, WED + timedelta(days=1), 9)
    assert body["today"]["reason"] == "made_late"
    assert body["today"]["give"]["people"] == 2
    assert _moment(body["today"]["give"]["due_at"]) == _at(company, WED, 14, 30)
    routine = body["id"]

    listed = client.get(url(company)).json()
    assert _moment(listed[0]["next_run"]) == _at(company, WED + timedelta(days=1), 9)
    assert listed[0]["today"] is None  # only a routine's own page asks about today
    preview = client.get(url(company, f"{routine}/preview/"), {"day": WED.isoformat()}).json()
    assert preview["reason"] == "made_late" and not any(row["gets"] for row in preview["people"])
    assert _moment(preview["next_run"]) == _at(company, WED + timedelta(days=1), 9)

    give = url(company, f"{routine}/give-today/")
    assert client.post(give, {"due_time": "10:00"}, format="json").status_code == 400  # gone
    given = client.post(give, {"due_time": "13:15"}, format="json")
    assert given.status_code == 201, given.content
    assert given.json()["given"] == 2
    assert _moment(given.json()["due_at"]) == _at(company, WED, 13, 15)
    tasks = client.get(f"/api/v1/owner/companies/{company.pk}/tasks/", {"routine": routine})
    assert tasks.json()["count"] == 2
    assert client.post(give, {}, format="json").status_code == 400  # everyone has it now
    assert client.get(url(company, f"{routine}/")).json()["today"]["give"] is None


def test_paused_routines_have_no_next_run_and_giving_needs_routine_rights(shop, owner_api):
    routine = TaskTemplateFactory(
        company=shop.company, assignees=[shop.worker], is_active=False, created_by=shop.owner
    )
    body = owner_api(shop.owner).get(url(shop.company, f"{routine.pk}/")).json()
    assert body["next_run"] is None and body["today"]["reason"] == "paused"
    assert body["today"]["give"] is None
    give = url(shop.company, f"{routine.pk}/give-today/")
    assert owner_api(shop.owner).post(give, {}, format="json").status_code == 400
    assert owner_api(shop.worker).post(give, {}, format="json").status_code == 403
