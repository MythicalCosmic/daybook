"""Fixtures of the contract tests: a pharmacy with Finance on, two branches (Chilonzor and
Yunusobod), and its people:

- owner: every permission;
- manager: finance.view and finance.manage at Chilonzor only (no branches.all);
- reader: finance.view in every branch, no finance.manage;
- ali: a pharmacist at Chilonzor (no finance permissions).

The reference day is Saturday 7 November 2026, Asia/Tashkent (morning report at 09:00);
`freeze` moves the clock.
"""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from apps.companies.models import Branch
from apps.contracts import services
from apps.finance import defaults as finance_defaults
from apps.finance.models import Counterparty, MoneyAccount
from apps.members.models import AccessRole
from apps.members.permissions import Perm

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 11, 7)


def local(day: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def freeze(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def shop(company, freeze):
    freeze(local(DAY, 10))
    company.features = ["finance"]
    company.timezone = "Asia/Tashkent"
    company.save(update_fields=["features", "timezone"])
    first = company.branches.order_by("order", "pk").first()
    first.name, first.code = "Chilonzor", "CHL"
    first.save()
    Branch.objects.create(company=company, name="Yunusobod", code="YNS", order=1)
    finance_defaults.ensure(company)
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
def manager(shop, member, chilonzor):
    role = AccessRole.objects.create(
        company=shop,
        name="Branch money",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.FINANCE_VIEW, Perm.FINANCE_MANAGE],
    )
    person = member(shop, "Employee", first_name="Bekzod")
    person.role = role
    person.save(update_fields=["role"])
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def reader(shop, member):
    """Sees money in every branch, changes nothing (finance.view without finance.manage)."""
    role = AccessRole.objects.create(
        company=shop,
        name="Money reader",
        permissions=[Perm.DASHBOARD_ACCESS, Perm.FINANCE_VIEW, Perm.BRANCHES_ALL],
    )
    person = member(shop, "Employee", first_name="Lola")
    person.role = role
    person.save(update_fields=["role"])
    return person


@pytest.fixture
def ali(shop, member, chilonzor):
    person = member(shop, "Pharmacist", first_name="Ali")
    person.branches.set([chilonzor])
    return person


@pytest.fixture
def landlord(shop, owner):
    from apps.finance import services as finance

    return finance.create_counterparty(
        shop, by=owner, name="Rustam Qodirov (ijara)", kind=Counterparty.Kind.OTHER
    )


@pytest.fixture
def bank(shop, owner):
    """The first som account, opened with 100 000 000 at the start of the year."""
    from apps.finance import services as finance

    account = (
        MoneyAccount.objects.filter(company=shop, currency="UZS", is_active=True)
        .order_by("pk")
        .first()
    )
    finance.record_transaction(
        shop,
        by=owner,
        kind="opening",
        amount=Decimal(100_000_000),
        occurred_on=date(2026, 1, 1),
        account=account,
    )
    account.refresh_from_db()
    return account


@pytest.fixture
def dollars(shop, owner):
    from apps.finance import services as finance

    return finance.create_account(
        shop, by=owner, name="Dollar kassa", kind=MoneyAccount.Kind.CASH, currency="USD"
    )


@pytest.fixture
def lease(shop, owner, chilonzor, landlord):
    """The Chilonzor lease: 9 000 000 a month on the 3rd, a year from 1 January 2026."""
    return services.create_contract(
        shop,
        by=owner,
        kind="lease",
        title="Chilonzor dorixonasi ijarasi",
        branch=chilonzor,
        counterparty=landlord,
        number="IJ-2026/14",
        signed_on=date(2025, 12, 20),
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 12, 31),
        amount=Decimal(9_000_000),
        period="monthly",
        payment_day=3,
    )


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))
