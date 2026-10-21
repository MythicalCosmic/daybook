"""Fixtures of the attendance tests: a shop with two branches (Chilonzor and Yunusobod, with
coordinates), cashiers, a manager and a branch lead who sees only Chilonzor, and a clock that
tests can freeze. The reference day is Wednesday 21 October 2026, Asia/Tashkent."""

from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.members.models import AccessRole, Position
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 10, 21)  # a Wednesday
CHILONZOR = (Decimal("41.285680"), Decimal("69.203430"))
YUNUSOBOD = (Decimal("41.364250"), Decimal("69.287950"))


def local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def freeze(monkeypatch):
    """`freeze(moment)`: `timezone.now()` returns `moment` from then on."""

    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def shop(company):
    company.features = ["attendance"]
    company.save(update_fields=["features"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.latitude, first.longitude = CHILONZOR
    first.geofence_m = 150
    first.opens_at, first.closes_at = time(9, 0), time(21, 0)
    first.save()
    Branch.objects.create(
        company=company,
        name="Yunusobod",
        code="YNS",
        latitude=YUNUSOBOD[0],
        longitude=YUNUSOBOD[1],
        opens_at=time(10, 0),
        closes_at=time(22, 0),
        order=1,
    )
    return company


@pytest.fixture
def chilonzor(shop):
    return shop.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(shop):
    return shop.branches.get(name="Yunusobod")


@pytest.fixture
def staff(shop, member, chilonzor, yunusobod):
    """manager (every branch), lead (Chilonzor only, attendance.manage without
    branches.all), ali and vali (cashiers at Chilonzor), sara (cashier at Yunusobod),
    bob (stock at Chilonzor), accountant (attendance.view only)."""
    cashier = Position.objects.create(company=shop, name="Cashier")
    stock = Position.objects.create(company=shop, name="Stock")
    office = Position.objects.create(company=shop, name="Office")
    AccessRole.objects.create(
        company=shop,
        name="Branch lead",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE],
    )

    def make(role="Employee", branch=chilonzor, position=cashier, **kwargs):
        made = member.registered(shop, role, position=position, home_branch=branch, **kwargs)
        made.branches.add(branch)
        return made

    people = SimpleNamespace(
        manager=make("Manager", position=office, first_name="Mona"),
        lead=make("Branch lead", position=office, first_name="Lola"),
        ali=make(first_name="Ali"),
        vali=make(first_name="Vali"),
        sara=make(branch=yunusobod, first_name="Sara"),
        bob=make(position=stock, first_name="Bob"),
        accountant=make("Accountant", position=office, first_name="Aziza"),
        cashier=cashier,
        stock=stock,
    )
    people.manager.branches.add(yunusobod)
    return people
