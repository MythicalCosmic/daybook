from datetime import date
from decimal import Decimal

import pytest

from apps.finance import defaults, sources
from apps.finance.models import MoneyAccount
from apps.finance.tests.factories import ExchangeRateFactory, MoneyAccountFactory

DAY = date(2026, 10, 1)
USD_RATE = Decimal("12800")


@pytest.fixture
def day():
    return DAY


@pytest.fixture
def books(company):
    """The company with its default categories and accounts, as `company_created` leaves it."""
    defaults.ensure(company)
    return company


@pytest.fixture
def owner(books, member):
    return member(books, "Owner", first_name="Olim")


@pytest.fixture
def accountant(books, member):
    return member(books, "Accountant", first_name="Aziza")


@pytest.fixture
def cash(books):
    return MoneyAccount.objects.get(company=books, kind=MoneyAccount.Kind.CASH)


@pytest.fixture
def bank(books):
    return MoneyAccountFactory(company=books, name="Bank", kind=MoneyAccount.Kind.BANK)


@pytest.fixture
def dollars(books):
    return MoneyAccountFactory(company=books, name="Dollar safe", kind="safe", currency="USD")


@pytest.fixture
def usd(db):
    """The Central Bank's dollar rate on DAY: 12 800 so'm."""
    return ExchangeRateFactory(date=DAY, rate=USD_RATE)


@pytest.fixture
def src():
    """A throwaway source type, `finance.test`, as another module would register its own."""
    sources.register("finance.test", label="Test", url_template="/c/{company_id}/test/{id}")
    yield lambda id, key="": sources.Source("finance.test", id, key)
    sources.unregister("finance.test")
