"""Ledger links protect rows one by one, yet a whole company's ledger can still be removed by
deleting each model's rows in turn, as `seed_demo --reset` does."""

import pytest
from django.db import transaction
from django.db.models import ProtectedError, RestrictedError

from apps.finance import services
from apps.finance.models import (
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    FinanceSettings,
    MoneyAccount,
    Transaction,
    Transfer,
)
from apps.finance.tests.factories import CategoryFactory, CompanyRateFactory, CounterpartyFactory

pytestmark = pytest.mark.django_db

LEDGER = [Category, CompanyRate, Counterparty, Debt, MoneyAccount, Transaction, Transfer]


@pytest.fixture
def ledger(books, owner, cash, dollars, usd, day):
    parent = CategoryFactory(company=books, name="Kitchen", kind="expense")
    CategoryFactory(company=books, name="Gas", kind="expense", parent=parent)
    CompanyRateFactory(company=books, date=day)
    services.record_transaction(
        books, by=owner, kind="opening", amount=1_000_000, occurred_on=day, account=cash
    )
    services.transfer(
        books,
        by=owner,
        from_account=cash,
        to_account=dollars,
        amount_out=128_000,
        amount_in=9,
        occurred_on=day,
    )
    debt = services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=5,
        currency="USD",
        issued_on=day,
        counterparty=CounterpartyFactory(company=books),
        category="sales",
    )
    payment = services.pay_debt(debt, by=owner, amount=60_000, paid_on=day, account=cash)
    Transaction.objects.create(
        company=books,
        kind="income",
        occurred_on=day,
        account=cash,
        amount=-payment.amount,
        base_amount=-payment.base_amount,
        category=Category.objects.get(company=books, system_code="sales"),
        reverses=Transaction.objects.get(kind="opening"),
    )
    return parent


def test_rows_are_protected_one_by_one(ledger, books):
    with pytest.raises(RestrictedError), transaction.atomic():
        ledger.delete()
    with pytest.raises(ProtectedError), transaction.atomic():
        MoneyAccount.objects.filter(company=books).delete()


def test_a_whole_ledger_can_be_removed_model_by_model(ledger, books):
    remaining = list(LEDGER)
    while remaining:
        blocked = []
        for model in remaining:
            try:
                with transaction.atomic():
                    model.objects.filter(company=books).delete()
            except ProtectedError:
                blocked.append(model)
        assert len(blocked) < len(remaining), blocked
        remaining = blocked

    assert not any(model.objects.filter(company=books).exists() for model in LEDGER)
    assert FinanceSettings.objects.filter(company=books).exists()  # goes with the company
