"""The nightly check: drift injected into the cached balances and debt totals is found,
corrected from the ledger, audited and reported to the owners."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.finance import maintenance, services, tasks
from apps.finance.models import Debt, MoneyAccount
from apps.finance.tests.factories import CounterpartyFactory
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def finance_on(books):
    """The nightly job only looks at companies with the finance module on (§10.1)."""
    books.features = ["finance"]
    books.save(update_fields=["features"])


def test_injected_drift_is_fixed(books, owner, cash, day):
    services.record_transaction(
        books,
        by=owner,
        kind="income",
        amount=Decimal("500"),
        occurred_on=day,
        account=cash,
        category="sales",
    )
    debt = services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=Decimal("300"),
        currency="UZS",
        issued_on=day,
        counterparty=CounterpartyFactory(company=books),
        is_opening=True,
    )
    services.pay_debt(debt, by=owner, amount=Decimal("100"), paid_on=day, account=cash)
    MoneyAccount.objects.filter(pk=cash.pk).update(balance=Decimal("999"))
    Debt.objects.filter(pk=debt.pk).update(paid=Decimal("300"), status=Debt.Status.PAID)

    assert maintenance.verify_company(books, fix=False)["accounts"]
    found = tasks.verify_balances()
    assert found == 1

    cash.refresh_from_db()
    debt.refresh_from_db()
    assert cash.balance == Decimal("600.00")
    assert (debt.paid, debt.status) == (Decimal("100.00"), Debt.Status.OPEN)
    log = AuditLog.objects.get(action="finance.balances_fixed")
    assert log.details["accounts"][0]["balance"] == ["999.00", "600.00"]
    assert Notification.objects.filter(kind="finance.balance_drift", recipient=owner).exists()
    assert maintenance.verify_company(books) == {"accounts": [], "debts": []}


def test_a_clean_ledger_changes_nothing(books, owner, cash, day):
    services.record_transaction(
        books,
        by=owner,
        kind="income",
        amount=Decimal("5"),
        occurred_on=day,
        account=cash,
        category="sales",
    )
    assert tasks.verify_balances() == 0
    assert not AuditLog.objects.filter(action="finance.balances_fixed").exists()


def test_a_company_with_finance_off_is_skipped(books, owner, cash, day):
    services.record_transaction(
        books,
        by=owner,
        kind="income",
        amount=Decimal("5"),
        occurred_on=day,
        account=cash,
        category="sales",
    )
    MoneyAccount.objects.filter(pk=cash.pk).update(balance=Decimal("1"))
    books.features = []
    books.save(update_fields=["features"])
    assert tasks.verify_balances() == 0
    cash.refresh_from_db()
    assert cash.balance == Decimal("1.00")


def test_the_check_reads_the_whole_ledger_in_a_few_queries(
    books, owner, cash, day, django_assert_max_num_queries
):
    for amount in range(1, 30):
        services.record_transaction(
            books,
            by=owner,
            kind="income",
            amount=Decimal(amount),
            occurred_on=day,
            account=cash,
            category="sales",
        )
    with django_assert_max_num_queries(5):
        assert maintenance.verify_company(books) == {"accounts": [], "debts": []}
