"""Time off on the owner API: the list, deciding, recording, revoking, the calendar and the
numbers; plus the registrations (Needs you, calendar sources, offboarding step, AI tool)."""

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.companies.tests.factories import BranchFactory
from apps.console import registry
from apps.inbox.models import Notification
from apps.inbox.services import run_action
from apps.members.permissions import Perm
from apps.members.tests.ai import call_tool
from apps.members.tests.factories import AccessRoleFactory
from apps.timeoff import demo, services
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/time-off/"


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def setup(company, member):
    chilonzor = company.branches.first()
    yunusobod = BranchFactory(company=company, name="Yunusobod")
    owner = member.registered(company, "Owner", first_name="Dilnoza")
    near = member.registered(company, first_name="Ali", home_branch=chilonzor)
    near.branches.set([chilonzor])
    far = member.registered(company, first_name="Vali", home_branch=yunusobod)
    far.branches.set([yunusobod])
    role = AccessRoleFactory(
        company=company, permissions=[Perm.DASHBOARD_ACCESS, Perm.TIME_OFF_APPROVE]
    )
    lead = member.registered(company, role.name, first_name="Lola", home_branch=chilonzor)
    lead.branches.set([chilonzor])
    return {"owner": owner, "near": near, "far": far, "lead": lead, "yunusobod": yunusobod}


def asks(member, first, last=None):
    return TimeOff.objects.create(
        company=member.company, membership=member, first_day=first, last_day=last or first
    )


def test_the_list_is_branch_scoped(owner_api, company, setup, today):
    asks(setup["near"], today + timedelta(days=2))
    far_request = asks(setup["far"], today + timedelta(days=3))
    url = URL.format(cid=company.pk)

    everything = owner_api(setup["owner"]).get(url)
    mine = owner_api(setup["lead"]).get(url)

    assert everything.data["count"] == 2
    assert [row["member"]["name"] for row in mine.data["results"]] == ["Ali"]
    assert owner_api(setup["lead"]).get(url + f"{far_request.pk}/").status_code == 404


def test_filters(owner_api, company, setup, today):
    asks(setup["near"], today + timedelta(days=2))
    TimeOff.objects.create(
        company=company,
        membership=setup["far"],
        first_day=today + timedelta(days=20),
        last_day=today + timedelta(days=22),
        status=TimeOff.Status.APPROVED,
    )
    api = owner_api(setup["owner"])
    url = URL.format(cid=company.pk)

    assert api.get(url, {"status": "pending"}).data["count"] == 1
    assert api.get(url, {"from": (today + timedelta(days=21)).isoformat()}).data["count"] == 1
    assert api.get(url, {"branch": setup["yunusobod"].pk}).data["count"] == 1
    assert api.get(url, {"q": "vali"}).data["count"] == 1


