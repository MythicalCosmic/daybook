"""Fixtures of the asset tests: a pharmacy with Finance and Assets on, two branches (Chilonzor
and Yunusobod), and its people:

- owner: every permission;
- keeper: assets.manage at Chilonzor only (no branches.all);
- accountant: the Accountant role (finance.view, no assets.manage);
- ali: a pharmacist at Chilonzor.

The reference day is Saturday 7 November 2026, Asia/Tashkent; `freeze` moves the clock.
"""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.assets import defaults
from apps.companies.models import Branch
from apps.finance import defaults as finance_defaults
from apps.finance.models import Category, MoneyAccount
from apps.members.models import AccessRole
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 11, 7)


def local(day: date, hour: int = 12) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=TZ)


@pytest.fixture
def freeze(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def shop(company, freeze):
    freeze(local(DAY, 10))
    company.features = ["finance", "assets"]
    company.save(update_fields=["features"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    finance_defaults.ensure(company)
    defaults.ensure(company)
    return company


@pytest.fixture
def chilonzor(shop):
    return shop.branches.get(name="Chilonzor")


@pytest.fixture
def yunusobod(shop):
    return shop.branches.get(name="Yunusobod")


@pytest.fixture
def owner(shop, member):
    return member(shop, "Owner")


@pytest.fixture
def keeper(shop, member, chilonzor):
    role = AccessRole.objects.create(
        company=shop,
        name="Keeper",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.ASSETS_MANAGE],
    )
    person = member(shop, "Employee")
    person.role = role
    person.save(update_fields=["role"])
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def accountant(shop, member):
    return member(shop, "Accountant")


@pytest.fixture
def ali(shop, member, chilonzor):
    person = member(shop, "Pharmacist", first_name="Ali")
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def cash(shop, owner):
    """The cash desk, opened with 50 000 000 at the start of the year."""
    from apps.finance import services as finance

    account = MoneyAccount.objects.filter(company=shop, kind=MoneyAccount.Kind.CASH).first()
    finance.record_transaction(
        shop,
        by=owner,
        kind="opening",
        amount=Decimal(50_000_000),
        occurred_on=date(2026, 1, 1),
        account=account,
    )
    account.refresh_from_db()
    return account


@pytest.fixture
def equipment(shop):
    """An expense category for equipment purchases (capex)."""
    return Category.objects.create(
        company=shop, name="Uskunalar", kind=Category.Kind.EXPENSE, is_capex=True
    )


@pytest.fixture
def category(shop):
    from apps.assets.models import AssetCategory

    return AssetCategory.objects.get(company=shop, system_code="fridges")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))
