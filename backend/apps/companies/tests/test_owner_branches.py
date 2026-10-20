"""O branches/: address, hours, geofence, manager, cash limit; closed instead of deleted."""

import pytest

from apps.audit.models import AuditLog
from apps.companies.audit_actions import CompanyAction
from apps.companies.models import Branch
from apps.companies.tests.factories import BranchFactory

pytestmark = pytest.mark.django_db

CHILONZOR = {
    "name": "Chilonzor",
    "code": "chl",
    "address": "Bunyodkor 12, Chilonzor, Tashkent",
    "phone": "+998712000101",
    "latitude": "41.285480",
    "longitude": "69.203560",
    "geofence_m": 120,
    "opens_at": "09:00",
    "closes_at": "21:00",
    "open_weekdays": [0, 1, 2, 3, 4, 5],
    "cash_limit": "15000000.00",
}


def url(company, path=""):
    return f"/api/v1/owner/companies/{company.pk}/branches/{path}"


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


def test_owner_adds_a_branch_with_its_geofence(company, owner, owner_api, member):
    manager = member(company, "Manager")

    response = owner_api(owner).post(
        url(company), CHILONZOR | {"manager_id": manager.pk}, format="json"
    )

    assert response.status_code == 201, response.content
    data = response.json()
    assert data["code"] == "CHL"
    assert (data["latitude"], data["longitude"], data["geofence_m"]) == (
        "41.285480",
        "69.203560",
        120,
    )
    assert (data["opens_at"], data["closes_at"]) == ("09:00", "21:00")
    assert data["cash_limit"] == "15000000.00"  # money as a string
    assert data["manager"] == {"id": manager.pk, "name": str(manager)}
    assert data["is_active"] is True and data["people"] == 0
    branch = Branch.objects.get(pk=data["id"])
    assert branch.order > company.branches.exclude(pk=branch.pk).first().order
    assert AuditLog.objects.filter(
        action=CompanyAction.BRANCH_CREATED, target_id=branch.pk
    ).exists()


def test_the_list_counts_people_and_shows_closed_branches_last(company, owner, owner_api, member):
    first = company.branches.get()
    closed = BranchFactory(company=company, name="Old kiosk", is_active=False)
    worker = member(company, "Employee")
    worker.branches.add(first)

    rows = owner_api(owner).get(url(company)).json()

    assert [row["id"] for row in rows] == [first.pk, closed.pk]
    assert rows[0]["people"] == 1  # the owner fixture has no branches; the worker does


def test_editing_a_branch_is_audited_with_its_changes(company, owner, owner_api):
    branch = company.branches.get()

    response = owner_api(owner).patch(
        url(company, f"{branch.pk}/"), {"geofence_m": 300, "address": "Navoiy 1"}, format="json"
    )

    assert response.status_code == 200
    log = AuditLog.objects.get(action=CompanyAction.BRANCH_CHANGED)
    assert log.details["changes"]["geofence_m"] == [150, 300]


@pytest.mark.parametrize(
    "patch",
    [
        {"name": ""},
        {"code": "TOO-LONG-CODE"},
        {"latitude": "41.3"},  # without a longitude
        {"latitude": "123.0", "longitude": "69.2"},
        {"geofence_m": 5},
        {"geofence_m": 9000},
        {"opens_at": "09:00"},  # without a closing time
        {"open_weekdays": [8]},
        {"cash_limit": "-5.00"},
    ],
)
def test_bad_branch_data_is_refused(company, owner, owner_api, patch):
    branch = company.branches.get()

    response = owner_api(owner).patch(url(company, f"{branch.pk}/"), patch, format="json")

    assert response.status_code == 400, patch


def test_names_and_codes_are_unique(company, owner, owner_api):
    BranchFactory(company=company, name="Yunusobod", code="YNS")

    assert (
        owner_api(owner).post(url(company), {"name": "yunusobod"}, format="json").status_code == 400
    )
    assert (
        owner_api(owner)
        .post(url(company), {"name": "Sergeli", "code": "yns"}, format="json")
        .status_code
        == 400
    )


def test_the_manager_must_work_in_the_company(company, other_company, owner, owner_api, member):
    stranger = member(other_company, "Manager")
    branch = company.branches.get()

    response = owner_api(owner).patch(
        url(company, f"{branch.pk}/"), {"manager_id": stranger.pk}, format="json"
    )

    assert response.status_code == 400


def test_closing_and_reopening(company, owner, owner_api):
    first = company.branches.get()
    second = BranchFactory(company=company, name="Yunusobod")

    # The last open branch can't close.
    second_closed = owner_api(owner).post(url(company, f"{second.pk}/deactivate/"))
    assert second_closed.status_code == 200 and second_closed.json()["is_active"] is False
    assert owner_api(owner).post(url(company, f"{first.pk}/deactivate/")).status_code == 400

    reopened = owner_api(owner).post(url(company, f"{second.pk}/activate/"))
    assert reopened.json()["is_active"] is True
    assert Branch.objects.filter(company=company).count() == 2  # nothing deleted
    assert owner_api(owner).delete(url(company, f"{second.pk}/")).status_code == 405


