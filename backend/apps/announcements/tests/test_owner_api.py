"""Announcements on the owner API: list with read rates, publish, receipts, follow-up actions,
the audience count; registrations and demo data."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.announcements import demo, services
from apps.announcements.models import Announcement, Receipt
from apps.console import registry
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/announcements/"


@pytest.fixture
def team(company, member):
    owner = member.registered(company, "Owner", first_name="Dilnoza")
    people = [member.registered(company, first_name=name) for name in ("A", "B", "C", "D")]
    for person in people:
        person.branches.set([company.branches.first()])
    return owner, people


def test_publish_now_from_the_composer(owner_api, company, team):
    owner, people = team
    cashier = PositionFactory(company=company, name="Cashier")
    for person in people[:2]:
        person.position = cashier
        person.save()

    response = owner_api(owner).post(
        URL.format(cid=company.pk),
        {"text_html": "<p>Hello <strong>cashiers</strong></p>", "position_ids": [cashier.pk]},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["text"] == "Hello <b>cashiers</b>"
    assert response.data["status"] == "sent"
    assert response.data["recipients_count"] == 2
    assert response.data["positions"] == [{"id": cashier.pk, "name": "Cashier"}]


def test_schedule_pin_and_expire(owner_api, company, team):
    owner, _ = team
    now = timezone.now()

    response = owner_api(owner).post(
        URL.format(cid=company.pk),
        {
            "text_html": "<p>Saturday inventory</p>",
            "scheduled_for": (now + timedelta(days=1)).isoformat(),
            "pinned_until": (now + timedelta(days=3)).isoformat(),
            "expires_at": (now + timedelta(days=5)).isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == "scheduled"
    assert response.data["recipients_count"] == 0
    announcement_id = response.data["id"]

    edited = owner_api(owner).patch(
        URL.format(cid=company.pk) + f"{announcement_id}/",
        {"text_html": "<p>Saturday inventory at <b>08:00</b></p>"},
        format="json",
    )
    assert edited.status_code == 200
    assert edited.data["text"] == "Saturday inventory at <b>08:00</b>"
    cancelled = owner_api(owner).post(URL.format(cid=company.pk) + f"{announcement_id}/cancel/")
    assert cancelled.data["status"] == "cancelled"


def test_list_with_read_rates_and_stats(owner_api, company, team):
    owner, people = team
    announcement = services.publish(owner, "Read me")
    for person in people[:3]:
        Receipt.objects.filter(announcement=announcement, membership=person).update(
            read_at=timezone.now()
        )

    listed = owner_api(owner).get(URL.format(cid=company.pk))
    stats = owner_api(owner).get(URL.format(cid=company.pk) + "stats/")

    [row] = listed.data["results"]
    assert (row["read_count"], row["recipients_count"], row["read_rate"]) == (3, 4, "75.0")
    assert stats.data["sent_30d"] == 1 and stats.data["read_rate_30d"] == "75.0"


def test_receipts_remind_and_pins(
    owner_api, company, team, sent_messages, django_capture_on_commit_callbacks
):
    owner, people = team
    announcement = services.publish(owner, "Read me")
    Receipt.objects.filter(announcement=announcement, membership=people[0]).update(
        read_at=timezone.now()
    )
    api = owner_api(owner)
    base = URL.format(cid=company.pk) + f"{announcement.pk}/"

    unread = api.get(base + "receipts/", {"state": "unread"})
    assert unread.data["count"] == 3
    with django_capture_on_commit_callbacks(execute=True):
        reminded = api.post(base + "remind/")
    assert reminded.data == {"reminded": 3}

    pinned = api.post(
        base + "pin/",
        {"pinned_until": (timezone.now() + timedelta(days=2)).isoformat()},
        format="json",
    )
    assert pinned.data["is_pinned"] is True
    unpinned = api.post(base + "unpin/")
    assert unpinned.data["is_pinned"] is False


def test_audience_count(owner_api, company, team):
    owner, people = team
    cook = PositionFactory(company=company, name="Courier")
    people[0].position = cook
    people[0].save()

    response = owner_api(owner).get(URL.format(cid=company.pk) + "audience/", {"position": cook.pk})

    assert response.data["count"] == 1
    assert response.data["sample"] == [{"id": people[0].pk, "name": "A"}]


def test_permissions_and_tenancy(owner_api, company, other_company, member, team):
    owner, people = team
    announcement = services.publish(owner, "Hi")
    stranger = member.registered(other_company, "Owner")

    assert owner_api(people[0]).get(URL.format(cid=company.pk)).status_code == 403
    assert owner_api(stranger).get(URL.format(cid=company.pk)).status_code == 404
    assert (
        owner_api(stranger)
        .get(URL.format(cid=other_company.pk) + f"{announcement.pk}/")
        .status_code
        == 404
    )


def test_registrations(company, team):
    owner, _ = team
    services.publish(owner, "<b>Uniform</b> from Monday")

    hits = registry.run_search(owner, "uniform", types=["announcements.announcement"])
    stream = registry.run_stream(owner)
    rates = call_tool(
        "announcements_stats",
        owner,
        start=str(timezone.localdate() - timedelta(days=1)),
        end=str(timezone.localdate()),
    )

    assert [hit.title for hit in hits] == ["Uniform from Monday"]
    assert any(item.kind == "announcements.sent" for item in stream)
    assert rates["rows"][0]["recipients"] == 4


def test_demo(company, demo_people):
    people = demo_people(company)

    demo.seed(company, people, timezone.now())

    statuses = set(Announcement.objects.filter(company=company).values_list("status", flat=True))
    assert statuses == {"sent", "scheduled", "cancelled"}
    assert Receipt.objects.filter(announcement__company=company, read_at__isnull=False).exists()
    assert Announcement.objects.filter(company=company, pinned_until__gt=timezone.now()).exists()


# Every endpoint against the owner-API rules (§2.3 rule 21) -----------------------------------


def endpoints(sent, scheduled) -> list[tuple[str, str, dict]]:
    later = (timezone.now() + timedelta(days=2)).isoformat()
    return [
        ("get", "announcements/", {}),
        ("post", "announcements/", {"text_html": "<p>Hi</p>"}),
        ("get", f"announcements/{sent.pk}/", {}),
        ("patch", f"announcements/{scheduled.pk}/", {"text_html": "<p>Changed</p>"}),
        ("get", f"announcements/{sent.pk}/receipts/", {}),
        ("post", f"announcements/{sent.pk}/remind/", {}),
        ("post", f"announcements/{scheduled.pk}/cancel/", {}),
        ("post", f"announcements/{sent.pk}/pin/", {"pinned_until": later}),
        ("post", f"announcements/{sent.pk}/unpin/", {}),
        ("get", "announcements/audience/", {}),
        ("get", "announcements/stats/", {}),
    ]


def call(client, method, url, body):
    return (
        getattr(client, method)(url, body, format="json") if body else getattr(client, method)(url)
    )


def at(company, suffix):
    return f"/api/v1/owner/companies/{company.pk}/{suffix}"


@pytest.fixture
def both(company, other_company, member, team):
    owner, _people = team
    theirs = member.registered(other_company, "Owner")
    member.registered(other_company)
    later = timezone.now() + timedelta(days=1)
    return (
        owner,
        services.publish(owner, "Ours"),
        services.publish(owner, "Ours later", scheduled_for=later),
        theirs,
        services.publish(theirs, "Theirs"),
        services.publish(theirs, "Theirs later", scheduled_for=later),
    )


def test_another_companys_member_gets_404_everywhere(owner_api, company, both):
    _owner, sent, scheduled, theirs, _their_sent, _their_scheduled = both

    for method, suffix, body in endpoints(sent, scheduled):
        response = call(owner_api(theirs), method, at(company, suffix), body)
        assert response.status_code == 404, (method, suffix, response.status_code)


def test_another_companys_ids_are_404_in_our_urls(owner_api, company, other_company, both):
    owner, _sent, _scheduled, _theirs, their_sent, their_scheduled = both
    api = owner_api(owner)

    for method, suffix, body in endpoints(their_sent, their_scheduled):
        if not any(char.isdigit() for char in suffix):
            continue
        response = call(api, method, at(company, suffix), body)
        assert response.status_code == 404, (method, suffix, response.status_code)
    their_scheduled.refresh_from_db()
    assert their_scheduled.status == Announcement.Status.SCHEDULED


def test_another_companys_positions_and_branches_are_refused(
    owner_api, company, other_company, team
):
    owner, _people = team
    foreign_position = PositionFactory(company=other_company)
    foreign_branch = other_company.branches.first()
    api = owner_api(owner)

    to_position = api.post(
        URL.format(cid=company.pk),
        {"text_html": "<p>Cooks only</p>", "position_ids": [foreign_position.pk]},
        format="json",
    )
    to_branch = api.post(
        URL.format(cid=company.pk),
        {"text_html": "<p>Branch only</p>", "branch_ids": [foreign_branch.pk]},
        format="json",
    )

    # Dropping the unknown id would have sent it to everyone.
    assert to_position.status_code == 400 and "position_ids" in to_position.data
    assert to_branch.status_code == 400 and "branch_ids" in to_branch.data
    assert not Announcement.objects.filter(company=company).exists()


def test_without_the_permission_every_endpoint_is_403(owner_api, company, member, both):
    _owner, sent, scheduled, *_rest = both
    from apps.members.permissions import Perm
    from apps.members.tests.factories import AccessRoleFactory

    role = AccessRoleFactory(company=company, permissions=[Perm.DASHBOARD_ACCESS])
    api = owner_api(member.registered(company, role.name))

    for method, suffix, body in endpoints(sent, scheduled):
        response = call(api, method, at(company, suffix), body)
        assert response.status_code == 403, (method, suffix, response.status_code)


def test_lists_dont_grow_queries_with_rows(owner_api, company, team):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    owner, people = team
    api = owner_api(owner)
    first = services.publish(owner, "First", [], branch_ids=[company.branches.first().pk])
    urls = [URL.format(cid=company.pk), URL.format(cid=company.pk) + f"{first.pk}/receipts/"]

    def count(url):
        with CaptureQueriesContext(connection) as captured:
            assert api.get(url).status_code == 200
        return len(captured)

    few = {url: count(url) for url in urls}
    position = PositionFactory(company=company)
    for index in range(8):
        services.publish(owner, f"Note {index}", [position.pk], branch_ids=[])
    for person in people:
        services.read(first, by=person)

    for url in urls:
        assert count(url) <= few[url], url


def test_editing_the_text_keeps_the_pin_and_expiry(owner_api, company, team):
    owner, _people = team
    later = timezone.now() + timedelta(days=1)
    scheduled = services.publish(
        owner,
        "Inventory",
        scheduled_for=later,
        pinned_until=later + timedelta(days=2),
        expires_at=later + timedelta(days=5),
    )

    response = owner_api(owner).patch(
        URL.format(cid=company.pk) + f"{scheduled.pk}/", {"text_html": "<p>Stock count</p>"}
    )
    changed = services.update_scheduled(scheduled, by=owner, text="Stock count!")

    assert response.status_code == 200
    assert changed.pinned_until == later + timedelta(days=2)
    assert changed.expires_at == later + timedelta(days=5)
    unpinned = services.update_scheduled(scheduled, by=owner, pinned_until=None)
    assert unpinned.pinned_until is None and unpinned.expires_at is not None
