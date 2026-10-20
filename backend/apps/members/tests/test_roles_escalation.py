"""The four anti-escalation rules (docs/PLAN-OWNER.md §5), on the owner API and the services.

1. Only owners assign or remove the Owner role, and only owners edit a role they hold.
2. A non-owner grants only permissions they hold, and assigns only roles within their own.
3. Approving a join request gives the default role or a role allowed by rule 2.
4. The last approved owner can't be demoted, blocked or offboarded.
"""

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory

pytestmark = pytest.mark.django_db

ROLES = "/api/v1/owner/companies/{cid}/roles/"
PEOPLE = "/api/v1/owner/companies/{cid}/people/"

HR_PERMS = [
    Perm.DASHBOARD_ACCESS,
    Perm.MEMBERS_VIEW,
    Perm.MEMBERS_MANAGE,
    Perm.MEMBERS_APPROVE,
    Perm.ROLES_MANAGE,
    Perm.BRANCHES_ALL,
    Perm.TASKS_ASSIGN,
    Perm.FINANCE_CLAIM,
]


@pytest.fixture
def hr(company, member):
    role = AccessRoleFactory(company=company, name="HR", permissions=[str(p) for p in HR_PERMS])
    return member.registered(company, role.name)


@pytest.fixture
def owner(company, member):
    return member.registered(company, "Owner")


def role(company, name):
    return AccessRole.objects.get(company=company, name=name)


# Rule 1 -----------------------------------------------------------------------------------


def test_only_owners_give_the_owner_role(owner_api, company, member, hr, owner):
    worker = member.registered(company)
    owner_role = role(company, "Owner")

    refused = owner_api(hr).patch(
        PEOPLE.format(cid=company.pk) + f"{worker.pk}/", {"role_id": owner_role.pk}, format="json"
    )
    assert refused.status_code == 403
    allowed = owner_api(owner).patch(
        PEOPLE.format(cid=company.pk) + f"{worker.pk}/", {"role_id": owner_role.pk}, format="json"
    )
    assert allowed.status_code == 200
    worker.refresh_from_db()
    assert worker.role.is_owner


def test_only_owners_take_the_owner_role_away(company, member, hr, owner):
    second_owner = member.registered(company, "Owner")

    with pytest.raises(PermissionDenied):
        services.change_role(second_owner, by=hr, role=role(company, "Employee"))


def test_only_owners_edit_a_role_they_hold_themselves(owner_api, company, hr, owner):
    url = ROLES.format(cid=company.pk) + f"{hr.role_id}/"

    refused = owner_api(hr).patch(url, {"name": "People team"}, format="json")
    assert refused.status_code == 403
    allowed = owner_api(owner).patch(url, {"name": "People team"}, format="json")
    assert allowed.status_code == 200


def test_nobody_edits_the_owner_role_but_owners(owner_api, company, hr):
    url = ROLES.format(cid=company.pk) + f"{role(company, 'Owner').pk}/"

    response = owner_api(hr).patch(url, {"name": "Boss"}, format="json")

    assert response.status_code == 403


# Rule 2 -----------------------------------------------------------------------------------


def test_a_non_owner_grants_only_permissions_they_hold(owner_api, company, hr):
    url = ROLES.format(cid=company.pk)

    refused = owner_api(hr).post(
        url, {"name": "Money", "permissions": [Perm.FINANCE_VIEW]}, format="json"
    )
    assert refused.status_code == 403
    allowed = owner_api(hr).post(
        url, {"name": "Helpers", "permissions": [Perm.TASKS_ASSIGN]}, format="json"
    )
    assert allowed.status_code == 201
    assert allowed.data["permissions"] == [Perm.TASKS_ASSIGN]
    assert allowed.data["can_edit"] and allowed.data["can_assign"]


def test_a_non_owner_cant_take_away_permissions_they_dont_hold(company, hr):
    accountant = role(company, "Accountant")

    with pytest.raises(PermissionDenied):
        services.save_role(
            company, by=hr, role=accountant, name=accountant.name, permissions=[Perm.MEMBERS_VIEW]
        )


