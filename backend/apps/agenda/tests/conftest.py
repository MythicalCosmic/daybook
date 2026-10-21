import pytest

from apps.companies.models import Branch
from apps.members.models import AccessRole


@pytest.fixture
def owner(company, member):
    return member(company, "Owner", first_name="Dilnoza")


@pytest.fixture
def manager(company, member):
    """Runs the shop, but doesn't manage the calendar (no `agenda.manage` by default)."""
    return member(company, "Manager", first_name="Bekzod")


@pytest.fixture
def chilonzor(company):
    return company.branches.first()


@pytest.fixture
def yunusobod(company):
    return Branch.objects.create(company=company, name="Yunusobod")


@pytest.fixture
def planner(company, member, chilonzor):
    """Manages the calendar for one branch only."""
    role = AccessRole.objects.create(
        company=company, name="Planner", permissions=["dashboard.access", "agenda.manage"]
    )
    person = member(company, role.name, first_name="Planner", home_branch=chilonzor)
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def alisher(company, member, chilonzor):
    person = member(company, first_name="Alisher", home_branch=chilonzor)
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def nigora(company, member, yunusobod):
    person = member(company, first_name="Nigora", home_branch=yunusobod)
    person.branches.set([yunusobod])
    return person
