from datetime import timedelta
from decimal import Decimal

import pytest

from apps.finance import queries, services
from apps.finance.models import MoneyAccount
from apps.finance.tests.factories import CounterpartyFactory

pytestmark = pytest.mark.django_db

D = Decimal


def record(company, by, account, kind, amount, day, **kwargs):
    if kind in ("income", "expense"):
        kwargs.setdefault("category", "sales" if kind == "income" else "rent")
    return services.record_transaction(
        company, by=by, kind=kind, amount=amount, occurred_on=day, account=account, **kwargs
    )


class TestBalance:
    def test_now_and_on_a_day(self, books, owner, cash, day):
        record(books, owner, cash, "opening", 1000, day)
        record(books, owner, cash, "income", 500, day + timedelta(days=2))
        spent = record(books, owner, cash, "expense", 300, day + timedelta(days=4))
        record(books, owner, cash, "expense", 50, day + timedelta(days=4), status="pending")

        assert queries.balance(cash) == D("1200.00")
        assert queries.balance(cash, on=day - timedelta(days=1)) == 0
        assert queries.balance(cash, on=day) == D("1000.00")
        assert queries.balance(cash, on=day + timedelta(days=3)) == D("1500.00")
        assert queries.balance(cash, on=day + timedelta(days=4)) == D("1200.00")

        services.void_transaction(spent, by=owner, reason="x")
        assert queries.balance(cash, on=day + timedelta(days=9)) == D("1500.00")
        assert queries.balance(cash) == D("1500.00") == queries.ledger_balance(cash)

    def test_reads_the_balance_fresh(self, books, owner, cash, day):
        stale = MoneyAccount.objects.get(pk=cash.pk)
        record(books, owner, cash, "income", 70, day)

        assert stale.balance == 0
        assert queries.balance(stale) == D("70.00")


class TestHasLedgerRows:
    def test_any_booking_counts(self, books, owner, cash, bank, day):
        assert not queries.has_ledger_rows(books)
        row = record(books, owner, cash, "income", 70, day)
        assert queries.has_ledger_rows(books)
        services.void_transaction(row, by=owner, reason="x")
        assert queries.has_ledger_rows(books)  # a void row was still booked

    def test_an_opening_debt_counts(self, books, owner, day, other_company):
        services.open_debt(
            books,
            by=owner,
            direction="receivable",
            kind="trade",
            amount=5,
            currency="UZS",
            issued_on=day,
            counterparty=CounterpartyFactory(company=books),
            is_opening=True,
        )
        assert queries.has_ledger_rows(books)
        assert not queries.has_ledger_rows(other_company)
