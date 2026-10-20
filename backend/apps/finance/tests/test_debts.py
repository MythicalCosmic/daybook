from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.finance import conf, queries, services
from apps.finance.models import Debt, Transaction
from apps.finance.tests.factories import (
    CounterpartyFactory,
    ExchangeRateFactory,
    MoneyAccountFactory,
)
from apps.members.tests.factories import MembershipFactory
from apps.projects.models import Project

pytestmark = pytest.mark.django_db

D = Decimal
K = Transaction.Kind


@pytest.fixture
def customer(books):
    return CounterpartyFactory(company=books, name="Bek Market")


@pytest.fixture
def supplier(books):
    return CounterpartyFactory(company=books, name="Coca-Cola", kind="supplier")


@pytest.fixture
def later(usd, day):
    """Ten days on, the dollar costs 13 000 so'm."""
    return ExchangeRateFactory(date=day + timedelta(days=10), rate=D("13000")).date


def invoice(company, by, party, amount, day, currency="UZS", **kwargs):
    """Sold on credit: a receivable that books the income now."""
    kwargs.setdefault("category", "sales")
    return services.open_debt(
        company,
        by=by,
        direction="receivable",
        kind="trade",
        amount=amount,
        currency=currency,
        issued_on=day,
        counterparty=party,
        **kwargs,
    )


def rows(debt, **filters):
    return list(Transaction.objects.filter(debt=debt, **filters).order_by("pk"))


def fund(company, by, account, amount, day):
    services.record_transaction(
        company,
        by=by,
        kind="opening",
        amount=amount,
        occurred_on=day,
        account=account,
    )


