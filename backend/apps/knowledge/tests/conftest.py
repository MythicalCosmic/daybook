import pytest

from apps.members.models import Position


@pytest.fixture
def owner(company, member):
    return member(company, "Owner")


@pytest.fixture
def manager(company, member):
    """Manages the shop, but not the knowledge base (no `knowledge.manage` by default)."""
    return member(company, "Manager")


@pytest.fixture
def cashier_position(company):
    return Position.objects.create(company=company, name="Cashier")


@pytest.fixture
def cook_position(company):
    return Position.objects.create(company=company, name="Courier")


@pytest.fixture
def cashier(company, member, cashier_position):
    return member(company, "Employee", position=cashier_position, first_name="Madina")


@pytest.fixture
def cook(company, member, cook_position):
    return member(company, "Employee", position=cook_position, first_name="Jasur")
