import pytest

from apps.companies.tests.factories import CompanyFactory
from apps.members.models import AccessRole, Membership
from apps.members.tests.factories import MembershipFactory


@pytest.fixture
def company(db):
    return CompanyFactory()


@pytest.fixture
def other_company(db):
    return CompanyFactory()


@pytest.fixture
def member(db):
    """Make an approved member holding one of the company's default roles."""

    def make(company, role_name="Employee", **kwargs) -> Membership:
        kwargs.setdefault("status", Membership.Status.APPROVED)
        role = AccessRole.objects.get(company=company, name=role_name)
        return MembershipFactory(company=company, role=role, **kwargs)

    return make