class TestOpening:
    def test_a_sale_on_credit_books_the_income_as_an_accrual(self, books, owner, customer, day):
        debt = invoice(books, owner, customer, 1_000_000, day, due_on=day + timedelta(days=7))

        assert debt.status == Debt.Status.OPEN
        assert debt.outstanding == D("1000000.00")
        assert debt.rate == 1
        assert debt.created_by == owner.user
        [accrual] = rows(debt)
        assert accrual.kind == K.INCOME
        assert accrual.account is None
        assert accrual.amount == D("1000000.00")
        assert accrual.debt_amount == D("1000000.00")
        assert accrual.counterparty == customer
        assert accrual.category.system_code == "sales"

    def test_a_bill_books_the_expense(self, books, owner, supplier, day):
        debt = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="bill",
            amount=200,
            currency="UZS",
            issued_on=day,
            counterparty=supplier,
            category="goods",
        )

        assert [(row.kind, row.amount) for row in rows(debt)] == [(K.EXPENSE, D("-200.00"))]

    def test_a_loan_given_leaves_the_account_and_a_loan_taken_arrives(
        self, books, owner, customer, cash, day
    ):
        fund(books, owner, cash, 1000, day)
        lent = services.open_debt(
            books,
            by=owner,
            direction="receivable",
            kind="loan",
            amount=300,
            currency="UZS",
            issued_on=day,
            counterparty=customer,
            account=cash,
        )
        borrowed = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="loan",
            amount=5000,
            currency="UZS",
            issued_on=day,
            counterparty=customer,
            account=cash,
        )

        assert [(r.kind, r.amount, r.account) for r in rows(lent)] == [
            (K.DEBT_OPEN, D("-300.00"), cash)
        ]
        assert rows(borrowed)[0].amount == D("5000.00")
        assert queries.balance(cash) == D("5700.00")

    def test_an_opening_debt_records_only_the_debt(self, books, owner, customer, day):
        debt = services.open_debt(
            books,
            by=owner,
            direction="receivable",
            kind="trade",
            amount=750,
            currency="UZS",
            issued_on=day,
            counterparty=customer,
            is_opening=True,
        )

        assert debt.is_opening
        assert rows(debt) == []

    def test_a_dollar_debt_freezes_the_rate(self, books, owner, customer, usd, day):
        debt = invoice(books, owner, customer, 100, day, currency="USD")

        assert debt.rate == D("12800")
        [accrual] = rows(debt)
        assert (accrual.currency, accrual.amount, accrual.base_amount) == (
            "USD",
            D("100.00"),
            D("1280000.00"),
        )

    def test_an_employee_debt_and_a_project(self, books, owner, member, cash, day):
        worker = member(books, first_name="Jasur")
        project = Project.objects.create(company=books, name="Opening", key="OPEN")
        fund(books, owner, cash, 1000, day)
        advance = services.open_debt(
            books,
            by=owner,
            direction="receivable",
            kind="advance",
            amount=500,
            currency="UZS",
            issued_on=day,
            membership=worker,
            account=cash,
            project=project,
        )

        assert advance.membership == worker
        assert list(project.debts.all()) == [advance]
        assert rows(advance)[0].membership == worker
        assert rows(advance)[0].project == project

    @pytest.mark.parametrize(
        "change, message",
        [
            (lambda o: {"counterparty": None}, "one counterparty or one employee"),
            (lambda o: {"membership": o["worker"]}, "one counterparty or one employee"),
            (lambda o: {"due_on": o["day"] - timedelta(days=1)}, "due date"),
            (lambda o: {"account": o["cash"]}, "Pick an account"),
            (lambda o: {"category": "rent"}, "income category"),
            (
                lambda o: {"category": None, "is_opening": True, "account": o["cash"]},
                "opening debt",
            ),
            (lambda o: {"category": None, "account": o["dollars"]}, "holds USD"),
            (lambda o: {"category": None}, "record it as an opening debt"),
            (lambda o: {"amount": 0}, "zero"),
        ],
    )
    def test_bad_debts_are_refused(
        self, books, owner, member, customer, cash, dollars, day, change, message
    ):
        objects = {"worker": member(books), "cash": cash, "dollars": dollars, "day": day}
        kwargs = {
            "direction": "receivable",
            "kind": "trade",
            "amount": 100,
            "currency": "UZS",
            "issued_on": day,
            "counterparty": customer,
            "category": "sales",
        }
        kwargs.update(change(objects))
        with pytest.raises(DomainError, match=message):
            services.open_debt(books, by=owner, **kwargs)
        assert not Debt.objects.exists()

    def test_everything_must_belong_to_the_company(
        self, books, owner, customer, day, other_company
    ):
        with pytest.raises(DomainError, match="same company"):
            invoice(books, owner, CounterpartyFactory(company=other_company), 5, day)
        with pytest.raises(DomainError, match="same company"):
            invoice(
                books, owner, customer, 5, day, responsible=MembershipFactory(company=other_company)
            )
        with pytest.raises(DomainError, match="same company"):
            invoice(books, MembershipFactory(company=other_company), customer, 5, day)

    def test_the_system_passes_a_source_and_a_repeat_returns_the_first_debt(
        self, books, customer, day, src
    ):
        with pytest.raises(ValueError, match="source"):
            invoice(books, None, customer, 5, day)
        first = invoice(books, None, customer, 5, day, source=src(42, "issue"))
        again = invoice(books, None, customer, 50, day, source=src(42, "issue"))
        tax = invoice(books, None, customer, 1, day, source=src(42, "tax"))

        assert again == first
        assert tax != first
        assert (first.source_type, first.source_id, first.source_key) == (
            "finance.test",
            42,
            "issue",
        )
        assert rows(first)[0].source_type == "finance.test"
        assert Debt.objects.count() == 2

    def test_a_repeat_must_be_the_same_debt(self, books, customer, member, day, src):
        invoice(books, None, customer, 5, day, source=src(43, "issue"))
        with pytest.raises(ValueError, match="counterparty_id"):
            invoice(
                books, None, CounterpartyFactory(company=books), 5, day, source=src(43, "issue")
            )
        with pytest.raises(ValueError, match="direction"):
            services.open_debt(
                books,
                by=None,
                direction="payable",
                kind="trade",
                amount=5,
                currency="UZS",
                issued_on=day,
                counterparty=customer,
                category="goods",
                source=src(43, "issue"),
            )
        assert Debt.objects.count() == 1


