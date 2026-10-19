import pytest
from django.core.exceptions import PermissionDenied

from apps.accounts.tests.factories import UserFactory
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.models import AccessRole, Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory

pytestmark = pytest.mark.django_db


def test_manager_approves_request_and_new_member_gets_default_role(company, member):
    manager = member(company, "Manager")
    request = MembershipFactory(company=company)

    services.approve(request, by=manager.user)

    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED
    assert request.role == AccessRole.objects.get(company=company, is_default=True)
    assert request.decided_by == manager.user
    assert request.decided_at is not None


def test_employee_cannot_approve(company, member):
    employee = member(company)
    request = MembershipFactory(company=company)

    with pytest.raises(PermissionDenied):
        services.approve(request, by=employee.user)


def test_pending_owner_cannot_approve(company, member):
    pending_owner = member(company, "Owner", status=Membership.Status.PENDING)
    request = MembershipFactory(company=company)

    with pytest.raises(PermissionDenied):
        services.approve(request, by=pending_owner.user)


def test_platform_admin_from_settings_can_approve(company, settings):
    platform_admin = UserFactory()
    settings.PLATFORM_ADMIN_TG_IDS = [platform_admin.telegram_id]
    request = MembershipFactory(company=company)

    services.approve(request, by=platform_admin)

    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED


def test_superuser_can_approve(company):
    request = MembershipFactory(company=company)

    services.approve(request, by=UserFactory(is_superuser=True))

    request.refresh_from_db()
    assert request.status == Membership.Status.APPROVED


def test_request_cannot_be_decided_twice(company, member):
    manager = member(company, "Manager")
    request = MembershipFactory(company=company)
    services.approve(request, by=manager.user)

    with pytest.raises(DomainError):
        services.reject(request, by=manager.user)


def test_manager_rejects_request(company, member):
    manager = member(company, "Manager")
    request = MembershipFactory(company=company)

    services.reject(request, by=manager.user)

    request.refresh_from_db()
    assert request.status == Membership.Status.REJECTED
    assert request.role is None


def test_blocking_needs_manage_permission(company, member):
    manager = member(company, "Manager")
    employee = member(company)

    with pytest.raises(PermissionDenied):
        services.block(employee, by=manager.user)


def test_owner_blocks_member(company, member):
    owner = member(company, "Owner")
    employee = member(company)

    services.block(employee, by=owner.user)

    employee.refresh_from_db()
    assert employee.status == Membership.Status.BLOCKED


def test_non_owner_cannot_block_an_owner(company, member):
    hr_role = AccessRoleFactory(company=company, permissions=[Perm.MEMBERS_MANAGE])
    hr = MembershipFactory(company=company, role=hr_role, status=Membership.Status.APPROVED)
    owner = member(company, "Owner")

    with pytest.raises(PermissionDenied):
        services.block(owner, by=hr.user)


def test_nobody_can_block_themselves(company, member):
    owner = member(company, "Owner")

    with pytest.raises(DomainError):
        services.block(owner, by=owner.user)
