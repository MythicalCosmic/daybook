"""Fixtures of the payroll tests: a pharmacy (the §3.17 golden setup: Monday to Saturday workdays,
Asia/Tashkent, the holiday of Thursday 1 October 2026) with two branches, its people, a cash
desk with money in it, and a clock tests can freeze. The reference day is Wednesday
21 October 2026."""

from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.finance import services as finance
from apps.members.models import AccessRole, Position
from apps.members.permissions import Perm
from apps.timeoff.models import Holiday

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 10, 21)  # a Wednesday
OCTOBER = date(2026, 10, 1)


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
def today(freeze):
    """The clock stands at noon of Wednesday 21 October 2026."""
    return freeze(local(DAY, 12))


@pytest.fixture
def shop(company):
    company.features = ["payroll", "finance", "attendance", "hr"]
    company.workdays = [0, 1, 2, 3, 4, 5]
    company.save(update_fields=["features", "workdays"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    Holiday.objects.create(company=company, date=date(2026, 10, 1), name="Teachers' Day")
    return company


@pytest.fixture
def chilonzor(shop):
    return shop.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(shop):
    return shop.branches.get(name="Yunusobod")


@pytest.fixture
def staff(shop, member, chilonzor, yunusobod):
    """owner, manager (payroll.propose, every branch), accountant (view, manage, pay), lead
    (propose at Chilonzor only, no amounts), ali and vali (pharmacists at Chilonzor) and sara
    (pharmacist at Yunusobod)."""
    pharmacist = Position.objects.create(company=shop, name="Pharmacist")
    office = Position.objects.create(company=shop, name="Office")
    AccessRole.objects.create(
        company=shop,
        name="Branch lead",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.PAYROLL_PROPOSE],
    )

    def make(role="Employee", branch=chilonzor, position=pharmacist, **kwargs):
        made = member.registered(shop, role, position=position, home_branch=branch, **kwargs)
        made.branches.add(branch)
        return made

    people = SimpleNamespace(
        owner=make("Owner", position=office, first_name="Dilnoza"),
        manager=make("Manager", position=office, first_name="Bekzod"),
        accountant=make("Accountant", position=office, first_name="Aziza"),
        lead=make("Branch lead", position=office, first_name="Lola"),
        ali=make(first_name="Ali"),
        vali=make(first_name="Vali"),
        sara=make(branch=yunusobod, first_name="Sara"),
        pharmacist=pharmacist,
    )
    people.owner.branches.add(yunusobod)
    people.manager.branches.add(yunusobod)
    people.accountant.branches.add(yunusobod)
    return people


@pytest.fixture
def cash(shop, staff):
    """A cash desk at Chilonzor with 50 000 000 so‘m in it."""
    account = finance.create_account(
        shop, by=staff.owner, kind="cash", name="Payroll cash", branch=None
    )
    finance.record_transaction(
        shop,
        by=staff.owner,
        kind="opening",
        amount=Decimal("50000000"),
        occurred_on=date(2026, 9, 1),
        account=account,
    )
    account.refresh_from_db()
    return account