class TestPaying:
    def test_partial_payments_until_paid(self, books, owner, customer, cash, day):
        debt = invoice(books, owner, customer, 1000, day)
        first = services.pay_debt(debt, by=owner, amount=400, paid_on=day, account=cash)

        debt.refresh_from_db()
        assert (debt.paid, debt.status) == (D("400.00"), Debt.Status.OPEN)
        assert (first.kind, first.amount, first.debt_amount) == (
            K.DEBT_PAYMENT,
            D("400.00"),
            D("400.00"),
        )
        assert first.counterparty == customer

        services.pay_debt(debt, by=owner, amount=600, paid_on=day, account=cash)

        debt.refresh_from_db()
        assert (debt.paid, debt.status, debt.outstanding) == (D("1000.00"), Debt.Status.PAID, 0)
        assert queries.balance(cash) == D("1000.00")
        with pytest.raises(DomainError, match="settled"):
            services.pay_debt(debt, by=owner, amount=1, paid_on=day, account=cash)

    def test_paying_a_payable_takes_money_out(self, books, owner, supplier, cash, day):
        fund(books, owner, cash, 1000, day)
        bill = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="bill",
            amount=300,
            currency="UZS",
            issued_on=day,
            counterparty=supplier,
            category="rent",
        )
        payment = services.pay_debt(bill, by=owner, amount=300, paid_on=day, account=cash)

        assert payment.amount == D("-300.00")
        assert queries.balance(cash) == D("700.00")

    def test_more_than_is_owed_is_refused(self, books, owner, customer, cash, day):
        debt = invoice(books, owner, customer, 100, day)
        with pytest.raises(DomainError, match="more than"):
            services.pay_debt(debt, by=owner, amount=D("100.01"), paid_on=day, account=cash)

    def test_not_before_it_was_issued_and_not_in_a_closed_period(
        self, books, owner, customer, cash, day
    ):
        debt = invoice(books, owner, customer, 100, day)
        with pytest.raises(DomainError, match="before the day"):
            services.pay_debt(
                debt, by=owner, amount=10, paid_on=day - timedelta(days=1), account=cash
            )
        settings = conf.get_settings(books)
        settings.locked_until = day
        settings.save()
        with pytest.raises(DomainError, match="closed"):
            services.pay_debt(debt, by=owner, amount=10, paid_on=day, account=cash)
        services.pay_debt(debt, by=owner, amount=10, paid_on=day + timedelta(days=1), account=cash)

    def test_an_offset_moves_no_money(self, books, owner, member, cash, day):
        worker = member(books)
        fund(books, owner, cash, 1000, day)
        advance = services.open_debt(
            books,
            by=owner,
            direction="receivable",
            kind="advance",
            amount=400,
            currency="UZS",
            issued_on=day,
            membership=worker,
            account=cash,
        )
        with pytest.raises(DomainError, match="must match"):
            services.pay_debt(advance, by=owner, amount=1, paid_on=day, debt_amount=2)
        offset = services.pay_debt(advance, by=owner, amount=400, paid_on=day)

        advance.refresh_from_db()
        assert advance.status == Debt.Status.PAID
        assert (offset.account, offset.amount, offset.currency) == (None, D("400.00"), "UZS")
        assert queries.balance(cash) == D("600.00")

    def test_everything_must_belong_to_the_company(
        self, books, owner, customer, day, other_company
    ):
        debt = invoice(books, owner, customer, 100, day)
        with pytest.raises(DomainError, match="same company"):
            services.pay_debt(
                debt,
                by=owner,
                amount=10,
                paid_on=day,
                account=MoneyAccountFactory(company=other_company),
            )
        with pytest.raises(DomainError, match="same company"):
            services.pay_debt(
                debt, by=MembershipFactory(company=other_company), amount=10, paid_on=day
            )

    def test_repeated_sources_return_the_first_payment(
        self, books, owner, customer, cash, day, src
    ):
        debt = invoice(books, owner, customer, 100, day)
        with pytest.raises(ValueError, match="source"):
            services.pay_debt(debt, by=None, amount=10, paid_on=day, account=cash)
        first = services.pay_debt(
            debt, by=None, amount=10, paid_on=day, account=cash, source=src(9, "paid")
        )
        again = services.pay_debt(
            debt, by=None, amount=10, paid_on=day, account=cash, source=src(9, "paid")
        )

        debt.refresh_from_db()
        assert again == first
        assert debt.paid == D("10.00")

    def test_one_source_pays_one_debt(self, books, owner, member, cash, day, src):
        """A payslip pays the salary and each reimbursement: one key each, never one for all."""
        worker = member(books)
        fund(books, owner, cash, 1000, day)
        salary, reimbursement = (
            services.open_debt(
                books,
                by=owner,
                direction="payable",
                kind=kind,
                amount=amount,
                currency="UZS",
                issued_on=day,
                membership=worker,
                category=category,
            )
            for kind, amount, category in (
                ("salary", 500, "salaries"),
                ("reimbursement", 80, "rent"),
            )
        )
        services.pay_debt(
            salary, by=None, amount=500, paid_on=day, account=cash, source=src(4, "paid")
        )

        with pytest.raises(ValueError, match="debt_id"):
            services.pay_debt(
                reimbursement, by=None, amount=80, paid_on=day, account=cash, source=src(4, "paid")
            )
        services.pay_debt(
            reimbursement, by=None, amount=80, paid_on=day, account=cash, source=src(4, "paid:r")
        )
        reimbursement.refresh_from_db()
        assert reimbursement.status == Debt.Status.PAID
        assert queries.balance(cash) == D("420.00")

    def test_a_source_that_opened_a_debt_doesnt_pay_it(self, books, customer, cash, day, src):
        debt = invoice(books, None, customer, 100, day, source=src(6, "issue"))
        with pytest.raises(ValueError, match="kind"):
            services.pay_debt(
                debt, by=None, amount=100, paid_on=day, account=cash, source=src(6, "issue")
            )
        debt.refresh_from_db()
        assert debt.paid == 0


