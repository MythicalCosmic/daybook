from datetime import timedelta
from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.finance import conf, queries, services
from apps.finance.models import Category, Transaction
from apps.finance.tests.factories import CategoryFactory, CounterpartyFactory, MoneyAccountFactory
from apps.members.permissions import Perm
from apps.members.tests.factories import MembershipFactory
from apps.projects.models import Project

pytestmark = pytest.mark.django_db

D = Decimal


def income(company, by, account, amount, day, **kwargs):
    kwargs.setdefault("category", "sales")
    return services.record_transaction(
        company, by=by, kind="income", amount=amount, occurred_on=day, account=account, **kwargs
    )


def expense(company, by, account, amount, day, **kwargs):
    kwargs.setdefault("category", "rent")
    return services.record_transaction(
        company, by=by, kind="expense", amount=amount, occurred_on=day, account=account, **kwargs
    )


def balance(account):
    return queries.balance(account)


class TestSigns:
    def test_income_comes_in_and_expense_goes_out(self, books, owner, cash, day):
        received = income(books, owner, cash, "500000", day)
        spent = expense(books, owner, cash, D("120000.50"), day)

        assert received.amount == D("500000.00")
        assert received.base_amount == D("500000.00")
        assert spent.amount == D("-120000.50")
        assert spent.base_amount == D("-120000.50")
        assert balance(cash) == D("379999.50")
        assert received.created_by == owner.user
        assert received.status == Transaction.Status.POSTED
        assert received.category.system_code == "sales"

    def test_a_contra_entry_reduces_its_kind(self, books, owner, cash, day):
        income(books, owner, cash, 300, day)
        refund = income(books, owner, cash, 100, day, category="refunds", is_contra=True)
        supplier_refund = expense(books, owner, cash, 50, day, is_contra=True)

        assert refund.amount == D("-100.00")
        assert supplier_refund.amount == D("50.00")
        assert balance(cash) == D("250.00")

    def test_owner_and_opening_entries_carry_their_own_sign(self, books, owner, cash, day):
        services.record_transaction(
            books, by=owner, kind="opening", amount=1000, occurred_on=day, account=cash
        )
        services.record_transaction(
            books, by=owner, kind="owner", amount=500, occurred_on=day, account=cash
        )
        draw = services.record_transaction(
            books, by=owner, kind="owner", amount=-300, occurred_on=day, account=cash
        )

        assert draw.amount == D("-300.00")
        assert balance(cash) == D("1200.00")

    @pytest.mark.parametrize("amount", [0, -5, "abc", None, "0.001", D("1e20")])
    def test_bad_amounts_are_refused(self, books, owner, cash, day, amount):
        with pytest.raises(DomainError):
            income(books, owner, cash, amount, day)
        assert not Transaction.objects.exists()

    def test_an_amount_too_large_in_the_base_currency_is_refused(
        self, books, owner, cash, dollars, usd, day
    ):
        with pytest.raises(DomainError, match="too large"):  # fits in dollars, not in som
            income(books, owner, dollars, D("9999999999999999"), day)
        income(books, owner, cash, D("9999999999999999.99"), day)
        with pytest.raises(DomainError, match="too large"):  # the balance can't hold more
            income(books, owner, cash, 1, day)
        assert balance(cash) == D("9999999999999999.99")

    def test_owner_and_opening_entries_need_an_account_and_no_category(
        self, books, owner, cash, day
    ):
        with pytest.raises(DomainError):
            services.record_transaction(books, by=owner, kind="owner", amount=5, occurred_on=day)
        with pytest.raises(DomainError):
            services.record_transaction(
                books,
                by=owner,
                kind="opening",
                amount=5,
                occurred_on=day,
                account=cash,
                category="sales",
            )

    @pytest.mark.parametrize("kind", ["transfer", "debt_open", "debt_payment", "write_off", "fx"])
    def test_other_kinds_go_through_their_own_services(self, books, owner, cash, day, kind):
        with pytest.raises(ValueError):
            services.record_transaction(
                books, by=owner, kind=kind, amount=5, occurred_on=day, account=cash
            )


