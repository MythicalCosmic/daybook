"""Positions on the owner API: create, rename, hide, delete, reorder; and the demo data."""

import pytest
from django.utils import timezone

from apps.ai.tools.testing import call_tool
from apps.audit.models import AuditLog
from apps.members import demo
from apps.members.models import Membership, Position
from apps.members.tests.factories import PositionFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/owner/companies/{cid}/positions/"


def test_crud_and_reorder(owner_api, company, member):
    owner = member.registered(company, "Owner")
    api = owner_api(owner)
    url = URL.format(cid=company.pk)

    cook = api.post(url, {"name": "Cook"}, format="json")
    waiter = api.post(url, {"name": "Waiter"}, format="json")
    assert cook.status_code == 201 and waiter.status_code == 201
    assert api.post(url, {"name": "cook"}, format="json").status_code == 400

    renamed = api.patch(url + f"{cook.data['id']}/", {"name": "Chef"}, format="json")
    assert renamed.data["name"] == "Chef"

    order = api.post(url + "reorder/", {"ids": [waiter.data["id"], cook.data["id"]]}, format="json")
    assert [row["name"] for row in order.data] == ["Waiter", "Chef"]
    assert AuditLog.objects.filter(action="members.positions_reordered").exists()


def test_a_position_in_use_is_hidden_not_deleted(owner_api, company, member):
    owner = member.registered(company, "Owner")
    position = PositionFactory(company=company, name="Cashier")
    member.registered(company, position=position)
    url = URL.format(cid=company.pk) + f"{position.pk}/"

    assert owner_api(owner).delete(url).status_code == 400
    hidden = owner_api(owner).patch(url, {"is_active": False}, format="json")
    assert hidden.data["is_active"] is False
    assert hidden.data["members_count"] == 1


def test_anyone_with_dashboard_access_lists_positions_but_only_managers_change_them(
    owner_api, company, member
):
    accountant = member.registered(company, "Accountant")
    url = URL.format(cid=company.pk)

    assert owner_api(accountant).get(url).status_code == 200
    assert owner_api(accountant).post(url, {"name": "Cook"}, format="json").status_code == 403


def test_demo_adds_people_who_left_requests_and_history(company, demo_people, settings):
    people = demo_people(company)
    now = timezone.now()

    demo.seed(company, people, now)

    statuses = set(Membership.objects.filter(company=company).values_list("status", flat=True))
    assert {"approved", "suspended", "left", "blocked", "pending"} <= statuses
    assert Position.objects.filter(company=company).count() >= 6
    # The core six stay the only approved people unless the extra staff is asked for.
    assert Membership.objects.filter(company=company, status="approved").count() == 6


def test_demo_with_extra_staff(company, demo_people, monkeypatch):
    monkeypatch.setenv("DEMO_EXTRA_STAFF", "1")
    people = demo_people(company)

    demo.seed(company, people, timezone.now())

    assert Membership.objects.filter(company=company, status="approved").count() == 18
    owner = people["owner"]
    result = call_tool("members_list_people", owner)
    assert len(result["rows"]) >= 18
    rates = {row["name"]: row["on_time_percent_30d"] for row in result["rows"]}
    assert rates["Gulnora Ismoilova"] == "100"


def test_ai_person_tool_respects_scope(company, member):
    from apps.companies.tests.factories import BranchFactory
    from apps.members.permissions import Perm
    from apps.members.tests.factories import AccessRoleFactory

    chilonzor = company.branches.first()
    yunusobod = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_VIEW])
    viewer = member.registered(company, role.name, home_branch=chilonzor)
    viewer.branches.set([chilonzor])
    far = member.registered(company, home_branch=yunusobod)
    far.branches.set([yunusobod])

    assert call_tool("members_person_overview", viewer, member_id=far.pk) == {"error": "not_found"}
    mine = call_tool("members_person_overview", viewer, member_id=viewer.pk)
    assert mine["data"]["name"] == str(viewer)