class TestRounding:
    """Each settlement takes the difference of the debt's running totals off it, so a debt split
    any way adds up to the tiyin: its income or expense equals the cash it brought."""

    @pytest.fixture
    def odd_rate(self, day):
        return ExchangeRateFactory(date=day, rate=D("12345.678901"))

    def totals(self, company):
        posted = Transaction.objects.filter(company=company, status="posted")
        pnl = sum(r.base_amount for r in posted if r.kind in Transaction.PNL_KINDS)
        cash = sum(r.base_amount for r in posted if r.account_id is not None)
        return pnl, cash

    def test_three_cent_payments_on_a_three_cent_debt(
        self, books, owner, customer, dollars, odd_rate, day
    ):
        debt = invoice(books, owner, customer, D("0.03"), day, currency="USD")
        for _ in range(3):
            services.pay_debt(debt, by=owner, amount=D("0.01"), paid_on=day, account=dollars)

        [accrual] = rows(debt, kind=K.INCOME)
        assert accrual.base_amount == D("370.37")
        pnl, cash = self.totals(books)
        assert pnl == cash == D("370.38")  # 3 x 123.46 came in; one tiyin is an fx gain
        assert sum(r.base_amount for r in rows(debt, kind=K.FX)) == D("0.01")

    def test_offsets_and_write_offs_take_exactly_the_rest(
        self, books, owner, member, odd_rate, day
    ):
        worker = member(books)
        debt = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="salary",
            amount=D("0.03"),
            currency="USD",
            issued_on=day,
            membership=worker,
            category="salaries",
        )
        offsets = [services.pay_debt(debt, by=owner, amount=D("0.01"), paid_on=day) for _ in "ab"]
        services.write_off(debt, by=owner, reason="Forgiven")

        assert [o.base_amount for o in offsets] == [D("-123.46"), D("-123.45")]
        [accrual] = rows(debt, kind=K.EXPENSE)
        [written_off] = rows(debt, kind=K.WRITE_OFF)
        assert written_off.base_amount == D("123.46")
        assert accrual.base_amount + written_off.base_amount == D("-246.91")
        assert sum(o.base_amount for o in offsets) == D("-246.91")
        assert rows(debt, kind=K.FX) == []


