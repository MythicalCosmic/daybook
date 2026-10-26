"""Departments on the owner API, the people directory and what the mini app reads."""

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.members import departments
from apps.members.models import Department, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory

pytestmark = pytest.mark.django_db


def url(company, suffix=""):
    return f"/api/v1/owner/companies/{company.pk}/departments/{suffix}"


def people_url(company, suffix=""):
    return f"/api/v1/owner/companies/{company.pk}/people/{suffix}"


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


def test_making_and_reading_the_tree(owner_api, company, member, owner):
    bekzod = member.registered(company, first_name="Bekzod")
    api = owner_api(owner)

    top = api.post(url(company), {"name": "Rahbariyat", "head_id": owner.pk}, format="json")
    assert top.status_code == 201, top.data
    sales = api.post(
        url(company),
        {"name": "Savdo", "parent_id": top.data["id"], "head_id": bekzod.pk},
        format="json",
    )
    api.post(
        url(company, f"{sales.data['id']}/members/"), {"member_ids": [bekzod.pk]}, format="json"
    )

    response = api.get(url(company))

    assert response.status_code == 200
    rows = response.data
    assert [row["name"] for row in rows] == ["Rahbariyat", "Savdo"]  # parents first
    assert rows[1]["parent_id"] == rows[0]["id"]
    assert rows[1]["head"]["id"] == bekzod.pk
    assert rows[1]["path"] == ["Rahbariyat", "Savdo"]
    assert (rows[0]["member_count"], rows[0]["total_count"]) == (0, 1)
    assert (rows[1]["member_count"], rows[1]["total_count"]) == (1, 1)
    assert rows[0]["can_edit"] is True


def test_renaming_moving_and_deleting(owner_api, company, owner):
    api = owner_api(owner)
    top = departments.create_department(company, by=owner, name="Rahbariyat")
    stock = departments.create_department(company, by=owner, name="Omber")

    response = api.patch(
        url(company, f"{stock.pk}/"), {"name": "Ombor", "parent_id": top.pk}, format="json"
    )
    assert response.status_code == 200, response.data
    assert (response.data["name"], response.data["parent_id"]) == ("Ombor", top.pk)

    cycle = api.patch(url(company, f"{top.pk}/"), {"parent_id": stock.pk}, format="json")
    assert cycle.status_code == 400
    assert "under itself" in cycle.data["detail"]

    assert api.delete(url(company, f"{top.pk}/")).status_code == 204
    stock.refresh_from_db()
    assert stock.parent is None


def test_a_manager_of_some_branches_reads_but_cant_change_the_tree(
    owner_api, company, member, owner
):
    role = AccessRoleFactory(
        company=company,
        permissions=[Perm.MEMBERS_VIEW, Perm.MEMBERS_MANAGE, Perm.DASHBOARD_ACCESS],
    )
    scoped = member.registered(company, role.name)
    scoped.branches.add(company.branches.first())
    departments.create_department(company, by=owner, name="Rahbariyat")
    api = owner_api(scoped)

    listed = api.get(url(company))
    assert listed.status_code == 200
    assert listed.data[0]["can_edit"] is False
    assert api.post(url(company), {"name": "Savdo"}, format="json").status_code == 403


def test_people_of_another_company_cant_be_placed(owner_api, company, member, owner, other_company):
    stranger = member.registered(other_company)
    top = departments.create_department(company, by=owner, name="Rahbariyat")

    response = owner_api(owner).post(
        url(company, f"{top.pk}/members/"), {"member_ids": [stranger.pk]}, format="json"
    )

    assert response.status_code == 400
    assert "member_ids" in response.data


def test_people_rows_name_their_department_and_head(owner_api, company, member, owner):
    bekzod = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    top = departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top, head=bekzod)
    departments.place(sales, by=owner, people=[bekzod, alisher])

    rows = {row["id"]: row for row in owner_api(owner).get(people_url(company)).data["results"]}

    assert rows[alisher.pk]["department"] == {"id": sales.pk, "name": "Savdo"}
    assert rows[alisher.pk]["manager"]["id"] == bekzod.pk
    assert rows[bekzod.pk]["manager"]["id"] == owner.pk
    assert rows[owner.pk]["department"] is None
    detail = owner_api(owner).get(people_url(company, f"{bekzod.pk}/")).data
    assert detail["heads"] == [{"id": sales.pk, "name": "Savdo"}]


