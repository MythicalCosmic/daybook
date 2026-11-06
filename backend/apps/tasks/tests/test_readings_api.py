"""The readings endpoints (PLAN-OWNER §14.10): routines with the readings proof, the storage
preset, the routine journal and the month's PDF, today's excursions, Settings → Routines, the
task drawer and Today rows, and the mini app's complete and recheck. Every owner endpoint: another
company's id answers 404, a missing permission 403, and branch scope holds.

The clock is frozen on Wednesday 23 October 2030, 12:00 in the company's timezone."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.ai.tools.registry import ToolContext
from apps.companies.tests.factories import BranchFactory
from apps.members.tests.factories import PositionFactory
from apps.tasks import feeds, generation, services
from apps.tasks.ai_tools import TasksReadingsInput, tasks_readings
from apps.tasks.models import Proof, Task, TaskTemplate
from apps.tasks.tests.factories import make_shop

pytestmark = pytest.mark.django_db

WED = date(2030, 10, 23)
FRIDGE = {"key": "t", "label": "Fridge 1", "unit": "°C", "min": "2", "max": "8", "critical": True}


@pytest.fixture
def clock(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def at(company):
    tz = ZoneInfo(company.timezone)
    return lambda day, hour, minute=0: datetime.combine(day, time(hour, minute), tzinfo=tz)


@pytest.fixture
def shop(company, member, clock, at):
    clock(at(WED, 12) - timedelta(days=40))
    made = make_shop(company, member)
    clock(at(WED, 12))
    return made


def owner_url(company, path: str) -> str:
    return f"/api/v1/owner/companies/{company.pk}/{path}"


def employee(member) -> APIClient:
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(member.user).access_token}")
    return api


def routine_at(shop, branch=None, *, people=None, due=time(9)) -> TaskTemplate:
    template = services.create_template(
        by=shop.owner,
        title=f"Fridge {due:%H:%M}",
        due_time=due,
        proof=Proof.READINGS,
        readings=[FRIDGE],
        branch=branch or shop.here,
        assignees=people or [shop.worker],
    )
    TaskTemplate.objects.filter(pk=template.pk).update(
        created_at=template.created_at - timedelta(days=30)
    )
    template.refresh_from_db()
    return template


def run_of(template, person, day=WED) -> Task:
    due = generation.deadline(template, day, ZoneInfo(template.company.timezone))
    [task] = generation.build_tasks(template, day, due, people=[person], created_by=None, now=due)
    task.save()
    return task


# Routines with readings -----------------------------------------------------------------


def test_a_routine_is_made_with_readings_and_shared(shop, owner_api):
    response = owner_api(shop.owner).post(
        owner_url(shop.company, "routines/"),
        {
            "title": "Fridge, morning",
            "due_time": "09:00",
            "proof": "readings",
            "readings": [{"label": "Fridge 1", "unit": "°C", "min": "2", "max": "8"}],
            "shared": True,
            "branch_id": shop.here.pk,
            "assignee_ids": [shop.worker.pk],
        },
        format="json",
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["proof"] == "readings" and body["shared"] is True
    assert body["readings"] == [
        {
            "key": "a",
            "label": "Fridge 1",
            "unit": "°C",
            "min": "2.0",
            "max": "8.0",
            "critical": False,
        }
    ]


def test_a_readings_routine_without_specs_is_refused(shop, owner_api):
    response = owner_api(shop.owner).post(
        owner_url(shop.company, "routines/"),
        {
            "title": "Fridge",
            "due_time": "09:00",
            "proof": "readings",
            "branch_id": shop.here.pk,
            "assignee_ids": [shop.worker.pk],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not TaskTemplate.objects.filter(title="Fridge").exists()


def test_the_mini_apps_old_routine_form_cant_ask_for_readings(shop):
    response = employee(shop.manager).post(
        f"/api/v1/companies/{shop.company.pk}/task-templates/",
        {"title": "Fridge", "due_time": "09:00", "proof": "readings"},
        format="json",
    )

    assert response.status_code in (400, 404)
    assert not TaskTemplate.objects.filter(title="Fridge").exists()


# The routine journal and the month's PDF -----------------------------------------------


def test_the_routine_journal(shop, owner_api, clock, at):
    template = routine_at(shop)
    task = run_of(template, shop.worker)
    clock(at(WED, 9, 5))
    services.complete_task(task, by=shop.worker, readings={"t": "8,6"}, reading_note="Moved")
    clock(at(WED, 12))

    response = owner_api(shop.owner).get(
        owner_url(shop.company, f"routines/{template.pk}/readings/")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {"taken": 1, "excursions": 1, "rechecks": 0, "missed": 0}
    assert body["series"][-1] == {"date": "2030-10-23", "t": "8.6"}
    [row] = body["rows"]
    assert (row["value"], row["note"], row["time"], row["in_range"]) == (
        "8.6",
        "Moved",
        "09:05",
        False,
    )
    assert body["specs"][0]["label"] == "Fridge 1"


def test_the_journal_answers_404_outside_company_or_scope_and_403_without_rights(
    shop, owner_api, other_company, member
):
    theirs = routine_at(shop, shop.there, people=[shop.colleague])
    foreign = TaskTemplate.objects.create(
        company=other_company, title="X", due_time=time(9), proof=Proof.NONE
    )

    lead = owner_api(shop.lead).get(owner_url(shop.company, f"routines/{theirs.pk}/readings/"))
    other = owner_api(shop.owner).get(owner_url(shop.company, f"routines/{foreign.pk}/readings/"))
    worker = owner_api(shop.worker).get(owner_url(shop.company, f"routines/{theirs.pk}/readings/"))

    assert (lead.status_code, other.status_code, worker.status_code) == (404, 404, 403)


def test_the_month_pdf_downloads_through_a_signed_link(shop, owner_api, clock, at):
    template = routine_at(shop)
    task = run_of(template, shop.worker)
    clock(at(WED, 9, 5))
    services.complete_task(task, by=shop.worker, readings={"t": "5"})
    clock(at(WED, 12))

    response = owner_api(shop.owner).get(
        owner_url(shop.company, f"routines/readings/pdf/?branch={shop.here.pk}&month=2030-10")
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["name"].endswith("2030-10.pdf")
    download = Client().get(body["url"])
    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"
    assert b"".join(download.streaming_content).startswith(b"%PDF")


def test_the_month_pdf_keeps_branch_scope_and_rights(shop, owner_api, other_company):
    foreign = BranchFactory(company=other_company)
    url = "routines/readings/pdf/?branch={}&month=2030-10"

    lead = owner_api(shop.lead).get(owner_url(shop.company, url.format(shop.there.pk)))
    other = owner_api(shop.owner).get(owner_url(shop.company, url.format(foreign.pk)))
    worker = owner_api(shop.worker).get(owner_url(shop.company, url.format(shop.here.pk)))
    bad = owner_api(shop.owner).get(
        owner_url(shop.company, f"routines/readings/pdf/?branch={shop.here.pk}&month=10/2030")
    )

    assert (lead.status_code, other.status_code, worker.status_code) == (404, 404, 403)
    assert bad.status_code == 400


def test_today_and_the_badge(shop, owner_api, clock, at):
    task = run_of(routine_at(shop), shop.worker)
    clock(at(WED, 9, 5))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")
    clock(at(WED, 12))

    response = owner_api(shop.owner).get(owner_url(shop.company, "routines/readings/today/"))
    theirs = owner_api(shop.lead).get(owner_url(shop.company, "routines/readings/today/"))

    assert response.status_code == 200
    assert [item["value"] for item in response.json()["excursions"]] == ["9.0"]
    assert theirs.status_code == 200 and len(theirs.json()["excursions"]) == 1
    assert feeds.readings_alerts(shop.owner) == 1
    assert feeds.readings_alerts(shop.colleague) == 0  # no branch of theirs


# The storage preset ----------------------------------------------------------------------


def test_the_preset_dialog_defaults_and_apply(shop, owner_api, member):
    pharmacist = PositionFactory(company=shop.company, name="Farmatsevt")
    member.registered(shop.company, position=pharmacist, home_branch=shop.here)
    api = owner_api(shop.owner)

    defaults = api.get(owner_url(shop.company, f"routines/storage-preset/?branch={shop.here.pk}"))
    made = api.post(
        owner_url(shop.company, "routines/storage-preset/"),
        {"branch": shop.here.pk, "fridges": 1, "times": ["09:00"]},
        format="json",
    )

    assert defaults.status_code == 200
    assert defaults.json()["times"] == ["09:00", "20:00"]
    assert defaults.json()["fridge"] == {"min": "2.0", "max": "8.0"}
    assert [p["id"] for p in defaults.json()["positions"]] == [pharmacist.pk]
    assert made.status_code == 201, made.json()
    assert len(made.json()["created"]) == 5
    assert all(row["shared"] for row in made.json()["created"])


def test_the_preset_answers_404_outside_and_403_without_rights(shop, owner_api, other_company):
    foreign = BranchFactory(company=other_company)
    url = owner_url(shop.company, "routines/storage-preset/")

    other = owner_api(shop.owner).post(url, {"branch": foreign.pk}, format="json")
    lead = owner_api(shop.lead).post(url, {"branch": shop.there.pk}, format="json")
    worker = owner_api(shop.worker).post(url, {"branch": shop.here.pk}, format="json")

    assert (other.status_code, lead.status_code, worker.status_code) == (404, 404, 403)


# Settings → Routines ------------------------------------------------------------------


def test_routines_settings_read_and_change(shop, owner_api):
    url = owner_url(shop.company, "routines/settings/")

    read = owner_api(shop.worker).get(url)
    changed = owner_api(shop.owner).patch(
        url,
        {"storage_fridge_min": "3.0", "storage_times": ["08:00", "14:00", "20:00"]},
        format="json",
    )
    refused = owner_api(shop.manager).patch(url, {"storage_fridge_min": "1"}, format="json")
    wrong = owner_api(shop.owner).patch(url, {"storage_room_min": "30"}, format="json")

    assert read.status_code in (200, 403)
    assert changed.status_code == 200, changed.json()
    assert changed.json()["storage_fridge_min"] == "3.0"
    assert changed.json()["storage_times"] == ["08:00", "14:00", "20:00"]
    assert refused.status_code == 403
    assert wrong.status_code == 400  # 30 is above the room's highest, 25


# The drawer, Today and To confirm -----------------------------------------------------


def test_the_drawer_and_today_show_the_values(shop, owner_api, clock, at):
    template = routine_at(shop)
    task = run_of(template, shop.worker)
    clock(at(WED, 9, 5))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")
    clock(at(WED, 10))  # within the two hours a recheck may come
    api = owner_api(shop.owner)

    drawer = api.get(owner_url(shop.company, f"tasks/{task.pk}/")).json()
    day = api.get(owner_url(shop.company, "routines/day/?day=2030-10-23")).json()

    assert drawer["readings"][0]["label"] == "Fridge 1"
    assert [(row["value"], row["note"]) for row in drawer["readings_taken"]] == [("9.0", "Moved")]
    assert drawer["recheck_until"] is not None
    card = next(row for row in day["routines"] if row["routine"]["id"] == template.pk)
    assert card["counts"]["excursions"] == 1 and day["totals"]["excursions"] == 1
    assert card["runs"][0]["readings_taken"][0]["in_range"] is False
    assert card["routine"]["readings"][0]["max"] == "8.0"


# The mini app ---------------------------------------------------------------------------


def test_the_mini_app_completes_with_readings_and_rechecks(shop, clock, at):
    task = run_of(routine_at(shop), shop.worker)
    url = f"/api/v1/companies/{shop.company.pk}/tasks/{task.pk}/"
    api = employee(shop.worker)

    shown = api.get(url).json()
    refused = api.post(url + "complete/", {}, format="json")
    clock(at(WED, 9, 5))
    done = api.post(
        url + "complete/", {"readings": {"t": "8,9"}, "reading_note": "Moved"}, format="json"
    )
    clock(at(WED, 9, 40))
    again = api.post(url + "recheck/", {"readings": {"t": "5.1"}}, format="json")

    assert shown["proof"] == "readings" and shown["readings"][0]["min"] == "2.0"
    assert refused.status_code == 400
    assert "Enter the readings" in str(refused.json())
    assert done.status_code == 200, done.json()
    assert done.json()["status"] == "done"
    assert again.status_code == 200, again.json()
    values = [(row["value"], row["is_recheck"]) for row in again.json()["readings_taken"]]
    assert values == [("8.9", False), ("5.1", True)]


# Exports, the AI and the brief -----------------------------------------------------------


def test_the_exporter_keeps_branch_scope(shop, clock, at):
    ours, theirs = routine_at(shop), routine_at(shop, shop.there, people=[shop.colleague])
    for template, person in ((ours, shop.worker), (theirs, shop.colleague)):
        task = run_of(template, person)
        clock(at(WED, 9, 5))
        services.complete_task(task, by=person, readings={"t": "5"})
    clock(at(WED, 12))

    everyone = list(feeds.readings_export_rows(shop.owner, {}))
    lead = list(feeds.readings_export_rows(shop.lead, {}))

    assert len(everyone) == 2
    assert [row["branch"] for row in lead] == [shop.here.name]
    assert set(lead[0]) == {column[0] for column in feeds.READINGS_COLUMNS}


def test_the_ai_tool_reports_excursions_per_routine(shop, clock, at):
    task = run_of(routine_at(shop), shop.worker)
    clock(at(WED, 9, 5))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")
    clock(at(WED, 12))

    result = tasks_readings(ToolContext.for_member(shop.owner), TasksReadingsInput(days=3))
    scoped = tasks_readings(ToolContext.for_member(shop.lead), TasksReadingsInput(days=3))

    [row] = result.rows
    assert row["readings_taken"] == 1 and row["out_of_range"][0]["value"] == "9.0"
    assert len(scoped.rows) == 1
    alone = tasks_readings(
        ToolContext.for_member(shop.owner, switches=frozenset()), TasksReadingsInput(days=3)
    )
    assert "note" not in alone.rows[0]["out_of_range"][0]


def test_the_brief_adds_readings_only_once_they_are_set_up(shop, clock, at):
    plain = services.create_task(
        by=shop.owner, title="Count the till", assignee=shop.worker, due_at=at(WED, 18)
    )
    assert plain is not None
    before = feeds.brief(shop.company, WED, at(WED, 12), None)
    task = run_of(routine_at(shop), shop.worker)
    clock(at(WED, 9, 5))
    services.complete_task(task, by=shop.worker, readings={"t": "9"}, reading_note="Moved")
    clock(at(WED, 12))

    after = feeds.brief(shop.company, WED, at(WED, 12), None)

    assert "excursions" not in before
    assert [item["value"] for item in after["excursions"]] == ["9.0"]
    assert after["missed_readings"] == []