def test_approve_from_the_dashboard_closes_the_telegram_copies(
    owner_api, company, setup, today, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        request = services.request_time_off(
            setup["near"], first_day=today + timedelta(days=4), last_day=today + timedelta(days=4)
        )
    copies = Notification.objects.filter(kind="timeoff.request")
    # The owner and the branch lead, not the person and not people of other branches.
    assert {copy.recipient for copy in copies} == {setup["owner"], setup["lead"]}

    with django_capture_on_commit_callbacks(execute=True):
        response = owner_api(setup["lead"]).post(
            URL.format(cid=company.pk) + f"{request.pk}/approve/"
        )

    assert response.status_code == 200
    assert response.data["status"] == "approved"
    assert not copies.filter(acted_at__isnull=True).exists()
    told = Notification.objects.get(kind="timeoff.decided")
    assert told.recipient == setup["near"] and "approved" in told.title


def test_the_telegram_button_decides_once(
    company, setup, today, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        request = services.request_time_off(
            setup["near"], first_day=today + timedelta(days=4), last_day=today + timedelta(days=4)
        )
    copy = Notification.objects.get(kind="timeoff.request", recipient=setup["owner"])

    message = run_action(copy.pk, "reject", by=setup["owner"])

    request.refresh_from_db()
    assert message == "Rejected" and request.status == TimeOff.Status.REJECTED
    assert not Notification.objects.filter(kind="timeoff.request", acted_at__isnull=True).exists()


def test_record_with_a_sick_note(owner_api, company, setup, today):
    out = BytesIO()
    Image.new("RGB", (20, 20), "white").save(out, "JPEG")
    note = SimpleUploadedFile("spravka.jpg", out.getvalue(), content_type="image/jpeg")

    response = owner_api(setup["owner"]).post(
        URL.format(cid=company.pk) + "record/",
        {
            "member_id": setup["near"].pk,
            "first_day": (today - timedelta(days=3)).isoformat(),
            "last_day": (today - timedelta(days=1)).isoformat(),
            "reason": "Sick leave",
            "attachment": note,
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["recorded_by"]["name"] == "Dilnoza"
    assert response.data["attachment"].startswith("/api/v1/files/")
    assert response.data["days"] == 3


def test_record_for_someone_outside_the_scope_is_refused(owner_api, company, setup, today):
    response = owner_api(setup["lead"]).post(
        URL.format(cid=company.pk) + "record/",
        {
            "member_id": setup["far"].pk,
            "first_day": today.isoformat(),
            "last_day": today.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 400


def test_revoke(owner_api, company, setup, today):
    time_off = TimeOff.objects.create(
        company=company,
        membership=setup["near"],
        first_day=today + timedelta(days=2),
        last_day=today + timedelta(days=4),
        status=TimeOff.Status.APPROVED,
    )

    response = owner_api(setup["owner"]).post(
        URL.format(cid=company.pk) + f"{time_off.pk}/revoke/",
        {"reason": "Inventory", "from_day": (today + timedelta(days=3)).isoformat()},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["last_day"] == (today + timedelta(days=2)).isoformat()
    assert response.data["revoke_reason"] == "Inventory"


def test_calendar_and_stats(owner_api, company, setup, today):
    TimeOff.objects.create(
        company=company,
        membership=setup["near"],
        first_day=today,
        last_day=today,
        status=TimeOff.Status.APPROVED,
    )
    asks(setup["far"], today + timedelta(days=1))
    Holiday.objects.create(company=company, date=today.replace(day=1), name="First")
    api = owner_api(setup["owner"])

    calendar = api.get(
        URL.format(cid=company.pk) + "calendar/",
        {"month": today.strftime("%Y-%m"), "everyone": "true"},
    )
    stats = api.get(URL.format(cid=company.pk) + "stats/")

    assert calendar.status_code == 200
    names = [row["member"]["name"] for row in calendar.data["rows"]]
    assert names[:2] == ["Ali", "Vali"] and "Dilnoza" in names
    assert calendar.data["holidays"][0]["name"] == "First"
    assert stats.data["off_today"] == 1
    assert stats.data["pending"] >= 1


def test_permissions_and_tenancy(owner_api, company, other_company, member, setup):
    worker = setup["near"]
    stranger = member.registered(other_company, "Owner")
    url = URL.format(cid=company.pk)

    assert owner_api(worker).get(url).status_code == 403
    assert owner_api(stranger).get(url).status_code == 404


def test_needs_you_items(company, setup, today):
    request = asks(setup["near"], today + timedelta(days=5))

    [item] = registry.queue_items(setup["lead"], kind="timeoff.request")

    assert item.id == request.pk
    assert [a.endpoint for a in item.actions] == [
        f"time-off/{request.pk}/approve/",
        f"time-off/{request.pk}/reject/",
    ]
    assert registry.queue_items(setup["near"], kind="timeoff.request") == []


def test_calendar_sources_and_offboarding_step(company, setup, today):
    TimeOff.objects.create(
        company=company,
        membership=setup["near"],
        first_day=today + timedelta(days=2),
        last_day=today + timedelta(days=3),
        status=TimeOff.Status.APPROVED,
    )
    Holiday.objects.create(company=company, date=today + timedelta(days=7), name="Navruz")

    items = registry.collect_calendar(setup["owner"], today, today + timedelta(days=10))
    kinds = {item.kind for item in items}
    assert {"timeoff.time_off", "timeoff.holiday"} <= kinds

    [step] = [
        s
        for s in registry.collect_offboard_steps(setup["near"], by=setup["owner"])
        if s["key"] == "timeoff"
    ]
    assert "will be cancelled" in step["lines"][0]


def test_ai_tool(company, setup, today):
    TimeOff.objects.create(
        company=company,
        membership=setup["far"],
        first_day=today,
        last_day=today,
        status=TimeOff.Status.APPROVED,
    )
    asks(setup["near"], today + timedelta(days=1))

    seen_by_lead = call_tool(
        "timeoff_overview", setup["lead"], start=str(today), end=str(today + timedelta(days=3))
    )
    seen_by_owner = call_tool(
        "timeoff_overview", setup["owner"], start=str(today), end=str(today + timedelta(days=3))
    )

    assert [row["name"] for row in seen_by_lead["rows"]] == ["Ali"]
    assert len(seen_by_owner["rows"]) == 2
    assert call_tool("timeoff_overview", setup["near"], start=str(today), end=str(today)) == {
        "error": "not_allowed"
    }


def test_demo(company, demo_people):
    people = demo_people(company)

    demo.seed(company, people, timezone.now())

    assert Holiday.objects.filter(company=company, name="Navro‘z bayrami").exists()
    statuses = set(TimeOff.objects.filter(company=company).values_list("status", flat=True))
    assert {"approved", "pending", "rejected"} <= statuses
    assert TimeOff.objects.filter(company=company, recorded_by__isnull=False).exists()