class TestCategories:
    def test_an_income_needs_an_income_category(self, books, owner, cash, day):
        with pytest.raises(DomainError, match="income category"):
            income(books, owner, cash, 5, day, category="rent")
        with pytest.raises(DomainError, match="expense category"):
            expense(books, owner, cash, 5, day, category="sales")
        with pytest.raises(DomainError, match="category"):
            income(books, owner, cash, 5, day, category=None)

    def test_a_category_object_works_and_an_archived_one_is_refused(self, books, owner, cash, day):
        snacks = CategoryFactory(company=books, name="Snacks", kind=Category.Kind.EXPENSE)
        income(books, owner, cash, 100, day)
        assert expense(books, owner, cash, 5, day, category=snacks).category == snacks

        snacks.is_active = False
        snacks.save()
        with pytest.raises(DomainError, match="archived"):
            expense(books, owner, cash, 5, day, category=snacks)

    def test_a_missing_system_category_is_made_on_first_use(self, company, member, day):
        owner = member(company, "Owner")
        account = MoneyAccountFactory(company=company)
        row = income(company, owner, account, 5, day)

        assert row.category.system_code == "sales"
        assert Category.objects.filter(company=company, system_code="fx_diff").exists()

    def test_an_unknown_system_code_is_a_programming_error(self, books, owner, cash, day):
        with pytest.raises(ValueError):
            income(books, owner, cash, 5, day, category="lottery")


class TestLinks:
    def test_the_row_takes_the_accounts_branch(self, books, owner, day):
        branch = books.branches.first() or BranchFactory(company=books)
        till = MoneyAccountFactory(company=books, branch=branch)

        assert income(books, owner, till, 5, day).branch == branch

    def test_everything_must_belong_to_the_company(self, books, owner, cash, day, other_company):
        foreign = {
            "account": MoneyAccountFactory(company=other_company),
            "counterparty": CounterpartyFactory(company=other_company),
            "membership": MembershipFactory(company=other_company),
            "branch": BranchFactory(company=other_company),
            "category": CategoryFactory(company=other_company, kind="income"),
            "project": Project.objects.create(company=other_company, name="X", key="XX"),
        }
        for field, obj in foreign.items():
            kwargs = {"account": cash, field: obj}
            with pytest.raises(DomainError, match="same company"):
                income(books, owner, amount=5, day=day, **kwargs)
        with pytest.raises(DomainError, match="same company"):
            income(books, MembershipFactory(company=other_company), cash, 5, day)
        assert not Transaction.objects.exists()

    def test_every_entry_is_on_an_account(self, books, owner, day):
        with pytest.raises(DomainError, match="account"):
            services.record_transaction(
                books, by=owner, kind="income", amount=5, occurred_on=day, category="sales"
            )

    def test_a_row_may_concern_a_debt_without_settling_it(self, books, owner, cash, day):
        loan = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="loan",
            amount=1000,
            currency="UZS",
            issued_on=day,
            counterparty=CounterpartyFactory(company=books),
            account=cash,
        )
        interest = expense(books, owner, cash, 50, day, category="bank_fees", debt=loan)

        loan.refresh_from_db()
        assert (interest.debt, loan.paid) == (loan, 0)
        assert interest.debt_amount is None
        services.void_transaction(interest, by=owner, reason="Waived")
        assert balance(cash) == D("1000.00")
        with pytest.raises(ValueError):
            expense(books, owner, cash, 50, day, debt_amount=5)
        with pytest.raises(ValueError, match="pay_debt"):  # it would settle nothing
            expense(books, owner, cash, 50, day, category="bank_fees", debt=loan, debt_amount=50)

    def test_a_project_can_be_charged(self, books, owner, cash, day):
        project = Project.objects.create(company=books, name="Opening", key="OPEN")
        cash.allow_negative = True
        cash.save()
        row = expense(books, owner, cash, 100, day, project=project)

        assert list(project.finance_transactions.all()) == [row]

    def test_the_account_currency_rules(self, books, owner, dollars, usd, day):
        with pytest.raises(DomainError, match="holds USD"):
            income(books, owner, dollars, 5, day, currency="UZS")
        row = income(books, owner, dollars, 5, day)

        assert row.currency == "USD"

    def test_an_archived_account_takes_nothing(self, books, owner, cash, day):
        cash.is_active = False
        cash.save()
        with pytest.raises(DomainError, match="archived"):
            income(books, owner, cash, 5, day)


