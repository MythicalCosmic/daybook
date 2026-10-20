from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.finance import conf, queries, services
from apps.finance.models import Transaction, Transfer
from apps.finance.tests.factories import MoneyAccountFactory
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

D = Decimal
K = Transaction.Kind


def fund(company, by, account, amount, day):
    services.record_transaction(
        company, by=by, kind="opening", amount=amount, occurred_on=day, account=account
    )


def move(company, by, source_account, target, amount, day, **kwargs):
    return services.transfer(
        company,
        by=by,
        from_account=source_account,
        to_account=target,
        amount_out=amount,
        occurred_on=day,
        **kwargs,
    )


def rows(moved):
    return list(moved.transactions.order_by("pk"))


class TestOneCurrency:
    def test_the_whole_amount_arrives(self, books, owner, cash, bank, day):
        fund(books, owner, cash, 1000, day)
        moved = move(books, owner, cash, bank, 400, day, description="To the bank")

        assert (moved.amount_out, moved.amount_in, moved.exchange_rate) == (
            D("400.00"),
            D("400.00"),
            None,
        )
        assert [(r.kind, r.account, r.amount) for r in rows(moved)] == [
            (K.TRANSFER, cash, D("-400.00")),
            (K.TRANSFER, bank, D("400.00")),
        ]
        assert queries.balance(cash) == D("600.00")
        assert queries.balance(bank) == D("400.00")
        assert moved.created_by == owner.user
        assert AuditLog.objects.filter(action="finance.transfer_made").count() == 1

    def test_a_fee_is_a_bank_fee_on_the_sending_account(self, books, owner, cash, bank, day):
        fund(books, owner, cash, 1000, day)
        moved = move(books, owner, cash, bank, 400, day, fee=5)

        fee = rows(moved)[2]
        assert (fee.kind, fee.account, fee.amount, fee.category.system_code) == (
            K.EXPENSE,
            cash,
            D("-5.00"),
            "bank_fees",
        )
        assert queries.balance(cash) == D("595.00")

    def test_one_currency_rules(self, books, owner, cash, bank, day):
        fund(books, owner, cash, 1000, day)
        with pytest.raises(DomainError, match="whole amount"):
            move(books, owner, cash, bank, 400, day, amount_in=390)
        with pytest.raises(DomainError, match="no exchange rate"):
            move(books, owner, cash, bank, 400, day, rate=2)
        with pytest.raises(DomainError, match="two different"):
            move(books, owner, cash, cash, 400, day)
        with pytest.raises(DomainError, match="Not enough money"):
            move(books, owner, cash, bank, 1001, day)
        with pytest.raises(DomainError, match="Not enough money"):
            move(books, owner, cash, bank, 1000, day, fee=1)
        assert not Transfer.objects.exists()

    def test_archived_accounts_take_no_part(self, books, owner, cash, bank, day):
        fund(books, owner, cash, 1000, day)
        bank.is_active = False
        bank.save()
        with pytest.raises(DomainError, match="archived"):
            move(books, owner, cash, bank, 1, day)


class TestAcrossCurrencies:
    def test_som_to_dollars_at_the_rate_of_the_day(self, books, owner, cash, dollars, usd, day):
        fund(books, owner, cash, 2_000_000, day)
        moved = move(books, owner, cash, dollars, 1_280_000, day)

        assert (moved.amount_in, moved.exchange_rate) == (D("100.00"), D("12800"))
        out_row, in_row = rows(moved)
        assert (in_row.currency, in_row.rate, in_row.base_amount) == (
            "USD",
            D("12800"),
            D("1280000.00"),
        )
        assert out_row.base_amount == D("-1280000.00")
        assert queries.balance(dollars) == D("100.00")

    def test_an_exchange_office_rate_books_the_difference(
        self, books, owner, cash, dollars, usd, day
    ):
        fund(books, owner, cash, 2_000_000, day)
        moved = move(books, owner, cash, dollars, 1_290_000, day, amount_in=100)

        assert moved.exchange_rate == D("12900")
        _out, in_row, fx = rows(moved)
        assert in_row.base_amount == D("1280000.00")  # valued at the company's rate
        assert (fx.kind, fx.account, fx.base_amount, fx.currency) == (
            K.FX,
            None,
            D("-10000.00"),
            "UZS",
        )
        assert fx.category.system_code == "fx_diff"
        # In the base currency the transfer is exactly its exchange difference.
        assert sum(r.base_amount for r in rows(moved) if r.kind != K.FX) == fx.base_amount

    def test_dollars_to_som_with_a_given_rate(self, books, owner, cash, dollars, usd, day):
        fund(books, owner, dollars, 500, day)
        moved = move(books, owner, dollars, cash, 100, day, rate="12950")

        assert moved.amount_in == D("1295000.00")
        assert rows(moved)[2].base_amount == D("15000.00")  # sold above the official rate
        assert queries.balance(dollars) == D("400.00")
        assert queries.balance(cash) == D("1295000.00")

    def test_without_any_rate_the_transfers_own_rate_values_both_sides(
        self, books, owner, cash, dollars, day
    ):
        cash.allow_negative = True
        cash.save()
        moved = move(books, owner, cash, dollars, 1_300_000, day, amount_in=100)

        assert [r.kind for r in rows(moved)] == [K.TRANSFER, K.TRANSFER]
        assert rows(moved)[1].rate == D("13000")
        with pytest.raises(DomainError, match="no exchange rate"):
            move(books, owner, cash, dollars, 1_300_000, day)

    def test_a_fee_in_the_sending_currency(self, books, owner, cash, dollars, usd, day):
        fund(books, owner, dollars, 500, day)
        moved = move(books, owner, dollars, cash, 100, day, fee=2)

        fee = next(r for r in rows(moved) if r.kind == K.EXPENSE)
        assert (fee.currency, fee.amount, fee.base_amount) == ("USD", D("-2.00"), D("-25600.00"))
        assert queries.balance(dollars) == D("398.00")