def test_the_directory_filters_by_department_and_everything_below(
    owner_api, company, member, owner
):
    top = departments.create_department(company, by=owner, name="Rahbariyat")
    sales = departments.create_department(company, by=owner, name="Savdo", parent=top)
    stock = departments.create_department(company, by=owner, name="Ombor")
    seller, keeper = member.registered(company), member.registered(company)
    departments.place(sales, by=owner, people=[seller])
    departments.place(stock, by=owner, people=[keeper])

    found = owner_api(owner).get(people_url(company), {"department": top.pk}).data["results"]

    assert [row["id"] for row in found] == [seller.pk]


def test_moving_someone_through_their_page(owner_api, company, member, owner):
    worker = member.registered(company)
    stock = departments.create_department(company, by=owner, name="Ombor")
    api = owner_api(owner)

    response = api.patch(
        people_url(company, f"{worker.pk}/"), {"department_id": stock.pk}, format="json"
    )
    assert response.status_code == 200, response.data
    assert response.data["department"] == {"id": stock.pk, "name": "Ombor"}

    response = api.patch(
        people_url(company, f"{worker.pk}/"), {"department_id": None}, format="json"
    )
    assert response.data["department"] is None


def test_the_app_knows_my_department_head_and_team(api_as, company, member, owner):
    bekzod = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    sales = departments.create_department(company, by=owner, name="Savdo", head=bekzod)
    departments.place(sales, by=owner, people=[bekzod, alisher])
    departments.create_department(company, by=owner, name="Rahbariyat", head=owner)
    Department.objects.filter(pk=sales.pk).update(parent=Department.objects.get(name="Rahbariyat"))

    mine = api_as(alisher).get("/api/v1/me/").data["memberships"][0]
    head = api_as(bekzod).get("/api/v1/me/").data["memberships"][0]

    assert mine["department"] == {"id": sales.pk, "name": "Savdo"}
    assert mine["manager"] == {"id": bekzod.pk, "name": str(bekzod)}
    assert mine["team_size"] == 0
    assert head["team_size"] == 1
    assert head["manager"]["id"] == owner.pk


def test_a_head_picks_from_their_people_in_the_app(api_as, company, member, owner):
    bekzod = member.registered(company, first_name="Bekzod")
    alisher = member.registered(company, first_name="Alisher")
    outsider = member.registered(company, first_name="Otabek")
    sales = departments.create_department(company, by=owner, name="Savdo", head=bekzod)
    departments.place(sales, by=owner, people=[bekzod, alisher])

    response = api_as(bekzod).get(f"/api/v1/companies/{company.pk}/members/")

    assert response.status_code == 200
    ids = {row["id"] for row in response.data}
    assert alisher.pk in ids
    assert outsider.pk not in ids
    # Someone who heads nothing and holds neither right still sees no list.
    assert api_as(outsider).get(f"/api/v1/companies/{company.pk}/members/").status_code == 403


def test_a_branch_lead_who_heads_a_department_also_picks_its_people(api_as, company, member, owner):
    here = company.branches.first()
    there = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(company=company, permissions=[Perm.TASKS_ASSIGN])
    lead = member.registered(company, role.name)
    lead.branches.add(here)
    near = member.registered(company)
    near.branches.add(here)
    far = member.registered(company)
    far.branches.add(there)
    team = departments.create_department(company, by=owner, name="Kuryerlar", head=lead)
    departments.place(team, by=owner, people=[far])

    ids = {row["id"] for row in api_as(lead).get(f"/api/v1/companies/{company.pk}/members/").data}

    assert {near.pk, far.pk} <= ids
    assert Membership.objects.filter(pk__in=ids).count() == len(ids)
