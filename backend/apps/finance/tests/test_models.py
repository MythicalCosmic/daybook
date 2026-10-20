"""The database refuses ledger rows that break the rules, whoever writes them."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.companies.tests.factories import BranchFactory
from apps.finance import services
from apps.finance.models import Category, Counterparty, Debt, MoneyAccount, Transaction, Transfer
from apps.finance.tests.factories import (
    CategoryFactory,
    CounterpartyFactory,
    ExchangeRateFactory,
    MoneyAccountFactory,
)
from apps.members.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

D = Decimal


def refused(make):
    with pytest.raises(IntegrityError), transaction.atomic():
        make()


@pytest.fixture
def sales(books):
    return Category.objects.get(company=books, system_code="sales")


@pytest.fixture
def rent(books):
    return Category.objects.get(company=books, system_code="rent")


@pytest.fixture
def debt(books, day):
    return Debt.objects.create(
        company=books,
        direction="receivable",
        kind="trade",
        counterparty=CounterpartyFactory(company=books),
        amount=100,
        issued_on=day,
    )


@pytest.fixture
def row(books, cash, sales, day):
    """Makes a transaction: a valid income unless told otherwise."""

    def make(**changes):
        fields = {
            "company": books,
            "kind": "income",
            "occurred_on": day,
            "account": cash,
            "amount": D("10"),
            "base_amount": D("10"),
            "category": sales,
        }
        fields.update(changes)
        return Transaction.objects.create(**fields)

    return make


class TestTransactionRules:
    def test_a_valid_row(self, row):
        assert row().pk

    def test_amounts_are_never_zero_except_exchange_differences(self, row, rent, debt):
        refused(lambda: row(amount=0, base_amount=0))
        assert row(kind="fx", account=None, amount=0, base_amount=5, category=rent).pk

    def test_income_is_positive_and_expense_negative(self, row, rent):
        out = {"amount": -10, "base_amount": -10}
        refused(lambda: row(**out))
        refused(lambda: row(kind="expense", amount=10, category=rent))
        assert row(**out, is_contra=True).pk
        assert row(kind="expense", amount=10, category=rent, is_contra=True).pk
        original = row()
        assert row(**out, reverses=original).pk

    def test_some_kinds_need_an_account(self, row, debt):
        for kind in ("transfer", "opening", "owner", "debt_open"):
            refused(lambda kind=kind: row(kind=kind, account=None, category=None, debt=debt))

    def test_debt_kinds_need_a_debt(self, row, rent):
        for kind in ("debt_open", "debt_payment", "write_off"):
            refused(lambda kind=kind: row(kind=kind, category=rent))

    def test_an_income_or_expense_needs_an_account_or_a_debt(self, row, debt):
        refused(lambda: row(account=None))
        assert row(account=None, debt=debt).pk

    def test_pnl_kinds_need_a_category(self, row, debt):
        for kind, amount in (("income", 10), ("expense", -10), ("write_off", -10), ("fx", 1)):
            refused(
                lambda kind=kind, amount=amount: row(
                    kind=kind, amount=amount, category=None, account=None, debt=debt
                )
            )

    def test_an_exchange_difference_has_no_account(self, row, rent):
        refused(lambda: row(kind="fx", category=rent))

    def test_a_transfer_row_belongs_to_a_transfer(self, row):
        refused(lambda: row(kind="transfer", category=None))

    def test_the_rate_is_positive(self, row):
        refused(lambda: row(rate=0))

    def test_a_settled_amount_is_positive_and_needs_its_debt(self, row, debt):
        refused(lambda: row(debt_amount=5))
        refused(lambda: row(debt=debt, debt_amount=0))
        refused(lambda: row(debt=debt, debt_amount=-5))
        assert row(debt=debt, debt_amount=5).pk

    def test_the_base_amount_points_the_way_the_amount_does(self, row, rent):
        refused(lambda: row(base_amount=-10))
        refused(lambda: row(kind="expense", category=rent, amount=-10, base_amount=10))
        assert row(amount=D("0.01"), base_amount=0).pk  # a tiyin of som in a dollar company

    def test_a_source_is_complete_and_live_rows_hold_it_once(self, row):
        refused(lambda: row(source_type="finance.test"))
        refused(lambda: row(source_id=5))
        first = row(source_type="finance.test", source_id=5, source_key="a")
        refused(lambda: row(source_type="finance.test", source_id=5, source_key="a"))
        assert row(source_type="finance.test", source_id=5, source_key="b").pk
        first.status = "void"
        first.save()
        assert row(source_type="finance.test", source_id=5, source_key="a").pk
        rejected = row(source_type="finance.test", source_id=6, status="rejected")
        assert row(source_type="finance.test", source_id=6).pk != rejected.pk

    def test_ledger_rows_are_protected(self, row, cash, sales, books):
        txn = row()
        with pytest.raises(ProtectedError):
            cash.delete()
        with pytest.raises(ProtectedError):
            sales.delete()
        assert txn.pk


class TestDebtRules:
    def test_paid_stays_within_the_amount(self, debt):
        debt.paid = D("100.01")
        refused(debt.save)
        debt.paid = D("-1")
        refused(debt.save)

    def test_exactly_one_party(self, books, day, member):
        party = CounterpartyFactory(company=books)
        worker = member(books)
        base = {"company": books, "direction": "payable", "amount": 5, "issued_on": day}
        refused(lambda: Debt.objects.create(**base))
        refused(lambda: Debt.objects.create(**base, counterparty=party, membership=worker))

    def test_amount_rate_and_dates(self, books, day):
        party = CounterpartyFactory(company=books)
        base = {"company": books, "direction": "payable", "issued_on": day, "counterparty": party}
        refused(lambda: Debt.objects.create(**base, amount=0))
        refused(lambda: Debt.objects.create(**base, amount=5, rate=0))
        refused(lambda: Debt.objects.create(**base, amount=5, due_on=day - timedelta(days=1)))

    def test_lock_and_source_are_complete_and_sources_unique_until_cancelled(self, debt):
        debt.locked_by_type = "finance.test"
        refused(debt.save)
        debt.locked_by_type = ""
        debt.source_type, debt.source_id = "finance.test", 1
        debt.save()
        twin = Debt.objects.get(pk=debt.pk)
        twin.pk = None
        refused(twin.save)
        debt.status = "cancelled"
        debt.save()
        twin.pk = None
        twin.save()
        assert twin.pk


class TestTransferRules:
    def test_two_accounts_and_positive_amounts(self, books, cash, bank, day):
        base = {"company": books, "occurred_on": day, "from_account": cash}
        refused(lambda: Transfer.objects.create(**base, to_account=cash, amount_out=1, amount_in=1))
        refused(lambda: Transfer.objects.create(**base, to_account=bank, amount_out=0, amount_in=1))
        refused(
            lambda: Transfer.objects.create(
                **base, to_account=bank, amount_out=1, amount_in=1, fee=-1
            )
        )
        refused(
            lambda: Transfer.objects.create(
                **base, to_account=bank, amount_out=1, amount_in=1, exchange_rate=0
            )
        )

    def test_a_source_is_held_by_one_posted_transfer(self, books, cash, bank, day):
        base = {
            "company": books,
            "occurred_on": day,
            "from_account": cash,
            "to_account": bank,
            "amount_out": 1,
            "amount_in": 1,
            "source_type": "finance.test",
            "source_id": 1,
        }
        first = Transfer.objects.create(**base)
        refused(lambda: Transfer.objects.create(**base))
        first.status = "void"
        first.save()
        assert Transfer.objects.create(**base).pk


class TestAccountRules:
    def test_names_are_unique_per_company(self, books, cash, other_company):
        refused(lambda: MoneyAccountFactory(company=books, name=cash.name))
        assert MoneyAccountFactory(company=other_company, name=cash.name).pk

    def test_employee_and_owner_accounts_have_a_holder(self, books):
        refused(lambda: MoneyAccountFactory(company=books, kind="employee"))
        refused(lambda: MoneyAccountFactory(company=books, kind="owner"))

    def test_one_safe_per_branch_and_currency_and_one_account_per_holder(self, books, member):
        branch = BranchFactory(company=books)
        MoneyAccountFactory(company=books, kind="safe", branch=branch)
        refused(lambda: MoneyAccountFactory(company=books, kind="safe", branch=branch))
        assert MoneyAccountFactory(company=books, kind="safe", branch=branch, currency="USD").pk
        assert MoneyAccountFactory(company=books, kind="safe").pk  # company-level safes
        assert MoneyAccountFactory(company=books, kind="safe").pk
        worker = member(books)
        MoneyAccountFactory(company=books, kind="employee", holder=worker)
        refused(lambda: MoneyAccountFactory(company=books, kind="employee", holder=worker))

    def test_clean_keeps_links_in_the_company(self, books, other_company):
        account = MoneyAccountFactory.build(
            company=books, kind="cash", branch=BranchFactory(company=other_company)
        )
        with pytest.raises(ValidationError):
            account.clean()
        account = MoneyAccountFactory.build(company=books, kind="employee")
        with pytest.raises(ValidationError):
            account.clean()
        account = MoneyAccountFactory.build(
            company=books, kind="employee", holder=MembershipFactory(company=other_company)
        )
        with pytest.raises(ValidationError):
            account.clean()


class TestCategoryRules:
    def test_names_are_unique_among_siblings_top_level_included(self, books, rent):
        refused(lambda: CategoryFactory(company=books, name=rent.name))
        child = CategoryFactory(company=books, name="Shop", parent=rent)
        refused(lambda: CategoryFactory(company=books, name="Shop", parent=rent))
        assert child.pk

    def test_system_codes_are_unique(self, books):
        refused(lambda: CategoryFactory(company=books, system_code="rent"))

    def test_two_levels_of_the_same_kind_in_the_same_company(
        self, books, rent, sales, other_company
    ):
        child = CategoryFactory(company=books, parent=rent)
        with pytest.raises(ValidationError, match="two levels"):
            CategoryFactory.build(company=books, parent=child).clean()
        with pytest.raises(ValidationError, match="kind"):
            CategoryFactory.build(company=books, parent=sales, kind="expense").clean()
        with pytest.raises(ValidationError, match="same company"):
            CategoryFactory.build(company=other_company, parent=rent).clean()
        with pytest.raises(ValidationError, match="two levels"):
            rent.parent = sales
            rent.kind = "income"
            rent.clean()
        rent.refresh_from_db()
        CategoryFactory.build(company=books, parent=rent).clean()


class TestCounterpartyRules:
    def test_phone_and_tin_are_unique_when_given(self, books):
        CounterpartyFactory(company=books, phone="+998901234567", tin="123456789")
        refused(lambda: CounterpartyFactory(company=books, phone="+998901234567"))
        refused(lambda: CounterpartyFactory(company=books, tin="123456789"))
        assert CounterpartyFactory(company=books).pk
        assert CounterpartyFactory(company=books).pk

    def test_validation(self, books, other_company):
        party = Counterparty(company=books, name="X", phone="901234567")
        with pytest.raises(ValidationError):
            party.full_clean()
        party = Counterparty(
            company=books,
            name="X",
            default_category=CategoryFactory(company=other_company),
        )
        with pytest.raises(ValidationError):
            party.clean()


class TestRates:
    def test_one_rate_per_currency_day_and_source(self, day):
        ExchangeRateFactory(date=day)
        refused(lambda: ExchangeRateFactory(date=day))
        assert ExchangeRateFactory(date=day, source="manual").pk
        refused(lambda: ExchangeRateFactory(date=day, currency="UZS", source="manual"))
        refused(lambda: ExchangeRateFactory(date=day.replace(year=2020), rate=0))


def test_services_and_models_agree_on_holder_kinds():
    assert set(MoneyAccount.HOLDER_KINDS) == {"employee", "owner"}
    assert services.ROW_SOURCE == "finance.transaction"
