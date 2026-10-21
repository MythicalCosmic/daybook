"""Every people, join request, role and position endpoint against the owner-API rules (§2.3 rule
21, §5, §2.6): another company's id answers 404 (in its URL and as an id in ours), a missing
permission 403, lists cost the same number of queries for 3 people as for 12, and fields the
dashboard doesn't need (Telegram ids) never leave the server."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.members import services
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, PositionFactory

pytestmark = pytest.mark.django_db

BASE = "/api/v1/owner/companies/{cid}/"


def path(company, suffix: str) -> str:
    return BASE.format(cid=company.pk) + suffix


@pytest.fixture
def world(company, other_company, member):
    """Our owner, someone to act on, a request, a role and a position; the same in another
    company; and a member who may open the dashboard and nothing else."""
    branch = company.branches.first()

    def placed(target, role="Employee", **kwargs):
        person = member.registered(target, role, home_branch=target.branches.first(), **kwargs)
        person.branches.set([target.branches.first()])
        return person

    ours = {
        "owner": placed(company, "Owner", first_name="Dilnoza"),
        "person": placed(company, first_name="Ali"),
        "request": _request(company, member),
        "role": AccessRoleFactory(company=company, name="Helpers", permissions=[]),
        "position": PositionFactory(company=company, name="Cook"),
    }
    theirs = {
        "owner": placed(other_company, "Owner"),
        "person": placed(other_company),
        "request": _request(other_company, member),
        "role": AccessRoleFactory(company=other_company, name="Helpers", permissions=[]),
        "position": PositionFactory(company=other_company, name="Cook"),
    }
    viewer_role = AccessRoleFactory(
        company=company, name="Viewer", permissions=[str(Perm.DASHBOARD_ACCESS)]
    )
    nobody = member.registered(company, viewer_role.name, home_branch=branch)
    nobody.branches.set([branch])
    return ours, theirs, nobody


def _request(company, member):
    """A join request ready for a decision."""
    from apps.members.tests.factories import MembershipFactory

    return MembershipFactory(
        company=company,
        status=Membership.Status.PENDING,
        role=None,
        onboarded_at=timezone.now(),
        user__phone="+998901110000",
    )


def endpoints(objects) -> list[tuple[str, str, dict]]:
    """(method, path suffix, body) of every endpoint, aimed at `objects`."""
    person, request = objects["person"].pk, objects["request"].pk
    role, position = objects["role"].pk, objects["position"].pk
    return [
        ("get", "people/", {}),
        ("get", "people/stats/", {}),
        ("get", f"people/{person}/", {}),
        ("patch", f"people/{person}/", {"first_name": "X"}),
        ("post", f"people/{person}/block/", {}),
        ("post", f"people/{person}/unblock/", {}),
        ("post", f"people/{person}/suspend/", {"reason": "Inquiry"}),
        ("post", f"people/{person}/reinstate/", {}),
        ("get", f"people/{person}/offboard-preview/", {}),
        ("post", f"people/{person}/offboard/", {"reason": "resignation"}),
        ("get", f"people/{person}/history/", {}),
        ("get", "join-requests/", {}),
        ("post", f"join-requests/{request}/approve/", {}),
        ("post", f"join-requests/{request}/reject/", {}),
        ("get", "roles/", {}),
        ("post", "roles/", {"name": "New", "permissions": []}),
        ("patch", f"roles/{role}/", {"name": "Renamed"}),
        ("delete", f"roles/{role}/", {}),
        ("get", "positions/", {}),
        ("post", "positions/", {"name": "Baker"}),
        ("patch", f"positions/{position}/", {"name": "Chef"}),
        ("delete", f"positions/{position}/", {}),
        ("post", "positions/reorder/", {"ids": [position]}),
    ]


def call(client, method: str, url: str, body: dict):
    return (
        getattr(client, method)(url, body, format="json") if body else getattr(client, method)(url)
    )


def test_another_companys_member_gets_404_everywhere(owner_api, company, world):
    ours, theirs, _nobody = world
    stranger = owner_api(theirs["owner"])

    for method, suffix, body in endpoints(ours):
        response = call(stranger, method, path(company, suffix), body)
        assert response.status_code == 404, (method, suffix, response.status_code)


def test_another_companys_ids_are_404_in_our_urls(owner_api, company, world):
    ours, theirs, _nobody = world
    api = owner_api(ours["owner"])

    for method, suffix, body in endpoints(theirs):
        if not any(char.isdigit() for char in suffix):
            continue  # lists, numbers and creates name no record
        response = call(api, method, path(company, suffix), body)
        assert response.status_code == 404, (method, suffix, response.status_code)
    # Ids inside a body are checked too.
    approve = api.post(
        path(company, f"join-requests/{ours['request'].pk}/approve/"),
        {"role_id": theirs["role"].pk},
        format="json",
    )
    assert approve.status_code == 404
    moved = api.patch(
        path(company, f"people/{ours['person'].pk}/"),
        {"position_id": theirs["position"].pk},
        format="json",
    )
    assert moved.status_code == 400
    assert (
        api.post(
            path(company, "positions/reorder/"), {"ids": [theirs["position"].pk]}, format="json"
        ).status_code
        == 400
    )


def test_without_the_permission_every_endpoint_is_403(owner_api, company, world):
    ours, _theirs, nobody = world
    api = owner_api(nobody)

    for method, suffix, body in endpoints(ours):
        response = call(api, method, path(company, suffix), body)
        if (method, suffix) == ("get", "positions/"):
            assert response.status_code == 200  # pickers everywhere list positions
            continue
        assert response.status_code == 403, (method, suffix, response.status_code)


def queries_for(client, url) -> int:
    with CaptureQueriesContext(connection) as captured:
        assert client.get(url).status_code == 200
    return len(captured)


def test_lists_dont_grow_queries_with_rows(owner_api, company, member, world):
    ours, _theirs, _nobody = world
    api = owner_api(ours["owner"])
    branch = company.branches.first()
    urls = [
        path(company, "people/"),
        path(company, "join-requests/"),
        path(company, "roles/"),
        path(company, "positions/"),
        path(company, f"people/{ours['person'].pk}/history/"),
    ]
    _request(company, member)
    services.update_member(ours["person"], by=ours["owner"], first_name="Alisher")
    few = {url: queries_for(api, url) for url in urls}

    for index in range(9):
        position = PositionFactory(company=company, name=f"Job {index}")
        person = member.registered(company, home_branch=branch, position=position)
        person.branches.set([branch])
        AccessRoleFactory(company=company, name=f"Role {index}", permissions=[])
        _request(company, member)
        services.update_member(ours["person"], by=ours["owner"], first_name=f"Ali {index}")
    # Former employees asking again, for the "worked here before" badge.
    gone = _request(company, member)
    AuditLog.objects.create(
        company=company,
        action=AuditLog.Action.MEMBER_LEFT,
        target_type="membership",
        target_id=gone.pk,
        details={"terminated_on": "2026-01-31"},
    )

    for url in urls:
        assert queries_for(api, url) <= few[url], url


def test_former_people_show_when_they_joined_and_left(owner_api, company, member, world):
    ours, _theirs, _nobody = world
    person = ours["person"]
    approved = timezone.now() - timedelta(days=400)
    AuditLog.objects.create(
        company=company,
        action=AuditLog.Action.MEMBER_APPROVED,
        target_type="membership",
        target_id=person.pk,
    )
    AuditLog.objects.filter(target_id=person.pk, action=AuditLog.Action.MEMBER_APPROVED).update(
        created_at=approved
    )
    last_day = timezone.localdate() - timedelta(days=3)
    services.offboard(person, by=ours["owner"].user, terminated_on=last_day)

    api = owner_api(ours["owner"])
    detail = api.get(path(company, f"people/{person.pk}/")).data
    row = next(
        r
        for r in api.get(path(company, "people/"), {"status": "former"}).data["results"]
        if r["id"] == person.pk
    )

    first_day = timezone.localtime(approved).date()
    assert detail["joined_on"] == row["joined_on"] == first_day.isoformat()
    assert detail["left_on"] == row["left_on"] == last_day.isoformat()
    assert detail["overview"]["joined_on"] == first_day.isoformat()
    assert detail["overview"]["left_on"] == last_day.isoformat()
    assert detail["overview"]["tenure_days"] == (last_day - first_day).days


def test_telegram_ids_never_leave_the_server(owner_api, company, world):
    ours, _theirs, _nobody = world
    api = owner_api(ours["owner"])

    detail = api.get(path(company, f"people/{ours['person'].pk}/")).data
    requests = api.get(path(company, "join-requests/")).data

    assert "telegram_id" not in detail
    assert all("telegram_id" not in row for row in requests)


def test_a_failed_edit_keeps_the_role_unchanged(owner_api, company, world):
    ours, theirs, _nobody = world
    person = ours["person"]
    manager_role = AccessRole.objects.get(company=company, name="Manager")

    response = owner_api(ours["owner"]).patch(
        path(company, f"people/{person.pk}/"),
        {"role_id": manager_role.pk, "home_branch_id": theirs["person"].home_branch_id},
        format="json",
    )

    assert response.status_code == 400
    person.refresh_from_db()
    assert person.role.name == "Employee"


def test_the_activity_line_shows_the_newcomer(company, member, world):
    from apps.console import registry

    ours, _theirs, _nobody = world
    request = ours["request"]
    services.approve_request(request, by=ours["owner"])

    [item] = [i for i in registry.run_stream(ours["owner"]) if i.kind == "members.joined"]

    assert item.actor == {"id": request.pk, "name": str(request)}
    assert item.url == f"people/{request.pk}"


def test_the_ai_sees_no_time_off_reasons(company, world):
    from apps.ai.tools.testing import call_tool
    from apps.timeoff.models import TimeOff

    ours, _theirs, _nobody = world
    today = timezone.localdate()
    TimeOff.objects.create(
        company=company,
        membership=ours["person"],
        first_day=today + timedelta(days=3),
        last_day=today + timedelta(days=4),
        reason="Hospital check-up",
    )

    result = call_tool("members_person_overview", ours["owner"], member_id=ours["person"].pk)

    [upcoming] = result["data"]["upcoming_time_off"]
    assert "reason" not in upcoming
    assert "Hospital" not in str(result)
