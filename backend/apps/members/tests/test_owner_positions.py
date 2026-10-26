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

    cook = api.post(url, {"name": "Farmatsevt"}, format="json")
    waiter = api.post(url, {"name": "Kuryer"}, format="json")
    assert cook.status_code == 201 and waiter.status_code == 201
    assert api.post(url, {"name": "farmatsevt"}, format="json").status_code == 400

    renamed = api.patch(url + f"{cook.data['id']}/", {"name": "Provizor"}, format="json")
    assert renamed.data["name"] == "Provizor"

    order = api.post(url + "reorder/", {"ids": [waiter.data["id"], cook.data["id"]]}, format="json")
    assert [row["name"] for row in order.data] == ["Kuryer", "Provizor"]
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
    assert owner_api(accountant).post(url, {"name": "Kuryer"}, format="json").status_code == 403


def test_demo_adds_people_who_left_requests_and_history(company, demo_people, settings):
    people = demo_people(company)
    now = timezone.now()

    demo.seed(company, people, now)

    statuses = set(Membership.objects.filter(company=company).values_list("status", flat=True))
    assert {"approved", "suspended", "left", "blocked", "pending"} <= statuses
    assert Position.objects.filter(company=company).count() >= 6
    # The core demo makes the working staff; this demo adds people with a status, and the three
    # who joined through this morning's team link.
    assert Membership.objects.filter(company=company, status="approved").count() == 6 + 3
    assert Membership.objects.filter(company=company, joined_by_link=True).count() == 3
    result = call_tool("members_list_people", people["owner"])
    assert len(result["rows"]) >= 6


def test_demo_statuses_follow_the_story(company, demo_people):
    """Bobur is suspended over the days the story says, Nodira left on her day, and both are in
    the History with the owner's reason."""
    from apps.core import demo_plan

    people = demo_people(company)
    now = timezone.now()
    demo.seed(company, people, now)
    story = demo_plan.Plan(company, people, now)

    bobur = Membership.objects.get(company=company, user__telegram_id=3013)
    first, last, reason = demo_plan.SUSPENSION
    assert bobur.status == "suspended" and bobur.suspended_until == story.day(last)
    suspended = AuditLog.objects.get(target_id=bobur.pk, action="member.suspended")
    assert suspended.details["reason"] == reason
    assert timezone.localtime(suspended.created_at, story.zone).date() == story.day(first)
    nodira = Membership.objects.get(company=company, user__telegram_id=3014)
    assert nodira.status == "left"
    left_on = story.day(-demo_plan.LEFT_DAYS_AGO)
    assert timezone.localtime(nodira.decided_at, story.zone).date() == left_on
    # Approvals are dated the day each person joined.
    approved = AuditLog.objects.filter(action="member.approved", target_id=people["nigora"].pk)
    assert timezone.localtime(approved.get().created_at, story.zone).date() == story.joined(
        "nigora"
    )


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