class TestRates:
    def test_a_dollar_row_freezes_the_rate_of_the_day(self, books, owner, dollars, usd, day):
        row = income(books, owner, dollars, D("100.50"), day)

        assert row.rate == D("12800")
        assert row.rate_stale is False
        assert row.base_amount == D("1286400.00")
        assert balance(dollars) == D("100.50")

    def test_a_given_rate_wins(self, books, owner, dollars, usd, day):
        row = income(books, owner, dollars, 10, day, rate="13000")

        assert row.rate == D("13000")
        assert row.base_amount == D("130000.00")

    def test_an_older_rate_is_marked_stale(self, books, owner, dollars, usd, day):
        row = income(books, owner, dollars, 10, day + timedelta(days=3))

        assert row.rate == D("12800")
        assert row.rate_stale is True

    def test_no_rate_at_all_is_refused(self, books, owner, dollars, day):
        with pytest.raises(DomainError, match="no exchange rate"):
            income(books, owner, dollars, 10, day)

    def test_the_base_currency_takes_no_rate(self, books, owner, cash, day):
        with pytest.raises(DomainError, match="base currency"):
            income(books, owner, cash, 10, day, rate="2")

    def test_a_dollar_company_divides_som_by_the_rate(self, company, member, usd, day):
        company.base_currency = "USD"
        company.save()
        owner = member(company, "Owner")
        som = MoneyAccountFactory(company=company, currency="UZS")
        dollars = MoneyAccountFactory(company=company, currency="USD")

        row = income(company, owner, som, 1_280_000, day)
        same = income(company, owner, dollars, 15, day)

        assert row.rate == D("12800")
        assert row.base_amount == D("100.00")
        assert same.rate == 1
        assert same.base_amount == D("15.00")


class TestApproval:
    def test_a_pending_entry_moves_nothing_until_approved(
        self, books, owner, accountant, cash, day
    ):
        income(books, owner, cash, 1000, day)
        claim = expense(books, accountant, cash, 300, day, status="pending")
        assert balance(cash) == D("1000.00")

        services.approve_transaction(claim, by=owner)

        claim.refresh_from_db()
        assert claim.status == Transaction.Status.POSTED
        assert claim.approved_by == owner.user
        assert claim.approved_at is not None
        assert balance(cash) == D("700.00")
        with pytest.raises(DomainError, match="waiting"):
            services.approve_transaction(claim, by=owner)

    def test_approval_still_needs_the_money(self, books, owner, cash, day):
        claim = expense(books, owner, cash, 300, day, status="pending")
        with pytest.raises(DomainError, match="Not enough money"):
            services.approve_transaction(claim, by=owner)

    def test_a_rejected_entry_never_counts(self, books, owner, cash, day):
        claim = expense(books, owner, cash, 300, day, status="pending")
        with pytest.raises(DomainError):
            services.reject_transaction(claim, by=owner, reason="  ")

        services.reject_transaction(claim, by=owner, reason="No receipt")

        claim.refresh_from_db()
        assert claim.status == Transaction.Status.REJECTED
        assert claim.void_reason == "No receipt"
        assert claim.voided_by == owner.user
        with pytest.raises(DomainError):
            services.approve_transaction(claim, by=owner)

    def test_only_incomes_and_expenses_wait(self, books, owner, cash, day):
        with pytest.raises(ValueError):
            services.record_transaction(
                books,
                by=owner,
                kind="owner",
                amount=5,
                occurred_on=day,
                account=cash,
                status="pending",
            )


class TestVoid:
    def test_voiding_takes_the_row_off_the_balance(self, books, owner, cash, day):
        received = income(books, owner, cash, 1000, day)
        spent = expense(books, owner, cash, 400, day)

        services.void_transaction(received, by=owner, reason="Typed twice")

        received.refresh_from_db()
        assert received.status == Transaction.Status.VOID
        assert received.voided_by == owner.user
        assert received.void_reason == "Typed twice"
        # A correction may leave the account below zero.
        assert balance(cash) == D("-400.00")
        assert queries.ledger_balance(cash) == D("-400.00")
        with pytest.raises(DomainError, match="already void"):
            services.void_transaction(received, by=owner, reason="Again")
        services.void_transaction(spent, by=owner, reason="Wrong")
        assert balance(cash) == 0

    def test_voiding_a_pending_row_moves_nothing(self, books, owner, cash, day):
        income(books, owner, cash, 1000, day)
        claim = expense(books, owner, cash, 300, day, status="pending")

        services.void_transaction(claim, by=owner, reason="Withdrawn")

        assert balance(cash) == D("1000.00")

    def test_a_person_voids_a_row(self, books, owner, cash, day, src):
        row = income(books, None, cash, 5, day, source=src(1))
        with pytest.raises(ValueError):
            services.void_transaction(row, by=None, reason="System")


class TestNegativeBalances:
    def test_an_account_cant_go_below_zero(self, books, owner, cash, day):
        income(books, owner, cash, 100, day)
        with pytest.raises(DomainError, match="Not enough money"):
            expense(books, owner, cash, D("100.01"), day)
        assert balance(cash) == D("100.00")
        assert Transaction.objects.count() == 1

    def test_unless_it_allows_it(self, books, owner, cash, day):
        cash.allow_negative = True
        cash.save()
        expense(books, owner, cash, 100, day)

        assert balance(cash) == D("-100.00")


