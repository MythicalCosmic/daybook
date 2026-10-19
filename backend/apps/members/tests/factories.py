import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import UserFactory
from apps.companies.tests.factories import CompanyFactory
from apps.members.models import AccessRole, Membership, Position


class PositionFactory(DjangoModelFactory):
    class Meta:
        model = Position

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Position {n}")


class AccessRoleFactory(DjangoModelFactory):
    class Meta:
        model = AccessRole

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Role {n}")
    permissions = factory.LazyFunction(list)


class MembershipFactory(DjangoModelFactory):
    class Meta:
        model = Membership

    company = factory.SubFactory(CompanyFactory)
    user = factory.SubFactory(UserFactory)
    status = Membership.Status.PENDING
