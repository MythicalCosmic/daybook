"""`/owner/me/` (companies where the person may open the dashboard) and `/owner/permissions/`."""

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.members.models import Membership
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db

ME = "/api/v1/owner/me/"


def test_me_lists_only_companies_with_dashboard_access(company, other_company, member, owner_api):
    owner = member(company, "Owner")
    member(other_company, "Employee", user=owner.user)  # no dashboard there
    third = BranchFactory().company
    member(third, "Owner", user=owner.user, status=Membership.Status.PENDING)

    response = owner_api(owner).get(ME)

    assert response.status_code == 200
    assert [c["id"] for c in response.data["companies"]] == [company.pk]
    assert response.data["user"] == {
        "id": owner.user_id,
        "telegram_id": owner.user.telegram_id,
        "first_name": owner.user.first_name,
        "last_name": owner.user.last_name,
        "full_name": str(owner.user),
        "username": owner.user.telegram_username or "",
        "photo_url": None,
    }
    assert response.data["language"] == "en"
    assert set(response.data) == {"user", "language", "bot_company", "companies"}  # no admin flag


def test_a_company_entry_has_everything_the_shell_needs(company, member, owner_api):
    company.features = ["sales", "finance"]
    company.save()
    branch = BranchFactory(company=company, name="Chilonzor", code="CHL")
    owner = member(company, "Owner", home_branch=branch)
    owner.branches.add(branch)

    entry = owner_api(owner).get(ME).data["companies"][0]
    branches = entry.pop("branches")

    assert entry == {
        "id": company.pk,
        "name": company.name,
        "logo": None,
        "timezone": "Asia/Tashkent",
        "base_currency": "UZS",
        "features": ["sales", "finance"],
        "role": {"id": owner.role_id, "name": "Owner"},
        "is_owner": True,
        "permissions": [perm.value for perm in Perm],
        "branch_scope": None,
        "home_branch": {"id": branch.pk, "name": "Chilonzor"},
        "pending": 0,
        "setup_completed": False,
        "membership_id": owner.pk,
    }
    # Every active branch of the company (the owner sees them all).
    assert {"id": branch.pk, "name": "Chilonzor", "code": "CHL"} in branches
    assert len(branches) == company.branches.filter(is_active=True).count()


def test_a_scoped_member_sees_only_their_branches(company, member, owner_api):
    mine, other = BranchFactory(company=company), BranchFactory(company=company)
    inactive = BranchFactory(company=company, is_active=False)
    accountant = member(company, "Accountant")
    accountant.role.permissions.remove(Perm.BRANCHES_ALL)
    accountant.role.save()
    accountant.branches.add(mine, inactive)

    entry = owner_api(accountant).get(ME).data["companies"][0]

    assert entry["branch_scope"] == sorted([mine.pk, inactive.pk])
    assert [b["id"] for b in entry["branches"]] == [mine.pk]  # only active ones are listed
    assert other.pk not in entry["branch_scope"]
    assert Perm.PAYROLL_FINALIZE.value not in entry["permissions"]
    assert entry["is_owner"] is False


def test_me_changes_the_language(company, member, owner_api):
    owner = member(company, "Owner")

    response = owner_api(owner).patch(ME, {"language": "uz"}, format="json")

    assert response.status_code == 200
    assert response.data["language"] == "uz"
    owner.user.refresh_from_db()
    assert owner.user.language == "uz"


def test_me_refuses_an_unknown_language(company, member, owner_api):
    owner = member(company, "Owner")

    assert owner_api(owner).patch(ME, {"language": "de"}, format="json").status_code == 400


def test_someone_without_any_dashboard_gets_an_empty_list(company, member, owner_api):
    employee = member(company)

    assert owner_api(employee).get(ME).data["companies"] == []


def test_permissions_lists_every_code_with_its_group(company, member, owner_api):
    owner = member(company, "Owner")

    response = owner_api(owner).get("/api/v1/owner/permissions/")

    assert response.status_code == 200
    assert len(response.data) == len(Perm)
    assert {
        "code": "payroll.finalize",
        "label": "Finalize and publish payroll runs",
        "group": "payroll",
    } in response.data