class TestPeriodLock:
    def test_nothing_is_added_on_or_before_the_lock(self, books, owner, cash, day):
        settings = conf.get_settings(books)
        settings.locked_until = day
        settings.save()

        with pytest.raises(DomainError, match="closed"):
            income(books, owner, cash, 5, day)
        with pytest.raises(DomainError, match="closed"):
            income(books, owner, cash, 5, day - timedelta(days=30))
        assert income(books, owner, cash, 5, day + timedelta(days=1)).amount == 5

    def test_rows_in_a_closed_period_are_not_voided_or_approved(self, books, owner, cash, day):
        received = income(books, owner, cash, 50, day)
        claim = expense(books, owner, cash, 5, day, status="pending")
        other = expense(books, owner, cash, 5, day, status="pending")
        settings = conf.get_settings(books)
        settings.locked_until = day
        settings.save()

        with pytest.raises(DomainError, match="closed"):
            services.void_transaction(received, by=owner, reason="Late")
        with pytest.raises(DomainError, match="closed"):
            services.approve_transaction(claim, by=owner)
        # Rejecting changes no posted number, so a closed period doesn't block it.
        services.reject_transaction(other, by=owner, reason="No")
        assert balance(cash) == D("50.00")


class TestSources:
    def test_a_repeated_source_returns_the_first_row(self, books, cash, day, src):
        first = income(books, None, cash, 100, day, source=src(7, "m1"))
        again = income(books, None, cash, 999, day, source=src(7, "m1"))
        other_key = income(books, None, cash, 1, day, source=src(7, "m2"))

        assert again == first
        assert other_key != first
        assert first.source_type == "finance.test"
        assert (first.source_id, first.source_key) == (7, "m1")
        assert first.created_by is None
        assert balance(cash) == D("101.00")

    def test_a_voided_booking_frees_its_source(self, books, owner, cash, day, src):
        first = income(books, owner, cash, 100, day, source=src(7, "diff"))
        services.void_transaction(first, by=owner, reason="Corrected")
        second = income(books, owner, cash, 120, day, source=src(7, "diff"))

        assert second != first
        assert balance(cash) == D("120.00")

    def test_the_system_must_pass_a_source(self, books, cash, day):
        with pytest.raises(ValueError, match="source"):
            income(books, None, cash, 100, day)
        assert not Transaction.objects.exists()

    def test_an_unregistered_source_is_refused(self, books, cash, day):
        with pytest.raises(ValueError, match="Register"):
            income(books, None, cash, 100, day, source=("sales.cashshift", 1, ""))

    def test_sources_are_per_company(self, books, cash, day, src, other_company):
        other_cash = MoneyAccountFactory(company=other_company)
        mine = income(books, None, cash, 100, day, source=src(1))
        theirs = income(other_company, None, other_cash, 100, day, source=src(1))

        assert mine != theirs

    def test_a_repeat_must_be_the_same_booking(self, books, cash, bank, day, src):
        first = income(books, None, cash, 100, day, source=src(8, "m1"))
        with pytest.raises(ValueError, match="account_id"):
            income(books, None, bank, 100, day, source=src(8, "m1"))
        with pytest.raises(ValueError, match="kind"):
            expense(books, None, cash, 100, day, source=src(8, "m1"))
        assert list(Transaction.objects.all()) == [first]


class TestAudit:
    def test_a_person_made_entry_is_audited(self, books, owner, cash, day):
        row = income(books, owner, cash, 100, day)

        log = AuditLog.objects.get(action="finance.transaction_recorded")
        assert log.actor == owner.user
        assert log.target_id == row.pk
        assert log.details["amount"] == "100.00"

    def test_salary_detail_is_kept_from_people_without_payroll_view(self, books, owner, cash, day):
        income(books, owner, cash, 1000, day)
        expense(books, owner, cash, 100, day, category="salaries")

        rows = AuditLog.objects.filter(action="finance.transaction_recorded").order_by("pk")
        # The field the audit views filter on, whether or not audit.record() sets it itself.
        assert [row.required_perm for row in rows] == [Perm.FINANCE_VIEW, Perm.PAYROLL_VIEW]

    def test_sourced_writes_are_audited_by_their_module(self, books, cash, day, src):
        income(books, None, cash, 100, day, source=src(1))

        assert not AuditLog.objects.filter(action__startswith="finance.").exists()
