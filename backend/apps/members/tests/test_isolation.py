"""A member of one company must never act on, or be wired into, another company."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.members import services
from apps.members.models import AccessRole, Membership, Position
from apps.members.permissions import Perm
from apps.members.tests.factories import MembershipFactory, PositionFactory

pytestmark = pytest.mark.django_db


def test_owner_cannot_approve_requests_in_another_company(company, other_company, member):
    owner = member(company, "Owner")
    request = MembershipFactory(company=other_company)

    with pytest.raises(PermissionDenied):
        services.approve(request, by=owner.user)


def test_owner_cannot_block_members_of_another_company(company, other_company, member):
    owner = member(company, "Owner")
    outsider = member(other_company)

    with pytest.raises(PermissionDenied):
        services.block(outsider, by=owner.user)


def test_permissions_do_not_leak_across_companies(company, other_company, member):
    owner = member(company, "Owner")

    assert services.can(owner.user, company, Perm.MEMBERS_APPROVE)
    assert not services.can(owner.user, other_company, Perm.MEMBERS_APPROVE)


def test_for_company_returns_only_that_companys_rows(company, other_company):
    PositionFactory(company=company, name="Cashier")
    PositionFactory(company=other_company, name="Driver")

    names = list(Position.objects.for_company(company).values_list("name", flat=True))

    assert names == ["Cashier"]


def test_role_from_another_company_is_rejected(company, other_company, member):
    membership = member(company)
    membership.role = AccessRole.objects.get(company=other_company, name="Owner")

    with pytest.raises(ValidationError) as exc_info:
        membership.full_clean()

    assert "role" in exc_info.value.message_dict


def test_position_from_another_company_is_rejected(company, other_company, member):
    membership = member(company)
    membership.position = PositionFactory(company=other_company)

    with pytest.raises(ValidationError) as exc_info:
        membership.full_clean()

    assert "position" in exc_info.value.message_dict


def test_same_person_can_belong_to_two_companies(company, other_company, member):
    first = member(company)
    second = member(other_company, user=first.user)

    assert Membership.objects.filter(user=first.user).count() == 2
    assert second.company == other_company