class TestVoid:
    def test_voiding_puts_both_balances_back(self, books, owner, cash, dollars, usd, day):
        fund(books, owner, cash, 2_000_000, day)
        moved = move(books, owner, cash, dollars, 1_290_000, day, amount_in=100, fee=1000)

        services.void_transfer(moved, by=owner, reason="Never happened")

        moved.refresh_from_db()
        assert moved.status == Transfer.Status.VOID
        assert (moved.voided_by, moved.void_reason) == (owner.user, "Never happened")
        assert {r.status for r in rows(moved)} == {"void"}
        assert queries.balance(cash) == D("2000000.00")
        assert queries.balance(dollars) == 0
        with pytest.raises(DomainError, match="already void"):
            services.void_transfer(moved, by=owner, reason="Again")

    def test_a_transfer_row_is_voided_with_its_transfer(self, books, owner, cash, bank, day):
        fund(books, owner, cash, 100, day)
        moved = move(books, owner, cash, bank, 50, day)
        with pytest.raises(DomainError, match="void the transfer"):
            services.void_transaction(rows(moved)[0], by=owner, reason="x")

    def test_not_in_a_closed_period_and_only_by_a_person(self, books, owner, cash, bank, day):
        fund(books, owner, cash, 100, day)
        moved = move(books, owner, cash, bank, 50, day)
        with pytest.raises(ValueError):
            services.void_transfer(moved, by=None, reason="x")
        settings = conf.get_settings(books)
        settings.locked_until = day
        settings.save()
        with pytest.raises(DomainError, match="closed"):
            services.void_transfer(moved, by=owner, reason="x")
        with pytest.raises(DomainError, match="closed"):
            move(books, owner, cash, bank, 10, day)
        move(books, owner, cash, bank, 10, day + timedelta(days=1))


class TestSourcesAndCompany:
    def test_a_repeated_source_returns_the_first_transfer(self, books, cash, bank, day, src):
        cash.allow_negative = True
        cash.save()
        with pytest.raises(ValueError, match="source"):
            move(books, None, cash, bank, 10, day)
        first = move(books, None, cash, bank, 10, day, source=src(4))
        again = move(books, None, cash, bank, 10, day, source=src(4))

        assert again == first
        assert queries.balance(bank) == D("10.00")
        assert not AuditLog.objects.filter(action="finance.transfer_made").exists()

    def test_a_voided_transfer_frees_its_source(self, books, owner, cash, bank, day, src):
        fund(books, owner, cash, 100, day)
        first = move(books, owner, cash, bank, 10, day, source=src(4))
        services.void_transfer(first, by=owner, reason="Redo")

        assert move(books, owner, cash, bank, 20, day, source=src(4)) != first

    def test_accounts_and_actor_must_be_of_the_company(
        self, books, owner, cash, day, other_company
    ):
        foreign = MoneyAccountFactory(company=other_company)
        with pytest.raises(DomainError, match="same company"):
            move(books, owner, cash, foreign, 10, day)
        with pytest.raises(DomainError, match="same company"):
            move(books, owner, foreign, cash, 10, day)
        with pytest.raises(DomainError, match="same company"):
            move(books, MembershipFactory(company=other_company), cash, foreign, 10, day)


class TestLockOrder:
    def test_accounts_are_locked_in_id_order_in_one_statement(self, books, owner, cash, bank, day):
        fund(books, owner, bank, 100, day)
        assert bank.pk > cash.pk
        with CaptureQueriesContext(connection) as queries_run:
            move(books, owner, bank, cash, 10, day)  # from the higher id to the lower one

        locks = [q["sql"] for q in queries_run if "FOR UPDATE" in q["sql"]]
        account_locks = [sql for sql in locks if 'FROM "finance_moneyaccount"' in sql]
        assert len(account_locks) == 1
        assert 'ORDER BY "finance_moneyaccount"."id" ASC' in account_locks[0]
        assert f"IN ({cash.pk}, {bank.pk})" in account_locks[0]