class TestExchangeDifferences:
    def test_a_dollar_debt_paid_in_som_books_the_difference(
        self, books, owner, customer, cash, later, day
    ):
        debt = invoice(books, owner, customer, 100, day, currency="USD")  # 1 280 000 so'm
        payment = services.pay_debt(debt, by=owner, amount=1_300_000, paid_on=later, account=cash)

        debt.refresh_from_db()
        assert debt.status == Debt.Status.PAID
        assert (payment.currency, payment.amount, payment.debt_amount) == (
            "UZS",
            D("1300000.00"),
            D("100.00"),
        )
        [fx] = rows(debt, kind=K.FX)
        assert (fx.amount, fx.base_amount, fx.currency, fx.account) == (
            D("20000.00"),
            D("20000.00"),
            "UZS",
            None,
        )
        assert fx.category.system_code == "fx_diff"
        assert (fx.source_type, fx.source_id, fx.source_key) == (
            "finance.transaction",
            payment.pk,
            "fx",
        )
        # Profit over the debt's life equals the cash it brought.
        pnl = sum(r.base_amount for r in rows(debt) if r.kind in Transaction.PNL_KINDS)
        assert pnl == D("1300000.00")

    def test_paying_at_the_debts_own_value_books_nothing(
        self, books, owner, customer, cash, usd, day
    ):
        debt = invoice(books, owner, customer, 100, day, currency="USD")
        services.pay_debt(debt, by=owner, amount=640_000, debt_amount=50, paid_on=day, account=cash)

        debt.refresh_from_db()
        assert debt.paid == D("50.00")
        assert rows(debt, kind=K.FX) == []

    def test_a_som_debt_paid_in_dollars(self, books, owner, customer, dollars, usd, day):
        debt = invoice(books, owner, customer, 1_300_000, day)
        payment = services.pay_debt(
            debt, by=owner, amount=100, debt_amount=1_300_000, paid_on=day, account=dollars
        )

        assert (payment.currency, payment.base_amount) == ("USD", D("1280000.00"))
        [fx] = rows(debt, kind=K.FX)
        assert fx.base_amount == D("-20000.00")  # we took $100 for 1.3 million: a loss
        assert queries.balance(dollars) == D("100.00")

    def test_the_debt_share_follows_the_rate_of_the_day(
        self, books, owner, customer, dollars, usd, day
    ):
        debt = invoice(books, owner, customer, 1_280_000, day)
        payment = services.pay_debt(debt, by=owner, amount=50, paid_on=day, account=dollars)

        assert payment.debt_amount == D("640000.00")
        assert rows(debt, kind=K.FX) == []

    def test_a_dollar_payable_paid_later_in_dollars_books_the_loss(
        self, books, owner, supplier, dollars, later, day
    ):
        fund(books, owner, dollars, 500, day)
        bill = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="bill",
            amount=100,
            currency="USD",
            issued_on=day,
            counterparty=supplier,
            category="goods",
        )
        payment = services.pay_debt(bill, by=owner, amount=100, paid_on=later, account=dollars)

        assert payment.base_amount == D("-1300000.00")
        [fx] = rows(bill, kind=K.FX)
        assert fx.base_amount == D("-20000.00")
        assert queries.balance(dollars) == D("400.00")

    def test_voiding_the_payment_voids_its_difference_and_reopens_the_debt(
        self, books, owner, customer, cash, later, day
    ):
        debt = invoice(books, owner, customer, 100, day, currency="USD")
        payment = services.pay_debt(debt, by=owner, amount=1_300_000, paid_on=later, account=cash)

        services.void_transaction(payment, by=owner, reason="Bounced")

        debt.refresh_from_db()
        assert (debt.status, debt.paid) == (Debt.Status.OPEN, 0)
        assert {r.status for r in rows(debt, kind__in=[K.FX, K.DEBT_PAYMENT])} == {"void"}
        assert queries.balance(cash) == 0
        [fx] = rows(debt, kind=K.FX)
        with pytest.raises(DomainError, match="void"):
            services.void_transaction(fx, by=owner, reason="x")