def test_a_non_owner_assigns_only_roles_within_their_own_permissions(company, member, hr):
    worker = member.registered(company)

    with pytest.raises(PermissionDenied):
        services.change_role(worker, by=hr, role=role(company, "Manager"))
    services.change_role(worker, by=hr, role=role(company, "Employee"))


def test_the_roles_list_says_what_the_viewer_may_do(owner_api, company, hr):
    response = owner_api(hr).get(ROLES.format(cid=company.pk))

    rows = {row["name"]: row for row in response.data}
    assert rows["Owner"]["can_assign"] is False and rows["Owner"]["can_edit"] is False
    assert rows["Manager"]["can_assign"] is False
    assert rows["Employee"]["can_assign"] is True
    assert rows["HR"]["can_edit"] is False  # their own role


# Rule 3 -----------------------------------------------------------------------------------


def test_approving_gives_the_default_role_or_one_within_the_approvers(company, hr):
    request = MembershipFactory(company=company, status=Membership.Status.PENDING)

    with pytest.raises(PermissionDenied):
        services.approve_request(request, by=hr, role=role(company, "Accountant"))
    approved = services.approve_request(request, by=hr)
    assert approved.role.is_default


# Rule 4 -----------------------------------------------------------------------------------


def test_the_last_owner_cant_be_demoted(company, owner):
    with pytest.raises(DomainError):
        services.change_role(owner, by=owner, role=role(company, "Manager"))


def test_the_last_owner_cant_be_blocked_or_offboarded(company, member, owner, hr):
    with pytest.raises((DomainError, PermissionDenied)):
        services.block_member(owner, by=hr)
    with pytest.raises((DomainError, PermissionDenied)):
        services.complete_offboarding(owner, by=hr, terminated_on=None, reason="resignation")
    # With a second owner, one of them can go.
    second = member.registered(company, "Owner")
    services.change_role(owner, by=second, role=role(company, "Manager"))
    owner.refresh_from_db()
    assert not owner.role.is_owner


def test_deleting_roles(owner_api, company, owner, member):
    url = ROLES.format(cid=company.pk)
    created = owner_api(owner).post(url, {"name": "Temps", "permissions": []}, format="json")
    temps = AccessRole.objects.get(pk=created.data["id"])

    assert owner_api(owner).delete(url + f"{role(company, 'Owner').pk}/").status_code == 400
    assert owner_api(owner).delete(url + f"{role(company, 'Employee').pk}/").status_code == 400
    member.registered(company, "Temps")
    assert owner_api(owner).delete(url + f"{temps.pk}/").status_code == 400
    Membership.objects.filter(role=temps).update(role=role(company, "Employee"))
    assert owner_api(owner).delete(url + f"{temps.pk}/").status_code == 204


def test_making_another_role_the_default(owner_api, company, owner):
    cashier = role(company, "Cashier")

    response = owner_api(owner).patch(
        ROLES.format(cid=company.pk) + f"{cashier.pk}/", {"is_default": True}, format="json"
    )

    assert response.status_code == 200
    assert AccessRole.objects.get(company=company, is_default=True) == cashier


def test_a_non_owner_doesnt_move_someone_out_of_a_role_above_theirs(owner_api, company, member, hr):
    accountant = member.registered(company, "Accountant")  # finance permissions HR lacks
    url = PEOPLE.format(cid=company.pk) + f"{accountant.pk}/"

    assert owner_api(hr).get(url).data["can"]["change_role"] is False
    refused = owner_api(hr).patch(url, {"role_id": role(company, "Employee").pk}, format="json")
    assert refused.status_code == 403
    accountant.refresh_from_db()
    assert accountant.role.name == "Accountant"
    # Someone in a role HR could give is fine.
    worker = member.registered(company, "Cashier")
    AccessRole.objects.filter(pk=worker.role_id).update(permissions=[str(Perm.FINANCE_CLAIM)])
    worker.role.refresh_from_db()
    services.change_role(worker, by=hr, role=role(company, "Employee"))


def test_the_owner_role_is_never_the_default(owner_api, company, owner):
    owner_role = role(company, "Owner")

    response = owner_api(owner).patch(
        ROLES.format(cid=company.pk) + f"{owner_role.pk}/", {"is_default": True}, format="json"
    )

    assert response.status_code == 400
    owner_role.refresh_from_db()
    assert not owner_role.is_default