@pytest.mark.django_db(transaction=True)
def test_closing_the_last_two_branches_at_once_keeps_one_open(company, owner):
    """Two people close the two open branches at the same moment: one wins, one is told the
    company needs an open branch (the company row serialises them)."""
    import threading

    from django.db import connection

    from apps.companies import services
    from apps.core.exceptions import DomainError

    branches = [company.branches.get(), BranchFactory(company=company, name="Yunusobod")]
    start = threading.Barrier(2)
    outcomes = []

    def close(branch):
        try:
            start.wait()
            services.deactivate_branch(branch, by=owner)
            outcomes.append("closed")
        except DomainError:
            outcomes.append("refused")
        finally:
            connection.close()

    threads = [threading.Thread(target=close, args=(branch,)) for branch in branches]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(outcomes) == ["closed", "refused"]
    assert Branch.objects.filter(company=company, is_active=True).count() == 1


def test_a_rename_that_loses_a_race_is_a_clear_error(company, owner, monkeypatch):
    """The database's unique name is the last guard; it answers like the check before it."""
    from django.db import IntegrityError

    from apps.companies import services
    from apps.core.exceptions import DomainError

    branch = company.branches.get()

    def collide(*args, **kwargs):
        raise IntegrityError("unique_branch_name_per_company")

    monkeypatch.setattr(Branch, "save", collide)
    with pytest.raises(DomainError, match="already called"):
        services.update_branch(branch, by=owner, name="Sergeli")


def test_reordering(company, owner, owner_api):
    first = company.branches.get()
    second = BranchFactory(company=company, name="Yunusobod", order=5)

    response = owner_api(owner).post(
        url(company, "reorder/"), {"ids": [second.pk, first.pk]}, format="json"
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [second.pk, first.pk]
    assert (
        owner_api(owner)
        .post(url(company, "reorder/"), {"ids": [second.pk]}, format="json")
        .status_code
        == 400
    )


def test_managers_read_branches_but_cannot_change_them(company, member, owner_api):
    manager = member(company, "Manager")
    branch = company.branches.get()

    assert owner_api(manager).get(url(company)).status_code == 200
    assert owner_api(manager).post(url(company), {"name": "New"}, format="json").status_code == 403
    assert (
        owner_api(manager)
        .patch(url(company, f"{branch.pk}/"), {"name": "X"}, format="json")
        .status_code
        == 403
    )
    assert owner_api(manager).post(url(company, f"{branch.pk}/deactivate/")).status_code == 403


def test_branch_scope_limits_what_a_scoped_member_sees(company, member, owner_api):
    first = company.branches.get()
    second = BranchFactory(company=company, name="Yunusobod")
    accountant_role = company.accessroles.get(name="Accountant")
    accountant_role.permissions = [p for p in accountant_role.permissions if p != "branches.all"]
    accountant_role.save()
    scoped = member(company, "Accountant")
    scoped.branches.add(second)

    rows = owner_api(scoped).get(url(company)).json()

    assert [row["id"] for row in rows] == [second.pk]
    assert owner_api(scoped).get(url(company, f"{first.pk}/")).status_code == 404


def test_the_palette_finds_branches_in_the_callers_scope(company, other_company, member):
    from apps.console import registry

    first = company.branches.get()
    first.name, first.address = "Chilonzor", "Bunyodkor 12"
    first.save()
    second = BranchFactory(company=company, name="Chilonzor-2", code="CH2")
    BranchFactory(company=other_company, name="Chilonzor bozori")
    role = company.accessroles.get(name="Accountant")
    role.permissions = [p for p in role.permissions if p != "branches.all"]
    role.save()
    scoped = member(company, "Accountant")
    scoped.branches.add(second)
    manager = member(company, "Manager")

    everything = registry.run_search(manager, "chilon", types=["companies.branches"])
    mine = registry.run_search(scoped, "chilon", types=["companies.branches"])

    assert [(hit.id, hit.subtitle) for hit in everything] == [
        (first.pk, "Bunyodkor 12"),
        (second.pk, "CH2"),
    ]
    assert everything[0].url == f"settings/branches?branch={first.pk}"
    assert [hit.id for hit in mine] == [second.pk]


def test_another_companys_branch_is_not_found(company, other_company, owner, owner_api):
    theirs = other_company.branches.get()

    assert owner_api(owner).get(url(company, f"{theirs.pk}/")).status_code == 404
    assert (
        owner_api(owner)
        .patch(url(company, f"{theirs.pk}/"), {"name": "x"}, format="json")
        .status_code
        == 404
    )
    assert owner_api(owner).get(url(other_company)).status_code == 404


def test_manager_options_list_approved_members(company, owner, owner_api, member):
    worker = member(company, "Employee", first_name="Madina", last_name="Saidova")
    member(company, "Employee", status="pending")

    response = owner_api(owner).get(url(company, "managers/"))

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert set(rows) == {owner.pk, worker.pk}
    assert rows[worker.pk]["name"] == "Madina Saidova"
    assert owner_api(member(company, "Manager")).get(url(company, "managers/")).status_code == 403