class TestLocks:
    def test_a_locked_debt_takes_payments_only_from_its_source(
        self, books, owner, member, cash, day, src
    ):
        worker = member(books)
        claim = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="reimbursement",
            amount=100,
            currency="UZS",
            issued_on=day,
            membership=worker,
            category="transport",
        )
        fund(books, owner, cash, 1000, day)
        payslip = src(5, "lock")
        services.lock_debt(claim, source=payslip)
        services.lock_debt(claim, source=src(5, "again"))  # same record: nothing changes

        claim.refresh_from_db()
        assert (claim.locked_by_type, claim.locked_by_id) == ("finance.test", 5)
        with pytest.raises(DomainError, match="reserved by Test #5"):
            services.pay_debt(claim, by=owner, amount=100, paid_on=day, account=cash)
        with pytest.raises(DomainError, match="reserved"):
            services.pay_debt(claim, by=None, amount=100, paid_on=day, account=cash, source=src(6))
        with pytest.raises(DomainError, match="reserved"):
            services.write_off(claim, by=owner, reason="x")
        with pytest.raises(DomainError, match="reserved"):
            services.cancel_debt(claim, by=owner, reason="x")
        with pytest.raises(DomainError, match="reserved"):
            services.lock_debt(claim, source=src(6))
        with pytest.raises(DomainError, match="reserved"):
            services.unlock_debt(claim, source=src(6))

        paid = services.pay_debt(
            claim, by=None, amount=100, paid_on=day, account=cash, source=src(5, "paid")
        )
        assert paid.amount == D("-100.00")

    def test_unlocking_lets_anyone_pay_again(self, books, owner, customer, cash, day, src):
        debt = invoice(books, owner, customer, 100, day)
        services.lock_debt(debt, source=src(5))
        services.unlock_debt(debt, source=src(5))
        services.unlock_debt(debt, source=src(5))  # nobody holds it: nothing changes

        services.pay_debt(debt, by=owner, amount=100, paid_on=day, account=cash)

        debt.refresh_from_db()
        assert debt.status == Debt.Status.PAID
        with pytest.raises(DomainError, match="settled"):
            services.lock_debt(debt, source=src(5))

    def test_a_lock_needs_a_registered_source(self, books, owner, customer, day):
        debt = invoice(books, owner, customer, 100, day)
        with pytest.raises(ValueError):
            services.lock_debt(debt, source=None)
        with pytest.raises(ValueError):
            services.lock_debt(debt, source=("payroll.payslip", 1, ""))


class TestWriteOff:
    def test_a_receivable_becomes_a_bad_debt(self, books, owner, customer, day):
        debt = invoice(books, owner, customer, 1000, day)
        part = services.write_off(debt, by=owner, reason="Shop closed", amount=300)

        debt.refresh_from_db()
        assert (part.kind, part.amount, part.category.system_code) == (
            K.WRITE_OFF,
            D("-300.00"),
            "bad_debts",
        )
        assert part.description == "Shop closed"
        assert (debt.paid, debt.status) == (D("300.00"), Debt.Status.OPEN)

        services.write_off(debt, by=owner, reason="Gone")
        debt.refresh_from_db()
        assert debt.status == Debt.Status.WRITTEN_OFF
        assert sum(r.base_amount for r in rows(debt)) == 0

    def test_a_payable_nobody_collects_becomes_other_income(self, books, owner, supplier, usd, day):
        bill = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="bill",
            amount=10,
            currency="USD",
            issued_on=day,
            counterparty=supplier,
            category="goods",
        )
        row = services.write_off(bill, by=owner, reason="Supplier gone")

        assert (row.amount, row.base_amount) == (D("10.00"), D("128000.00"))
        assert row.category.system_code == "other_income"

    def test_write_off_rules(self, books, owner, customer, day):
        debt = invoice(books, owner, customer, 100, day)
        with pytest.raises(DomainError, match="more than"):
            services.write_off(debt, by=owner, reason="x", amount=101)
        with pytest.raises(DomainError, match="why"):
            services.write_off(debt, by=owner, reason="")
        with pytest.raises(ValueError):
            services.write_off(debt, by=None, reason="x")
        tomorrow = timezone.localdate(timezone=ZoneInfo(books.timezone)) + timedelta(days=1)
        future = invoice(books, owner, customer, 100, tomorrow)
        with pytest.raises(DomainError, match="before the day it was issued"):
            services.write_off(future, by=owner, reason="x")

    def test_voiding_a_write_off_reopens_the_debt(self, books, owner, customer, day):
        debt = invoice(books, owner, customer, 100, day)
        row = services.write_off(debt, by=owner, reason="x")
        services.void_transaction(row, by=owner, reason="They paid after all")

        debt.refresh_from_db()
        assert (debt.status, debt.paid) == (Debt.Status.OPEN, 0)


