"""Fixtures of the recognition tests: a pharmacy with recognition and learning on, two branches
(Chilonzor, Yunusobod), workdays Monday to Saturday, Asia/Tashkent, and its people:

- owner: every permission (recognition.manage);
- head: the Manager role at Chilonzor only (members.view, learning.view; no branches.all);
- ali, madina: pharmacists at Chilonzor; nigora: a pharmacist at Yunusobod.

The reference day is Saturday 7 November 2026; `freeze` moves the clock, `at(day, hour)` makes
a company-local moment.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.members.models import AccessRole
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 11, 7)  # a Saturday


def at(day: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def freeze(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def shop(company, freeze):
    freeze(at(DAY, 10))
    company.features = ["recognition", "learning"]
    company.timezone = "Asia/Tashkent"
    company.workdays = [0, 1, 2, 3, 4, 5]
    company.save(update_fields=["features", "timezone", "workdays"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    return company


@pytest.fixture
def chilonzor(shop):
    return shop.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(shop):
    return shop.branches.get(name="Yunusobod")


def _at(person, branch):
    person.branches.set([branch])
    person.home_branch = branch
    person.save(update_fields=["home_branch"])
    return person


@pytest.fixture
def owner(shop, member):
    return member(shop, "Owner", first_name="Dilnoza", last_name="Karimova")


@pytest.fixture
def head(shop, member, chilonzor):
    person = member(shop, "Manager", first_name="Bekzod", last_name="Mirzayev")
    role = person.role
    role.permissions = [code for code in role.permissions if code != Perm.BRANCHES_ALL]
    role.save(update_fields=["permissions"])
    return _at(person, chilonzor)


@pytest.fixture
def ali(shop, member, chilonzor):
    return _at(member(shop, "Pharmacist", first_name="Alisher", last_name="Valiyev"), chilonzor)


@pytest.fixture
def madina(shop, member, chilonzor):
    return _at(member(shop, "Pharmacist", first_name="Madina", last_name="Saidova"), chilonzor)


@pytest.fixture
def nigora(shop, member, yunusobod):
    return _at(member(shop, "Pharmacist", first_name="Nigora", last_name="Azimova"), yunusobod)


@pytest.fixture
def staff_role(shop):
    return AccessRole.objects.get(company=shop, name="Pharmacist")
