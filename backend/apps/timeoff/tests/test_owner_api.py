"""Time off on the owner API: the list, deciding, recording, revoking, the calendar and the
numbers; plus the registrations (Needs you, calendar sources, offboarding step, AI tool)."""

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.ai.tools.testing import call_tool
from apps.companies.tests.factories import BranchFactory
from apps.console import registry
from apps.inbox.models import Notification
from apps.inbox.services import run_action
from apps.members.permissions import Perm
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
    assert {"timeoff.time_off", "timeoff.holidays"} <= kinds

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

    # Pharmacies work on public holidays: the pharmacy has none.
    assert not Holiday.objects.filter(company=company).exists()
    statuses = set(TimeOff.objects.filter(company=company).values_list("status", flat=True))
    assert {"approved", "pending", "rejected"} <= statuses
    assert TimeOff.objects.filter(company=company, recorded_by__isnull=False).exists()


# Every endpoint against the owner-API rules (§2.3 rule 21) -----------------------------------


@pytest.fixture
def both(company, other_company, member, setup, today):
    """A request, approved time off and a holiday here and in another company."""

    def records(target, owner, person):
        return {
            "owner": owner,
            "person": person,
            "request": asks(person, today + timedelta(days=4)),
            "approved": TimeOff.objects.create(
                company=target,
                membership=person,
                first_day=today + timedelta(days=10),
                last_day=today + timedelta(days=11),
                status=TimeOff.Status.APPROVED,
            ),
            "holiday": Holiday.objects.create(company=target, date=today, name="Day"),
        }

    theirs_owner = member.registered(other_company, "Owner")
    theirs_person = member.registered(other_company)
    return (
        records(company, setup["owner"], setup["near"]),
        records(other_company, theirs_owner, theirs_person),
    )


def endpoints(objects, today) -> list[tuple[str, str, dict]]:
    request, approved, holiday = (
        objects["request"].pk,
        objects["approved"].pk,
        objects["holiday"].pk,
    )
    day = str(today + timedelta(days=20))
    return [
        ("get", "time-off/", {}),
        ("get", f"time-off/{request}/", {}),
        ("post", f"time-off/{request}/approve/", {}),
        ("post", f"time-off/{request}/reject/", {}),
        ("post", f"time-off/{approved}/revoke/", {"reason": "Busy week"}),
        (
            "post",
            "time-off/record/",
            {"member_id": objects["person"].pk, "first_day": day, "last_day": day},
        ),
        ("get", "time-off/calendar/", {}),
        ("get", "time-off/stats/", {}),
        ("get", "holidays/", {}),
        ("post", "holidays/", {"date": day, "name": "Extra"}),
        ("patch", f"holidays/{holiday}/", {"name": "Renamed"}),
        ("delete", f"holidays/{holiday}/", {}),
        ("post", "holidays/public/", {"year": 2027}),
    ]


def call(client, method, url, body):
    return (
        getattr(client, method)(url, body, format="json") if body else getattr(client, method)(url)
    )


def at(company, suffix):
    return f"/api/v1/owner/companies/{company.pk}/{suffix}"


def test_another_companys_member_gets_404_everywhere(owner_api, company, both, today):
    ours, theirs = both
    stranger = owner_api(theirs["owner"])

    for method, suffix, body in endpoints(ours, today):
        response = call(stranger, method, at(company, suffix), body)
        assert response.status_code == 404, (method, suffix, response.status_code)


def test_another_companys_ids_are_404_in_our_urls(owner_api, company, both, today):
    ours, theirs = both
    api = owner_api(ours["owner"])

    for method, suffix, body in endpoints(theirs, today):
        if suffix == "time-off/record/":
            response = call(api, method, at(company, suffix), body)
            assert response.status_code == 400  # their person isn't ours to record for
            continue
        if not any(char.isdigit() for char in suffix):
            continue
        response = call(api, method, at(company, suffix), body)
        assert response.status_code == 404, (method, suffix, response.status_code)
    assert not TimeOff.objects.filter(membership=theirs["person"], recorded_by__isnull=False)


def test_without_time_off_approve_every_endpoint_is_403(owner_api, company, member, both, today):
    ours, _theirs = both
    role = AccessRoleFactory(company=company, permissions=[Perm.DASHBOARD_ACCESS])
    nobody = member.registered(company, role.name)
    api = owner_api(nobody)

    for method, suffix, body in endpoints(ours, today):
        response = call(api, method, at(company, suffix), body)
        assert response.status_code == 403, (method, suffix, response.status_code)


def test_lists_dont_grow_queries_with_rows(owner_api, company, member, setup, today):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    api = owner_api(setup["owner"])
    urls = [
        at(company, "time-off/"),
        at(company, "time-off/calendar/?everyone=1"),
        at(company, "holidays/"),
    ]

    def count(url):
        with CaptureQueriesContext(connection) as captured:
            assert api.get(url).status_code == 200
        return len(captured)

    services.record_time_off(
        setup["near"], by=setup["owner"], first_day=today, last_day=today, reason="Sick"
    )
    Holiday.objects.create(company=company, date=today + timedelta(days=40), name="One")
    few = {url: count(url) for url in urls}
    branch = company.branches.first()
    for index in range(8):
        person = member.registered(company, home_branch=branch)
        person.branches.set([branch])
        services.record_time_off(
            person,
            by=setup["owner"],
            first_day=today + timedelta(days=index),
            last_day=today + timedelta(days=index + 1),
        )
        asks(person, today + timedelta(days=20 + index))
        Holiday.objects.create(company=company, date=today + timedelta(days=50 + index), name="H")

    for url in urls:
        assert count(url) <= few[url], url


def test_the_ai_tool_looks_at_a_year_at_most(company, setup, today):
    far_future = TimeOff.objects.create(
        company=company,
        membership=setup["near"],
        first_day=today + timedelta(days=500),
        last_day=today + timedelta(days=501),
        status=TimeOff.Status.APPROVED,
    )

    result = call_tool(
        "timeoff_overview", setup["owner"], start=str(today), end=str(today + timedelta(days=900))
    )

    assert far_future.pk not in [row["id"] for row in result["rows"]]
