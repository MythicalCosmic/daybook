"""The AI endpoints of both APIs: shapes, rights, scoping (v0.2 AI contract §4, §5)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.ai import conf
from apps.ai.models import AgentState, AIDraft
from apps.ai.tests.conftest import OGG
from apps.audit.models import AuditLog
from apps.companies.models import Branch, Feature
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

SAID = "Alisher, ertaga soat 10 gacha muzlatgich haroratini tekshirib, rasmini yubor."
DRAFT_KEYS = {
    "id",
    "status",
    "source",
    "author",
    "created_at",
    "audio",
    "transcript",
    "language",
    "engine",
    "drafts",
    "questions",
    "created_tasks",
    "error_code",
    "error",
}
ITEM_KEYS = {
    "title",
    "description",
    "assignee",
    "assignee_guess",
    "due_at",
    "due_text",
    "priority",
    "checklist",
    "proof",
    "problems",
}


def url(company, path=""):
    return f"/api/v1/companies/{company.pk}/ai/{path}"


def owner_url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/ai/{path}"


@pytest.fixture
def people(company, member, ai_on):
    ai_on(company)
    return {
        "manager": member.registered(company, "Manager", first_name="Bekzod", last_name="Mirzayev"),
        "alisher": member.registered(company, first_name="Alisher", last_name="Valiyev"),
        "owner": member.registered(company, "Owner", first_name="Dilnoza", last_name="Karimova"),
    }


def post_text(client, company, text=SAID, capture=None):
    if capture is None:
        return client.post(url(company, "task-drafts/"), {"text": text}, format="json")
    with capture(execute=True):
        return client.post(url(company, "task-drafts/"), {"text": text}, format="json")


def test_status_for_the_mini_app(api_as, people, company, settings):
    settings.EMPLOYEE_BOT_USERNAME = "daily_taskmanagment_bot"

    response = api_as(people["alisher"]).get(url(company, "status/"))

    assert response.status_code == 200
    assert response.json() == {
        "voice": False,  # no speech service
        "smart_text": True,
        "engine": "rules",
        "max_seconds": 120,
        "auto_create": False,
        "bot_username": "daily_taskmanagment_bot",
    }


def test_status_with_ai_off(api_as, company, member):
    worker = member.registered(company)

    assert api_as(worker).get(url(company, "status/")).json()["smart_text"] is False


def test_typed_text_gives_a_draft_in_the_contract_shape(
    api_as, people, company, django_capture_on_commit_callbacks
):
    client = api_as(people["manager"])

    created = post_text(client, company, capture=django_capture_on_commit_callbacks)

    assert created.status_code == 202
    body = client.get(url(company, f"task-drafts/{created.json()['id']}/")).json()
    assert set(body) == DRAFT_KEYS
    assert body["status"] == "ready"
    assert body["source"] == "miniapp"
    assert body["author"] == {"id": people["manager"].pk, "name": "Bekzod Mirzayev"}
    assert body["audio"] is None
    assert body["engine"] == "rules"
    [item] = body["drafts"]
    assert set(item) == ITEM_KEYS
    assert item["assignee"] == {
        "id": people["alisher"].pk,
        "name": "Alisher Valiyev",
        "position": people["alisher"].position.name if people["alisher"].position else "",
    }
    assert item["proof"] == "photo"
    assert item["due_at"].endswith("+05:00")
    # "ertaga" said before 05:00 is the coming morning (the night shift's rule, quickadd).
    assert item["due_text"].endswith(", 10:00")
    assert item["problems"] == []
    assert body["created_at"].endswith("+05:00")


def test_a_recording_is_uploaded_and_heard(
    api_as, people, company, settings, django_capture_on_commit_callbacks
):
    settings.AI_FAKE = True
    client = api_as(people["manager"])
    audio = SimpleUploadedFile("note.webm", OGG, content_type="audio/webm")

    with django_capture_on_commit_callbacks(execute=True):
        created = client.post(
            url(company, "task-drafts/"), {"audio": audio, "seconds": "7.5", "language": "uz"}
        )

    assert created.status_code == 202
    body = client.get(url(company, f"task-drafts/{created.json()['id']}/")).json()
    assert body["status"] == "ready"
    assert body["audio"]["seconds"] == 8
    assert body["audio"]["url"].startswith("/api/v1/files/")
    assert body["engine"] == "fake"
    # The signed link plays the recording, with byte ranges for Safari.
    played = client.get(body["audio"]["url"], HTTP_RANGE="bytes=0-3")
    assert played.status_code == 206
    assert played.content == b"OggS"
    assert played["Content-Type"] == "audio/ogg"


@pytest.mark.parametrize(
    ("payload", "code", "status"),
    [
        ({"text": "x" * 2001}, "text_too_long", 400),
        ({"audio": "garbage"}, "audio_unreadable", 400),
    ],
)
def test_errors_carry_a_code(api_as, people, company, settings, payload, code, status):
    settings.AI_FAKE = True
    if "audio" in payload:
        payload = {"audio": SimpleUploadedFile("a.ogg", b"<html>", content_type="audio/ogg")}
        response = api_as(people["manager"]).post(url(company, "task-drafts/"), payload)
    else:
        response = api_as(people["manager"]).post(
            url(company, "task-drafts/"), payload, format="json"
        )

    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["detail"]


def test_ai_off_is_403(api_as, company, member):
    worker = member.registered(company)

    response = api_as(worker).post(url(company, "task-drafts/"), {"text": "Kassa"}, format="json")

    assert response.status_code == 403
    assert response.json()["code"] == "ai_off"


def test_the_daily_limit_is_429(api_as, people, company):
    row = conf.get_settings(company)
    row.member_daily_drafts = 1
    row.save()
    client = api_as(people["manager"])
    assert post_text(client, company).status_code == 202

    response = post_text(client, company)

    assert response.status_code == 429
    assert response.json()["code"] == "limit_reached"


def test_drafts_are_their_authors_only(
    api_as, people, company, other_company, member, django_capture_on_commit_callbacks
):
    created = post_text(
        api_as(people["manager"]), company, capture=django_capture_on_commit_callbacks
    )
    draft_id = created.json()["id"]

    assert (
        api_as(people["alisher"]).get(url(company, f"task-drafts/{draft_id}/")).status_code == 404
    )
    stranger = member.registered(other_company)
    assert api_as(stranger).get(url(other_company, f"task-drafts/{draft_id}/")).status_code == 404
    applied = api_as(people["alisher"]).post(url(company, f"task-drafts/{draft_id}/apply/"))
    assert applied.status_code == 404


def test_apply_with_edits_and_twice(api_as, people, company, django_capture_on_commit_callbacks):
    client = api_as(people["manager"])
    draft_id = post_text(client, company, capture=django_capture_on_commit_callbacks).json()["id"]
    due = (timezone.now() + timedelta(days=1)).isoformat()
    edits = {
        "drafts": [
            {
                "title": "Muzlatgich haroratini tekshirish",
                "assignee_id": people["alisher"].pk,
                "due_at": due,
                "priority": "urgent",
                "checklist": ["Termometr"],
                "proof": "photo",
            },
            {"title": "Javonni tartibga keltirish", "assignee_id": None},
        ]
    }

    with django_capture_on_commit_callbacks(execute=True):
        first = client.post(url(company, f"task-drafts/{draft_id}/apply/"), edits, format="json")

    assert first.status_code == 200
    body = first.json()
    assert len(body["created"]) == 2 and body["failed"] == []
    assert body["draft"]["status"] == "applied"
    assert [t["title"] for t in body["draft"]["created_tasks"]] == [
        "Muzlatgich haroratini tekshirish",
        "Javonni tartibga keltirish",
    ]
    fridge = Task.objects.get(pk=body["created"][0])
    assert (fridge.priority, fridge.proof) == ("urgent", "photo")
    assert list(fridge.checklist.values_list("text", flat=True)) == ["Termometr"]
    assert Task.objects.get(pk=body["created"][1]).assignee == people["manager"]
    again = client.post(url(company, f"task-drafts/{draft_id}/apply/"), edits, format="json")
    assert again.status_code == 200 and again.json()["created"] == body["created"]
    assert Task.objects.count() == 2


def test_discard(api_as, people, company, django_capture_on_commit_callbacks):
    client = api_as(people["manager"])
    draft_id = post_text(client, company, capture=django_capture_on_commit_callbacks).json()["id"]

    assert client.post(url(company, f"task-drafts/{draft_id}/discard/")).status_code == 204
    assert AIDraft.objects.get(pk=draft_id).status == "discarded"
    applied = client.post(url(company, f"task-drafts/{draft_id}/apply/"))
    assert applied.status_code == 400


def test_problems_are_worked_out_when_read(
    api_as, people, company, django_capture_on_commit_callbacks
):
    client = api_as(people["manager"])
    draft_id = post_text(
        client, company, text="Nodir, kassani sana.", capture=django_capture_on_commit_callbacks
    ).json()["id"]

    [item] = client.get(url(company, f"task-drafts/{draft_id}/")).json()["drafts"]

    assert item["assignee"] is None
    assert item["assignee_guess"] == "Nodir"
    assert set(item["problems"]) == {"no_assignee_match", "no_due"}


# The owner API -----------------------------------------------------------------------------------


def test_owner_status_shows_the_budget_to_who_configures(owner_api, people, company):
    body = owner_api(people["owner"]).get(owner_url(company, "status/")).json()

    assert body["enabled"] is True
    assert body["can_configure"] is True
    assert body["claude"] == "not_configured"
    assert body["speech"] == "not_configured"
    assert body["features"] == {
        "voice": False,
        "smart_text": True,
        "chat": False,
        "photo_checker": False,
    }
    assert body["budget"]["monthly_usd"] == "20.00"
    assert body["budget"]["spent_usd"] == "0.00"
    manager_view = owner_api(people["manager"]).get(owner_url(company, "status/")).json()
    assert manager_view["budget"] is None
    assert manager_view["can_configure"] is False


def test_fake_ai_reads_as_fake(owner_api, people, company, settings):
    settings.AI_FAKE = True

    body = owner_api(people["owner"]).get(owner_url(company, "status/")).json()

    assert (body["claude"], body["speech"], body["features"]["voice"]) == ("fake", "fake", True)


def test_enable_records_the_consent_and_switches_the_default_agents_on(owner_api, company, member):
    owner = member.registered(company, "Owner")
    client = owner_api(owner)
    assert (
        client.post(owner_url(company, "settings/enable/"), {"accept_terms": False}).status_code
        == 400
    )

    response = client.post(
        owner_url(company, "settings/enable/"), {"accept_terms": True}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    company.refresh_from_db()
    assert Feature.AI in company.features
    row = conf.get_settings(company)
    assert row.enabled and row.enabled_by == owner.user and row.enabled_at
    assert AgentState.objects.get(company=company, key="voice_tasks").enabled
    assert AuditLog.objects.filter(action="ai.enabled").count() == 1

    off = client.post(owner_url(company, "settings/disable/"))
    assert off.json()["enabled"] is False
    assert AuditLog.objects.filter(action="ai.disabled").count() == 1


def test_settings_need_ai_configure(owner_api, people, company):
    assert owner_api(people["manager"]).get(owner_url(company, "settings/")).status_code == 403

    client = owner_api(people["owner"])
    body = client.get(owner_url(company, "settings/")).json()
    assert body["enabled_by_name"] == ""
    changed = client.patch(
        owner_url(company, "settings/"),
        {"monthly_budget_usd": "35.50", "voice_retention_days": 7},
        format="json",
    )
    assert changed.status_code == 200
    assert changed.json()["monthly_budget_usd"] == "35.50"
    assert AuditLog.objects.filter(action="ai.settings_changed").count() == 1
    assert (
        client.patch(
            owner_url(company, "settings/"), {"voice_retention_days": 0}, format="json"
        ).status_code
        == 400
    )


def test_owner_lists_drafts_in_their_scope(
    owner_api, api_as, people, company, member, django_capture_on_commit_callbacks
):
    post_text(api_as(people["manager"]), company, capture=django_capture_on_commit_callbacks)
    post_text(
        api_as(people["alisher"]),
        company,
        text="Kassani sana",
        capture=django_capture_on_commit_callbacks,
    )

    everyone = owner_api(people["owner"]).get(owner_url(company, "task-drafts/")).json()
    assert everyone["count"] == 2
    assert {row["author"]["name"] for row in everyone["results"]} == {
        "Bekzod Mirzayev",
        "Alisher Valiyev",
    }
    mine = owner_api(people["manager"]).get(owner_url(company, "task-drafts/")).json()
    assert mine["count"] in (1, 2)  # a manager with tasks.view_all sees their branch's too
    by_author = (
        owner_api(people["owner"])
        .get(owner_url(company, f"task-drafts/?author={people['alisher'].pk}&status=ready"))
        .json()
    )
    assert by_author["count"] == 1


def test_the_branch_scope_hides_other_branches_drafts(
    owner_api, api_as, company, member, ai_on, django_capture_on_commit_callbacks
):
    ai_on(company)
    north = Branch.objects.create(company=company, name="North")
    south = Branch.objects.create(company=company, name="South")
    head = member.registered(company, "Manager", home_branch=north)
    head.branches.set([north])
    head.role.permissions = [p for p in head.role.permissions if p != "branches.all"]
    head.role.save()
    far = member.registered(company, "Manager", home_branch=south)
    far.branches.set([south])
    post_text(api_as(far), company, text="Kassani sana", capture=django_capture_on_commit_callbacks)

    seen = owner_api(head).get(owner_url(company, "task-drafts/")).json()

    assert seen["count"] == 0


def test_dashboard_drafts_come_from_the_dashboard(
    owner_api, people, company, django_capture_on_commit_callbacks
):
    client = owner_api(people["owner"])

    with django_capture_on_commit_callbacks(execute=True):
        created = client.post(owner_url(company, "task-drafts/"), {"text": SAID}, format="json")

    assert created.status_code == 202
    assert created.json()["source"] == "dashboard"
    draft_id = created.json()["id"]
    with django_capture_on_commit_callbacks(execute=True):
        applied = client.post(owner_url(company, f"task-drafts/{draft_id}/apply/"))
    assert applied.json()["draft"]["status"] == "applied"
