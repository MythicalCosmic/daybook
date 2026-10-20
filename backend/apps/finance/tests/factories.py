"""factory_boy factories for the models of the finance ledger.

Ledger rows (transactions, transfers, debts) have no factories on purpose: make them through
`apps.finance.services`, which keeps balances and debt totals in step.
"""

from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.finance.models import Category, CompanyRate, Counterparty, ExchangeRate, MoneyAccount


class MoneyAccountFactory(DjangoModelFactory):
    class Meta:
        model = MoneyAccount

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Account {n}")
    kind = MoneyAccount.Kind.CASH
    currency = "UZS"


class CategoryFactory(DjangoModelFactory):
    class Meta:
        model = Category

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Category {n}")
    kind = Category.Kind.EXPENSE


class CounterpartyFactory(DjangoModelFactory):
    class Meta:
        model = Counterparty

    company = factory.SubFactory(CompanyFactory)
    name = factory.Sequence(lambda n: f"Counterparty {n}")
    kind = Counterparty.Kind.CUSTOMER


class ExchangeRateFactory(DjangoModelFactory):
    class Meta:
        model = ExchangeRate

    currency = "USD"
    date = factory.LazyFunction(lambda: date(2026, 10, 1))
    rate = Decimal("12800")
    source = "cbu"


class CompanyRateFactory(DjangoModelFactory):
    class Meta:
        model = CompanyRate

    company = factory.SubFactory(CompanyFactory)
    currency = "USD"
    date = factory.LazyFunction(lambda: date(2026, 10, 1))
    rate = Decimal("12900")
