"""`rebase_default_accounts`: a company whose base currency changes before anything is booked
takes its default cash desk and card terminal along (companies.services.update_settings)."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.finance import services
from apps.finance.models import MoneyAccount
from apps.finance.tests.factories import MoneyAccountFactory

pytestmark = pytest.mark.django_db


def currencies(company) -> dict[str, str]:
    return dict(MoneyAccount.objects.filter(company=company).values_list("name", "currency"))


def test_an_empty_ledger_moves_only_the_default_accounts(books, owner, member):
    branch = books.branches.order_by("pk").first()
    safe = services.account_for_branch(branch, kind="safe", currency="UZS")
    MoneyAccountFactory(company=books, name="Bank", kind="bank")
    MoneyAccountFactory(company=books, name="Petty cash", kind="cash", branch=branch)
    MoneyAccountFactory(company=books, name="Dollar desk", kind="cash", currency="USD")
    holder = member(books, first_name="Aziz")
    services.account_for_holder(books, holder, currency="UZS")

    moved = services.rebase_default_accounts(books, currency="USD", by=owner)

    assert sorted(a.name for a in moved) == ["Card terminal", "Cash desk"]
    after = currencies(books)
    assert after["Cash desk"] == after["Card terminal"] == "USD"
    # Accounts someone opened in a currency, or that belong to a branch or a person, stay.
    assert after["Bank"] == after["Petty cash"] == after[safe.name] == "UZS"
    assert after["Dollar desk"] == "USD"
    assert sum(currency == "UZS" for currency in after.values()) == 4  # with Aziz's own account
    rows = AuditLog.objects.filter(company_id=books.pk, action="finance.account_updated")
    assert sorted(row.target for row in rows) == ["Card terminal", "Cash desk"]
    assert {str(row.details["changes"]) for row in rows} == {str({"currency": ["UZS", "USD"]})}
    assert all(row.actor == owner.user and row.required_perm == "finance.view" for row in rows)


def test_nothing_moves_once_money_is_booked(books, owner, cash):
    services.record_transaction(
        books,
        by=owner,
        kind="opening",
        account=cash,
        amount=Decimal("150000.00"),
        occurred_on=timezone.localdate(),
    )

    with pytest.raises(DomainError, match="stays UZS"):
        services.rebase_default_accounts(books, currency="USD", by=owner)

    assert set(currencies(books).values()) == {"UZS"}
    assert not AuditLog.objects.filter(action="finance.account_updated").exists()


def test_a_voided_entry_still_counts_as_booked(books, owner, cash):
    txn = services.record_transaction(
        books,
        by=owner,
        kind="opening",
        account=cash,
        amount=Decimal("1000.00"),
        occurred_on=timezone.localdate(),
    )
    services.void_transaction(txn, by=owner, reason="typo")

    with pytest.raises(DomainError):
        services.rebase_default_accounts(books, currency="USD", by=owner)


def test_the_same_currency_changes_nothing(books, owner):
    assert services.rebase_default_accounts(books, currency="UZS", by=owner) == []
    assert set(currencies(books).values()) == {"UZS"}


def test_it_is_a_persons_change_in_their_own_company(books, owner, other_company, member):
    stranger = member(other_company, "Owner")

    with pytest.raises(ValueError):
        services.rebase_default_accounts(books, currency="USD", by=None)
    with pytest.raises(ValueError):
        services.rebase_default_accounts(books, currency="XYZ", by=owner)
    with pytest.raises(DomainError):
        services.rebase_default_accounts(books, currency="USD", by=stranger)
    assert set(currencies(books).values()) == {"UZS"}
