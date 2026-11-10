"""The org chart (`lifecycle/org/`): one read with the departments, heads and headcounts, the
branches and their managers, every person with their manager, statuses and whether the viewer
may move them, open vacancies placed where their people work; branch scope; a move proposed
from the chart is a job change waiting for approval, never applied.

The clock stands at 10:00 on Wednesday 21 October 2026 (Asia/Tashkent).
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.hr.models import Vacancy
from apps.hr.tests.conftest import DAY
from apps.lifecycle.models import JobChange, Termination
from apps.members import departments
from apps.members import services as members
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db


def url(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/lifecycle/org/"


@pytest.fixture
def tree(shop, staff, chilonzor):
    """Rahbariyat (the owner) above Chilonzor (the accountant heads it: Ali, Vali, the lead)
    and Yunusobod (no head: Sara). The branches: Chilonzor run by the manager."""
    top = departments.create_department(shop, by=staff.owner, name="Rahbariyat", head=staff.owner)
    north = departments.create_department(
        shop, by=staff.owner, name="Chilonzor", parent=top, head=staff.accountant
    )
    south = departments.create_department(shop, by=staff.owner, name="Yunusobod", parent=top)
    departments.place(north, by=staff.owner, people=[staff.ali, staff.vali, staff.lead])
    departments.place(south, by=staff.owner, people=[staff.sara])
    chilonzor.manager = staff.manager
    chilonzor.save(update_fields=["manager"])
    return {"top": top, "north": north, "south": south}


def by_id(rows) -> dict:
    return {row["id"]: row for row in rows}


def test_the_tree_has_departments_heads_people_and_managers(shop, staff, tree, owner_api):
    response = owner_api(staff.owner).get(url(shop))

    assert response.status_code == 200
    data = response.json()
    assert [owner["name"] for owner in data["owners"]] == ["Dilnoza Karimova"]
    rows = by_id(data["departments"])
    top, north, south = (rows[tree[key].pk] for key in ("top", "north", "south"))
    assert (top["parent_id"], top["depth"], top["head"]["id"]) == (None, 1, staff.owner.pk)
    assert (north["parent_id"], north["head"]["name"]) == (tree["top"].pk, "Aziza Rasulova")
    assert north["head"]["position"] == "Office"
    assert (north["headcount"], north["total"]) == (4, 4)  # the head sits in it too
    assert (south["head"], south["headcount"]) == (None, 1)
    assert (top["headcount"], top["total"]) == (1, 6)
    people = by_id(data["people"])
    assert people[staff.ali.pk]["manager_id"] == staff.accountant.pk
    assert people[staff.ali.pk]["department_id"] == tree["north"].pk
    # Nobody heads Yunusobod: Sara's head is the one above it.
    assert people[staff.sara.pk]["manager_id"] == staff.owner.pk
    assert people[staff.owner.pk]["is_owner"] is True
    assert people[staff.manager.pk]["department_id"] is None
    branches = by_id(data["branches"])
    chilonzor = branches[staff.ali.home_branch_id]
    assert chilonzor["manager"]["id"] == staff.manager.pk
    assert chilonzor["headcount"] == 6
    assert branches[staff.sara.home_branch_id]["headcount"] == 1
    assert {row["name"] for row in data["positions"]} == {"Pharmacist", "Office"}
    assert data["can"] == {"move": True, "decide": True, "hiring": True, "structure": True}


def test_who_may_be_moved_and_why_not(shop, staff, tree, owner_api):
    owner = by_id(owner_api(staff.owner).get(url(shop)).json()["people"])
    assert owner[staff.ali.pk]["may_move"] is True
    assert (owner[staff.owner.pk]["may_move"], owner[staff.owner.pk]["why_not"]) == (False, "self")

    # The lead holds hr.manage at Chilonzor: their people, never an owner.
    lead = by_id(owner_api(staff.lead).get(url(shop)).json()["people"])
    assert lead[staff.ali.pk]["may_move"] is True
    assert lead[staff.owner.pk]["why_not"] == "owner"

    # The Manager role reads HR but doesn't manage it: nobody moves.
    manager = owner_api(staff.manager).get(url(shop)).json()
    assert manager["can"]["move"] is False
    assert {row["why_not"] for row in manager["people"]} == {"rights", "self"}


def test_a_branch_manager_sees_their_branches_part(shop, staff, tree, owner_api):
    data = owner_api(staff.lead).get(url(shop)).json()

    names = {row["name"] for row in data["people"]}
    assert "Sara Tosheva" not in names
    assert {"Ali Valiyev", "Vali Aliyev", "Dilnoza Karimova"} <= names
    assert [row["name"] for row in data["branches"]] == ["Chilonzor"]
    # Yunusobod (only Sara) is left out; the owner's department stays above Chilonzor.
    assert {row["name"] for row in data["departments"]} == {"Rahbariyat", "Chilonzor"}
    assert data["can"]["structure"] is False


def test_statuses_suspended_on_leave_leaving_and_a_change_waiting(
    shop, staff, tree, owner_api, chilonzor
):
    members.suspend(staff.vali, by=staff.owner, until=DAY + timedelta(days=3), reason="Tekshiruv")
    TimeOff.objects.create(
        company=shop,
        membership=staff.sara,
        first_day=DAY - timedelta(days=1),
        last_day=DAY + timedelta(days=4),
        status=TimeOff.Status.APPROVED,
    )
    Termination.objects.create(
        company=shop,
        membership=staff.ali,
        kind=Termination.Kind.RESIGNATION,
        status=Termination.Status.AGREED,
        wished_last_day=DAY + timedelta(days=10),
        last_day=DAY + timedelta(days=9),
        requested_by=staff.ali,
        requested_at=timezone.now(),
    )
    JobChange.objects.create(
        company=shop,
        membership=staff.lead,
        effective_on=date(2026, 11, 1),
        parts=["department"],
        department=tree["south"],
        reason="Yunusobodga",
        status=JobChange.Status.PROPOSED,
        proposed_by=staff.owner,
    )

    people = by_id(owner_api(staff.owner).get(url(shop)).json()["people"])

    vali = people[staff.vali.pk]
    assert (vali["status"], vali["suspended_until"]) == ("suspended", "2026-10-24")
    assert people[staff.sara.pk]["on_leave_until"] == "2026-10-25"
    assert people[staff.ali.pk]["leaving"]["day"] == "2026-10-30"
    assert people[staff.ali.pk]["leaving"]["status"] == "agreed"
    change = people[staff.lead.pk]["change"]
    assert (change["status"], change["effective_on"], change["parts"]) == (
        "proposed",
        "2026-11-01",
        ["department"],
    )
    assert people[staff.owner.pk]["leaving"] is None


def test_open_vacancies_are_places_where_their_people_work(
    shop, staff, tree, owner_api, chilonzor, yunusobod
):
    Vacancy.objects.create(
        company=shop,
        title="Farmatsevt — Chilonzor",
        position=staff.pharmacist,
        branch=chilonzor,
        status=Vacancy.Status.OPEN,
    )
    Vacancy.objects.create(
        company=shop,
        title="Farmatsevt — Yunusobod",
        position=staff.pharmacist,
        branch=yunusobod,
        status=Vacancy.Status.OPEN,
    )
    Vacancy.objects.create(company=shop, title="Kuryer", branch=chilonzor)  # a draft

    data = owner_api(staff.owner).get(url(shop)).json()

    places = {row["title"]: row for row in data["vacancies"]}
    assert set(places) == {"Farmatsevt — Chilonzor", "Farmatsevt — Yunusobod"}
    assert places["Farmatsevt — Chilonzor"]["department_id"] == tree["north"].pk
    assert places["Farmatsevt — Yunusobod"]["department_id"] == tree["south"].pk
    assert places["Farmatsevt — Chilonzor"]["branch_id"] == chilonzor.pk
    assert places["Farmatsevt — Chilonzor"]["applicants"] == 0

    # The lead sees the places of their branch only.
    lead = owner_api(staff.lead).get(url(shop)).json()
    assert [row["title"] for row in lead["vacancies"]] == ["Farmatsevt — Chilonzor"]


def test_without_departments_the_branches_still_make_the_tree(shop, staff, owner_api):
    data = owner_api(staff.owner).get(url(shop)).json()

    assert data["departments"] == []
    assert {row["name"]: row["headcount"] for row in data["branches"]} == {
        "Chilonzor": 6,
        "Yunusobod": 1,
    }
    assert all(row["manager_id"] is None for row in data["people"])


def test_a_move_from_the_chart_is_a_proposed_job_change_never_applied(shop, staff, tree, owner_api):
    """Dropping Ali on Yunusobod opens the job change dialog; what it sends waits for an
    approval (the lead may propose, not decide a department) and Ali stays where he is."""
    client = owner_api(staff.lead)
    chart = by_id(client.get(url(shop)).json()["people"])
    assert chart[staff.ali.pk]["may_move"] is True

    response = client.post(
        f"/api/v1/owner/companies/{shop.pk}/lifecycle/job-changes/",
        {
            "member_id": staff.ali.pk,
            "effective_on": "2026-11-01",
            "department_id": tree["south"].pk,
            "reason": "Yunusobodga o‘tkazish (tuzilma sxemasidan)",
            "approve": True,
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["status"] == "proposed"
    staff.ali.refresh_from_db()
    assert staff.ali.department_id == tree["north"].pk
    change = by_id(client.get(url(shop)).json()["people"])[staff.ali.pk]["change"]
    assert change["parts"] == ["department"]


def test_the_owner_moving_someone_approves_it_for_its_day(shop, staff, tree, owner_api):
    response = owner_api(staff.owner).post(
        f"/api/v1/owner/companies/{shop.pk}/lifecycle/job-changes/",
        {
            "member_id": staff.sara.pk,
            "effective_on": "2026-11-01",
            "department_id": tree["north"].pk,
            "reason": "Chilonzorga",
            "approve": True,
        },
        format="json",
    )

    assert response.json()["status"] == "approved"
    staff.sara.refresh_from_db()
    assert staff.sara.department_id == tree["south"].pk  # on the 1st, not now


def test_scope_permissions_and_the_module(shop, staff, tree, owner_api, outsider):
    assert owner_api(outsider).get(url(shop)).status_code == 404

    AccessRole.objects.create(company=shop, name="Kassa", permissions=[Perm.DASHBOARD_ACCESS])
    staff.vali.role = AccessRole.objects.get(company=shop, name="Kassa")
    staff.vali.save(update_fields=["role"])
    assert owner_api(staff.vali).get(url(shop)).status_code == 403

    shop.features = ["payroll"]
    shop.save(update_fields=["features"])
    assert owner_api(staff.owner).get(url(shop)).status_code == 403


def test_one_read_whatever_the_size(
    shop, staff, tree, owner_api, member, chilonzor, django_assert_max_num_queries
):
    client = owner_api(staff.owner)
    client.get(url(shop))  # warm the viewer's caches
    for index in range(40):
        person = member.registered(
            shop,
            "Employee",
            position=staff.pharmacist,
            home_branch=chilonzor,
            first_name=f"Xodim{index}",
            last_name="Testov",
            user__phone=f"+9989077{index:05d}",
        )
        person.branches.add(chilonzor)
        Membership.objects.filter(pk=person.pk).update(department=tree["north"])

    with django_assert_max_num_queries(25):
        response = client.get(url(shop))

    assert len(response.json()["people"]) == 47