class TestCancel:
    def test_cancelling_voids_every_row_and_moves_money_back(
        self, books, owner, customer, cash, later, day, src
    ):
        debt = invoice(books, owner, customer, 100, day, currency="USD", source=src(3, "issue"))
        services.pay_debt(debt, by=owner, amount=650_000, paid_on=later, account=cash)
        assert queries.balance(cash) == D("650000.00")

        services.cancel_debt(debt, by=owner, reason="Wrong customer")

        debt.refresh_from_db()
        assert (debt.status, debt.paid) == (Debt.Status.CANCELLED, 0)
        assert {r.status for r in rows(debt)} == {"void"}
        assert len(rows(debt)) == 3  # accrual, payment, exchange difference
        assert queries.balance(cash) == 0
        with pytest.raises(DomainError, match="already cancelled"):
            services.cancel_debt(debt, by=owner, reason="Again")
        # The source is free again.
        assert (
            invoice(books, None, customer, 100, day, currency="USD", source=src(3, "issue")) != debt
        )

    def test_rows_that_opened_a_debt_go_with_the_debt(self, books, owner, customer, cash, day):
        debt = invoice(books, owner, customer, 100, day)
        fund(books, owner, cash, 100, day)
        loan = services.open_debt(
            books,
            by=owner,
            direction="receivable",
            kind="loan",
            amount=50,
            currency="UZS",
            issued_on=day,
            counterparty=customer,
            account=cash,
        )
        for row in (*rows(debt), *rows(loan)):
            with pytest.raises(DomainError, match="cancel the debt"):
                services.void_transaction(row, by=owner, reason="x")

    def test_not_in_a_closed_period(self, books, owner, customer, day):
        debt = invoice(books, owner, customer, 100, day)
        settings = conf.get_settings(books)
        settings.locked_until = day
        settings.save()
        with pytest.raises(DomainError, match="closed"):
            services.cancel_debt(debt, by=owner, reason="x")


class TestOpenDebts:
    def test_open_debts_soonest_due_first_with_what_is_left(
        self, books, owner, member, customer, supplier, cash, day
    ):
        worker = member(books)
        later = invoice(books, owner, customer, 100, day, due_on=day + timedelta(days=9))
        sooner = invoice(books, owner, customer, 200, day, due_on=day + timedelta(days=2))
        undated = invoice(books, owner, customer, 300, day)
        paid = invoice(books, owner, customer, 50, day)
        services.pay_debt(paid, by=owner, amount=50, paid_on=day, account=cash)
        services.pay_debt(sooner, by=owner, amount=20, paid_on=day, account=cash)
        bill = services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="salary",
            amount=70,
            currency="UZS",
            issued_on=day,
            membership=worker,
            category="salaries",
        )

        found = list(queries.open_debts(books))
        assert found == [sooner, later, undated, bill]
        assert found[0].outstanding == D("180.00")
        assert list(queries.open_debts(books, direction="payable")) == [bill]
        assert list(queries.open_debts(books, membership=worker, kind="salary")) == [bill]
        assert list(queries.open_debts(books, counterparty=supplier)) == []
        assert list(queries.open_debts(books, counterparty=customer)) == [sooner, later, undated]

    def test_salary_debts_are_audited_for_payroll_eyes_only(self, books, owner, member, day):
        services.open_debt(
            books,
            by=owner,
            direction="payable",
            kind="salary",
            amount=70,
            currency="UZS",
            issued_on=day,
            membership=member(books),
            category="salaries",
        )
        log = AuditLog.objects.get(action="finance.debt_opened")
        assert log.required_perm == "payroll.view"
