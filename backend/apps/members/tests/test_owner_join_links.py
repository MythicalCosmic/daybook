"""Team links and deciding many join requests on the owner API, and what the mini app reads."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.companies.tests.factories import BranchFactory
from apps.members import join_links, services
from apps.members.models import AccessRole, JoinLink, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db


def url(company, suffix=""):
    return f"/api/v1/owner/companies/{company.pk}/join-links/{suffix}"


def test_making_a_link_and_reading_it_back(owner_api, company, member, settings):
    settings.EMPLOYEE_BOT_USERNAME = "team_bot"
    owner = member.registered(company, "Owner")
    branch = company.branches.first()
    position = PositionFactory(company=company, name="Pharmacist")
    ends = timezone.now() + timedelta(days=1)

    response = owner_api(owner).post(
        url(company),
        {
            "name": "Staff meeting",
            "branch_id": branch.pk,
            "position_id": position.pk,
            "max_uses": 20,
            "expires_at": ends.isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    body = response.data
    link = JoinLink.objects.get(pk=body["id"])
    assert body["link"] == f"https://t.me/team_bot?start=j_{link.code}"
    assert body["start_param"] == f"j_{link.code}"
    assert body["auto_approve"] is True
    assert body["branch"] == {"id": branch.pk, "name": branch.name}
    assert body["role"] is None
    assert body["default_role"]["name"] == "Employee"
    assert body["position"] == {"id": position.pk, "name": "Pharmacist"}
    assert (body["max_uses"], body["uses"], body["status"]) == (20, 0, "active")
    assert body["created_by"] == {"id": owner.pk, "name": owner.full_name or str(owner.user)}
    assert body["can_edit"] is True


def test_the_list_puts_working_links_first(owner_api, company, member):
    owner = member.registered(company, "Owner")
    stopped = join_links.create_link(company, by=owner, name="Old")
    join_links.update_link(stopped, by=owner, is_active=False)
    working = join_links.create_link(company, by=owner, name="New")
    full = join_links.create_link(company, by=owner, name="Full", max_uses=1)
    JoinLink.objects.filter(pk=full.pk).update(uses=1)

    response = owner_api(owner).get(url(company))

    assert response.status_code == 200
    assert [(row["name"], row["status"]) for row in response.data] == [
        ("New", "active"),
        ("Full", "full"),
        ("Old", "stopped"),
    ]
    assert working.pk == response.data[0]["id"]


def test_the_live_screen_lists_who_joined(owner_api, company, member):
    owner = member.registered(company, "Owner")
    link = join_links.create_link(company, by=owner, name="Staff meeting")
    user = UserFactory(phone="+998901112233")
    membership, _ = join_links.open_link(user, link.start_param)
    services.complete_onboarding(
        membership, first_name="Aziz", last_name="Karimov", position_id=None
    )
    waiting, _ = join_links.open_link(UserFactory(), link.start_param)

    response = owner_api(owner).get(url(company, f"{link.pk}/"))

    assert response.status_code == 200
    assert response.data["uses"] == 1
    people = response.data["people"]  # newest first: opening the link counts until they finish
    assert [person["id"] for person in people] == [waiting.pk, membership.pk]
    assert people[1]["name"] == "Aziz Karimov"
    assert people[1]["status"] == "approved"
    assert people[1]["onboarded"] is True
    assert people[0]["onboarded"] is False


def test_changing_stopping_and_deleting(owner_api, company, member):
    owner = member.registered(company, "Owner")
    link = join_links.create_link(company, by=owner, name="Staff meeting")
    api = owner_api(owner)

    response = api.patch(
        url(company, f"{link.pk}/"), {"name": "Morning", "max_uses": 5}, format="json"
    )
    assert response.status_code == 200, response.data
    assert (response.data["name"], response.data["max_uses"]) == ("Morning", 5)

    response = api.patch(url(company, f"{link.pk}/"), {"is_active": False}, format="json")
    assert response.data["status"] == "stopped"

    assert api.delete(url(company, f"{link.pk}/")).status_code == 204
    assert JoinLink.objects.get(pk=link.pk).deleted_at is not None
    assert api.get(url(company)).data == []
    assert api.get(url(company, f"{link.pk}/")).status_code == 404


def test_rules_come_back_as_messages(owner_api, company, member):
    owner = member.registered(company, "Owner")
    BranchFactory(company=company, name="Yunusobod")
    api = owner_api(owner)

    no_branch = api.post(url(company), {"name": "Meeting"}, format="json")
    assert no_branch.status_code == 400
    assert "branch" in no_branch.data["detail"]

    too_many = api.post(url(company), {"name": "Meeting", "max_uses": 900}, format="json")
    assert too_many.status_code == 400
    assert "max_uses" in too_many.data

    other_company_branch = BranchFactory()
    response = api.post(
        url(company), {"name": "Meeting", "branch_id": other_company_branch.pk}, format="json"
    )
    assert response.status_code == 404


def test_people_without_approval_rights_cant_see_links(owner_api, company, member):
    worker = member.registered(company, "Accountant")  # dashboard access, no members.approve

    assert owner_api(worker).get(url(company)).status_code == 403


def test_a_branch_head_sees_links_of_their_branches_only(owner_api, company, member):
    owner = member.registered(company, "Owner")
    mine = company.branches.first()
    other = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(
        company=company,
        permissions=[Perm.MEMBERS_APPROVE, Perm.FINANCE_CLAIM, Perm.DASHBOARD_ACCESS],
    )
    head = member.registered(company, role.name, home_branch=mine)
    head.branches.add(mine)
    theirs = join_links.create_link(company, by=owner, name="Chilonzor", branch=mine)
    hidden = join_links.create_link(company, by=owner, name="Yunusobod", branch=other)
    manager_role = AccessRole.objects.get(company=company, name="Manager")
    locked = join_links.create_link(
        company, by=owner, name="Managers", branch=mine, role=manager_role
    )

    response = owner_api(head).get(url(company))

    rows = {row["id"]: row for row in response.data}
    assert set(rows) == {theirs.pk, locked.pk}
    assert rows[theirs.pk]["can_edit"] is True
    assert rows[locked.pk]["can_edit"] is False  # its role is beyond theirs
    assert owner_api(head).get(url(company, f"{hidden.pk}/")).status_code == 404
    response = owner_api(head).patch(
        url(company, f"{locked.pk}/"), {"name": "Mine now"}, format="json"
    )
    assert response.status_code == 403


def test_join_requests_name_their_team_link(owner_api, company, member):
    owner = member.registered(company, "Owner")
    branch = company.branches.first()
    link = join_links.create_link(
        company, by=owner, name="Staff meeting", auto_approve=False, branch=branch
    )
    membership, _ = join_links.open_link(UserFactory(phone="+998901112233"), link.start_param)
    services.complete_onboarding(
        membership, first_name="Ali", last_name="Valiyev", position_id=None
    )

    response = owner_api(owner).get(f"/api/v1/owner/companies/{company.pk}/join-requests/")

    [row] = response.data
    assert row["join_link"] == {
        "id": link.pk,
        "name": "Staff meeting",
        "auto_approve": False,
        "branch": {"id": branch.pk, "name": branch.name},
        "role": None,
    }


def test_deciding_many_requests_on_the_api(owner_api, company, member):
    owner = member.registered(company, "Owner")
    cashier = AccessRole.objects.get(company=company, name="Cashier")
    first, second = (
        MembershipFactory(company=company, onboarded_at=timezone.now()) for _ in range(2)
    )

    response = owner_api(owner).post(
        f"/api/v1/owner/companies/{company.pk}/join-requests/bulk/",
        {"ids": [first.pk, second.pk, 999999], "action": "approve", "role_id": cashier.pk},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert (response.data["done"], response.data["failed"]) == (2, 1)
    assert [row["ok"] for row in response.data["results"]] == [True, True, False]
    assert Membership.objects.get(pk=first.pk).role == cashier

    third = MembershipFactory(company=company, onboarded_at=timezone.now())
    response = owner_api(owner).post(
        f"/api/v1/owner/companies/{company.pk}/join-requests/bulk/",
        {"ids": [third.pk], "action": "reject", "reason": "No place"},
        format="json",
    )
    assert response.data["done"] == 1
    assert Membership.objects.get(pk=third.pk).status == Membership.Status.REJECTED


def test_deciding_many_needs_ids(owner_api, company, member):
    owner = member.registered(company, "Owner")

    response = owner_api(owner).post(
        f"/api/v1/owner/companies/{company.pk}/join-requests/bulk/",
        {"ids": [], "action": "approve"},
        format="json",
    )

    assert response.status_code == 400
    assert "ids" in response.data


def test_the_app_knows_a_link_let_them_in(api_as, company, member):
    owner = member.registered(company, "Owner")
    link = join_links.create_link(company, by=owner, name="Staff meeting")
    membership, _ = join_links.open_link(UserFactory(phone="+998901112233"), link.start_param)

    response = api_as(membership).post(
        f"/api/v1/companies/{company.pk}/onboarding/",
        {"first_name": "Aziz", "last_name": "Karimov"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["status"] == "approved"
    assert response.data["joined_by_link"] is True
