import pytest

from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm

pytestmark = pytest.mark.django_db


def role(company, name) -> AccessRole:
    return AccessRole.objects.get(company=company, name=name)


def test_owner_role_grants_every_permission(company):
    owner = role(company, "Owner")

    assert all(owner.grants(perm) for perm in Perm)


def test_employee_role_grants_nothing(company):
    employee = role(company, "Employee")

    assert not any(employee.grants(perm) for perm in Perm)


def test_manager_role_grants_only_its_permissions(company):
    manager = role(company, "Manager")

    assert manager.grants(Perm.MEMBERS_APPROVE)
    assert not manager.grants(Perm.ROLES_MANAGE)
    assert not manager.grants(Perm.MEMBERS_MANAGE)


@pytest.mark.parametrize(
    "status",
    [
        Membership.Status.PENDING,
        Membership.Status.REJECTED,
        Membership.Status.BLOCKED,
        Membership.Status.LEFT,
    ],
)
def test_only_approved_members_have_permissions(company, member, status):
    owner = member(company, "Owner", status=status)

    assert not owner.has_perm(Perm.MEMBERS_VIEW)


def test_member_without_role_has_no_permissions(company, member):
    membership = member(company)
    membership.role = None

    assert not membership.has_perm(Perm.MEMBERS_VIEW)
