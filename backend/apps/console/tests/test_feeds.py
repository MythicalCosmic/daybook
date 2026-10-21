"""`search/`, `queue/`, `queue/counts/` and `stream/` over the registered providers."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.console import registry
from apps.console.registry import QueueAction, QueueItem, SearchHit, StreamItem
from apps.members.permissions import Perm

# Every registry starts empty: the feeds carry exactly the providers registered here.
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("empty_registries")]

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def url(company, path) -> str:
    return f"/api/v1/owner/companies/{company.pk}/{path}"


@pytest.fixture
def providers(empty_registries):
    def people(member, q, limit):
        return [SearchHit("console.person", 1, f"Ali ({q})", "Cashier", "/people/1")]

    def payslips(member, q, limit):
        return [SearchHit("console.payslip", 9, "October", "", "/payroll/9")]

    registry.register_search("console.person", perm=Perm.MEMBERS_VIEW, search=people)
    registry.register_search("console.payslip", perm=Perm.PAYROLL_VIEW, search=payslips)

    approve = QueueAction("approve", "Approve", "primary", "POST", "time-off/42/approve/")
    reject = QueueAction(
        "reject", "Reject", "danger", "POST", "time-off/42/reject/", needs_reason=True
    )
    registry.register_queue(
        "console.time_off",
        perm=Perm.TIME_OFF_APPROVE,
        label="Time off",
        count=lambda m: 1,
        items=lambda m, limit: [
            QueueItem(
                "console.time_off", 42, "Ali: 3 days", "14-16 Oct", NOW, "/x", [approve, reject]
            )
        ],
    )
    registry.register_queue(
        "console.advances",
        perm=Perm.PAYROLL_MANAGE,
        label="Advances",
        count=lambda m: 3,
        items=lambda m, limit: [],
    )
    registry.register_stream(
        "console.tasks",
        perm=None,
        fetch=lambda m, since, limit: [
            StreamItem(
                NOW,
                "console.tasks",
                {"id": 1, "name": "Ali"},
                "Done: shelves",
                "/t/1",
                "/media/proofs/thumbs/1/a.webp",
            ),
            StreamItem(NOW - timedelta(hours=2), "console.tasks", None, "Done: floor", "/t/2"),
        ],
    )


@pytest.mark.usefixtures("providers")
def test_search_returns_hits_the_member_may_see(company, member, owner_api):
    manager = member(company, "Manager")

    response = owner_api(manager).get(url(company, "search/"), {"q": "ali"})

    assert response.status_code == 200
    assert response.data["results"] == [
        {
            "type": "console.person",
            "id": 1,
            "title": "Ali (ali)",
            "subtitle": "Cashier",
            "url": "/people/1",
        }
    ]


@pytest.mark.usefixtures("providers")
def test_search_needs_two_characters_and_filters_types(company, member, owner_api):
    owner = member(company, "Owner")
    client = owner_api(owner)

    assert client.get(url(company, "search/"), {"q": "a"}).data["results"] == []
    response = client.get(url(company, "search/"), {"q": "oct", "types": "console.payslip"})
    assert [hit["type"] for hit in response.data["results"]] == ["console.payslip"]


@pytest.mark.usefixtures("providers")
def test_queue_lists_items_with_relative_actions(company, member, owner_api):
    manager = member(company, "Manager")

    response = owner_api(manager).get(url(company, "queue/"))

    assert response.status_code == 200
    [item] = response.data["items"]
    assert item["kind"] == "console.time_off"
    assert item["created_at"] == "2026-10-20T09:00:00+00:00"
    assert item["actions"][0]["endpoint"] == "time-off/42/approve/"
    assert item["actions"][1]["needs_reason"] is True


@pytest.mark.usefixtures("providers")
def test_queue_counts_per_kind(company, member, owner_api):
    owner, manager = member(company, "Owner"), member(company, "Manager")

    as_owner = owner_api(owner).get(url(company, "queue/counts/")).data
    as_manager = owner_api(manager).get(url(company, "queue/counts/")).data

    assert as_owner["total"] == 4
    assert as_manager == {
        "total": 1,
        "kinds": [{"kind": "console.time_off", "label": "Time off", "count": 1}],
    }


@pytest.mark.usefixtures("providers")
def test_queue_filters_by_kind_and_checks_limit(company, member, owner_api):
    owner = member(company, "Owner")
    client = owner_api(owner)

    assert client.get(url(company, "queue/"), {"kind": "console.advances"}).data["items"] == []
    assert client.get(url(company, "queue/"), {"limit": "lots"}).status_code == 400


@pytest.mark.usefixtures("providers")
def test_stream_newest_first_with_since(company, member, owner_api):
    owner = member(company, "Owner")
    client = owner_api(owner)

    items = client.get(url(company, "stream/")).data["items"]
    assert [item["title"] for item in items] == ["Done: shelves", "Done: floor"]
    assert items[0]["actor"] == {"id": 1, "name": "Ali"}
    assert items[0]["photo_url"] == "/media/proofs/thumbs/1/a.webp"

    newer = client.get(url(company, "stream/"), {"since": "2026-10-20T08:00:00Z"}).data["items"]
    assert [item["title"] for item in newer] == ["Done: shelves"]
    assert client.get(url(company, "stream/"), {"since": "yesterday"}).status_code == 400


@pytest.mark.parametrize("path", ["search/?q=ali", "queue/", "queue/counts/", "stream/"])
def test_every_feed_is_company_scoped(company, other_company, member, owner_api, path):
    outsider = member(other_company, "Owner")
    employee = member(company)

    assert owner_api(outsider).get(url(company, path)).status_code == 404
    assert owner_api(employee).get(url(company, path)).status_code == 403
