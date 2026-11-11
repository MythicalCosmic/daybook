"""Loans and instalments (v12, `apps.finance.loans`): the schedule stored as instalments, a payment
split into principal (no expense) and interest (an expense linked to the loan), early repayment,
the forecast, the statements and the morning reminders."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

import pytest

from apps.core.exceptions import DomainError
from apps.finance import loan_math, loans, planning, queries, services, statements
from apps.finance.models import Debt, DebtInstallment, Loan, Transaction
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db

START = date(2026, 1, 10)


def fresh(loan: Loan) -> Loan:
    return Loan.objects.select_related("debt").get(pk=loan.pk)


@pytest.fixture
def lender(books):
    return CounterpartyFactory(company=books, name="Ipoteka bank", kind="other")


@pytest.fixture
def money(books, owner):
    """A bank account with 50 mln so‘m on it, so payments never run it dry."""
    account = MoneyAccountFactory(company=books, name="Bank", kind="bank")
    services.record_transaction(
        books,
        by=owner,
        kind="opening",
        amount=D(50_000_000),
        occurred_on=START - timedelta(days=1),
        account=account,
    )
    return account


@pytest.fixture
def loan(books, owner, lender, money):
    """12 000 000 so‘m taken on 10 January at 24 %, equal principal over 12 months from 10
    February: 1 000 000 a month, interest 240 000 falling by 20 000."""
    return loans.create(
        books,
        by=owner,
        direction=Debt.Direction.PAYABLE,
        counterparty=lender,
        amount=D(12_000_000),
        currency="UZS",
        issued_on=START,
        annual_rate=D(24),
        method=Loan.Method.EQUAL_PRINCIPAL,
        term_months=12,
        first_due_on=date(2026, 2, 10),
        account=money,
        fee=D(120_000),
    )


def test_the_schedule_is_the_debts_instalments(loan):
    debt = loan.debt
    assert debt.kind == Debt.Kind.LOAN and debt.amount == D(12_000_000)
    rows = list(DebtInstallment.objects.filter(debt=debt))
    assert len(rows) == 12
    assert sum(row.amount for row in rows) == debt.amount
    assert rows[0].interest == D(240_000) and rows[-1].interest == D(20_000)
    assert debt.due_on == date(2027, 1, 10)
    # The money arrived on the account, and the fee was booked as a bank fee linked to the loan.
    fee = Transaction.objects.get(source_type=loans.SOURCE, source_key="fee")
    assert fee.amount == D(-120_000) and fee.debt_id == debt.pk
    assert fee.category.system_code == "bank_fees"


def test_paying_an_instalment_splits_principal_and_interest(books, owner, loan, money):
    first = loan.debt.installments.order_by("due_on").first()
    rows = loans.pay(first, by=owner, account=money, paid_on=date(2026, 2, 10))
    principal, interest = rows
    assert principal.kind == Transaction.Kind.DEBT_PAYMENT and principal.amount == D(-1_000_000)
    assert interest.kind == Transaction.Kind.EXPENSE and interest.amount == D(-240_000)
    assert interest.debt_id == loan.debt_id
    assert interest.category.system_code == "loan_interest"
    loan.debt.refresh_from_db()
    assert loan.debt.paid == D(1_000_000)
    # The P&L shows the interest (and the fee), never the principal.
    pnl = queries.totals(books, date(2026, 2, 1), date(2026, 2, 28), branch_ids=None)
    assert pnl["expense"] == D(240_000)
    lines = loans.lines(fresh(loan), date(2026, 2, 11))
    assert lines[0]["status"] == "paid" and lines[0]["balance"] == D(11_000_000)
    assert lines[1]["status"] == "due"
    # Paying the same instalment again: nothing left.
    with pytest.raises(DomainError):
        loans.pay(first, by=owner, account=money, paid_on=date(2026, 2, 10))


def test_part_payments_of_one_instalment(owner, loan, money):
    first = loan.debt.installments.order_by("due_on").first()
    loans.pay(first, by=owner, account=money, paid_on=date(2026, 2, 10), principal=D(400_000))
    row = loans.lines(fresh(loan), date(2026, 2, 10))[0]
    assert row["status"] == "partial"
    assert row["interest_paid"] == D(240_000) and row["principal_paid"] == D(400_000)
    loans.pay(first, by=owner, account=money, paid_on=date(2026, 2, 11))
    row = loans.lines(fresh(loan), date(2026, 2, 12))[0]
    assert row["status"] == "paid"
    # More principal than the payment holds is an early repayment instead.
    second = loan.debt.installments.order_by("due_on")[1]
    with pytest.raises(DomainError):
        loans.pay(second, by=owner, account=money, paid_on=date(2026, 3, 1), principal=D(2_000_000))


def test_late_instalment_is_overdue(books, loan):
    rows = loans.overdue(books, date(2026, 2, 20))
    assert len(rows) == 1 and rows[0]["days"] == 10
    assert rows[0]["line"]["rest"] == D(1_240_000)


def test_early_repayment_with_smaller_payments(books, owner, loan, money):
    for row in list(loan.debt.installments.order_by("due_on"))[:2]:
        loans.pay(row, by=owner, account=money, paid_on=row.due_on)
    loans.repay_early(
        loan,
        by=owner,
        account=money,
        paid_on=date(2026, 3, 20),
        amount=D(5_000_000),
        interest=D(30_000),
    )
    loan.debt.refresh_from_db()
    rows = list(loan.debt.installments.order_by("due_on", "position"))
    # Two paid, the early repayment, and the ten left spread over 5 000 000.
    assert sum(row.amount for row in rows) == loan.debt.amount
    early = [row for row in rows if row.early]
    assert len(early) == 1 and early[0].amount == D(5_000_000) and early[0].interest == D(30_000)
    left = [row for row in rows if row.due_on > date(2026, 3, 20)]
    assert len(left) == 10
    assert left[0].amount == D(500_000) and left[0].interest == D(100_000)
    lines = loans.lines(fresh(loan), date(2026, 3, 21))
    assert [line["status"] for line in lines[:3]] == ["paid", "paid", "paid"]
    assert lines[-1]["balance"] == 0
    assert loan.debt.paid == D(7_000_000)


def test_early_repayment_with_a_shorter_term(owner, loan, money):
    first = loan.debt.installments.order_by("due_on").first()
    loans.pay(first, by=owner, account=money, paid_on=first.due_on)
    loans.repay_early(
        loan,
        by=owner,
        account=money,
        paid_on=date(2026, 2, 20),
        amount=D(5_000_000),
        mode=loan_math.REDUCE_TERM,
    )
    left = loan.debt.installments.filter(due_on__gt=date(2026, 2, 20), early=False)
    # 6 000 000 left at the same 1 000 000 a month: six payments instead of eleven.
    assert left.count() == 6
    assert {row.amount for row in left} == {D(1_000_000)}


def test_early_repayment_of_everything_settles_the_loan(owner, loan, money):
    loans.repay_early(
        loan, by=owner, account=money, paid_on=date(2026, 1, 20), amount=D(12_000_000)
    )
    loan.debt.refresh_from_db()
    assert loan.debt.status == Debt.Status.PAID
    assert loan.debt.installments.count() == 1  # only the early repayment is left


def test_early_repayment_needs_the_due_payments_paid(owner, loan, money):
    with pytest.raises(DomainError):
        loans.repay_early(
            loan, by=owner, account=money, paid_on=date(2026, 3, 1), amount=D(1_000_000)
        )


def test_schedule_changes_only_before_the_first_payment(owner, loan, money):
    loans.replace_schedule(loan, by=owner, method=Loan.Method.ANNUITY, term_months=6)
    loan.refresh_from_db()
    assert loan.method == Loan.Method.ANNUITY
    assert loan.debt.installments.count() == 6
    first = loan.debt.installments.order_by("due_on").first()
    loans.pay(first, by=owner, account=money, paid_on=first.due_on)
    with pytest.raises(DomainError):
        loans.replace_schedule(loan, by=owner, term_months=12)


def test_a_typed_schedule(books, owner, lender, money):
    rows = [
        loan_math.Row(date(2026, 2, 10), D(4_000_000), D(150_000)),
        loan_math.Row(date(2026, 3, 10), D(6_000_000), D(80_000)),
    ]
    made = loans.create(
        books,
        by=owner,
        direction="payable",
        counterparty=lender,
        amount=D(10_000_000),
        currency="UZS",
        issued_on=START,
        annual_rate=D(20),
        method=Loan.Method.CUSTOM,
        term_months=2,
        first_due_on=date(2026, 2, 10),
        account=money,
        rows=rows,
    )
    assert [row.interest for row in made.debt.installments.order_by("due_on")] == [
        D(150_000),
        D(80_000),
    ]
    with pytest.raises(DomainError):
        loans.create(
            books,
            by=owner,
            direction="payable",
            counterparty=lender,
            amount=D(11_000_000),
            currency="UZS",
            issued_on=START,
            annual_rate=D(20),
            method=Loan.Method.CUSTOM,
            term_months=2,
            first_due_on=date(2026, 2, 10),
            account=money,
            rows=rows,
        )


def test_a_loan_from_before_the_books(books, owner, lender):
    made = loans.create(
        books,
        by=owner,
        direction="payable",
        counterparty=lender,
        amount=D(6_000_000),
        currency="UZS",
        issued_on=START,
        annual_rate=D(22),
        method=Loan.Method.ANNUITY,
        term_months=6,
        first_due_on=date(2026, 2, 5),
    )
    assert made.debt.is_opening
    assert not Transaction.objects.filter(debt=made.debt, kind="debt_open").exists()


def test_a_loan_given_earns_interest(books, owner, money):
    borrower = CounterpartyFactory(company=books, name="Hamkor MChJ")
    made = loans.create(
        books,
        by=owner,
        direction="receivable",
        counterparty=borrower,
        amount=D(3_000_000),
        currency="UZS",
        issued_on=START,
        annual_rate=D(12),
        method=Loan.Method.EQUAL_PRINCIPAL,
        term_months=3,
        first_due_on=date(2026, 2, 10),
        account=money,
    )
    first = made.debt.installments.order_by("due_on").first()
    principal, interest = loans.pay(first, by=owner, account=money, paid_on=first.due_on)
    assert principal.amount == D(1_000_000) and interest.amount == D(30_000)
    assert interest.category.system_code == "interest_income"


def test_the_account_must_hold_the_loans_currency(books, owner, loan):
    dollars = MoneyAccountFactory(company=books, name="USD", kind="safe", currency="USD")
    first = loan.debt.installments.first()
    with pytest.raises(DomainError):
        loans.pay(first, by=owner, account=dollars, paid_on=first.due_on)


def test_undo_a_payment(owner, loan, money):
    first = loan.debt.installments.order_by("due_on").first()
    principal, _interest = loans.pay(first, by=owner, account=money, paid_on=first.due_on)
    loans.undo_payment(loan, principal, by=owner, reason="Wrong day")
    loan.debt.refresh_from_db()
    assert loan.debt.paid == 0
    assert loans.lines(fresh(loan), date(2026, 2, 1))[0]["status"] == "due"
    # Paid again, it takes the next numbers.
    rows = loans.pay(first, by=owner, account=money, paid_on=first.due_on)
    assert rows[0].source_key.endswith(":p2")


def test_the_forecast_counts_each_instalment_with_its_interest(books, loan):
    today = date(2026, 1, 20)
    found = [
        item
        for item in planning.items(books, today, today + timedelta(days=90), branch_ids=None)
        if item.debt_id == loan.debt_id
    ]
    # 10 February, 10 March, 10 April: principal and interest, not the whole loan at the end.
    assert [item.date for item in found] == [
        date(2026, 2, 10),
        date(2026, 3, 10),
        date(2026, 4, 10),
    ]
    assert [item.amount for item in found] == [D(1_240_000), D(1_220_000), D(1_200_000)]
    assert all(item.kind == "payable" and item.url.endswith(f"/loans/{loan.pk}") for item in found)


def test_statements_read_the_interest_as_the_loans(books, owner, loan, money):
    first = loan.debt.installments.order_by("due_on").first()
    loans.pay(first, by=owner, account=money, paid_on=first.due_on)
    found = statements.earnings(books, date(2026, 3, 1))
    interest = next(line for line in found["lines"] if line["key"] == "interest")
    # The payment's interest and the loan's fee: both are what the loan costs.
    assert interest["amount"] == D(240_000) + D(120_000)


def _morning(company, day: date, hour: int = 9) -> datetime:
    return datetime.combine(day, time(hour, 5), tzinfo=ZoneInfo(company.timezone))


def test_reminders_before_the_payment_at_the_morning_hour(books, owner, loan):
    from apps.finance import deadline_reminders

    books.morning_report_at = time(9, 0)
    books.save(update_fields=["morning_report_at"])

    def sent(day: date, hour: int = 9) -> int:
        before = Notification.objects.filter(kind=loans.NOTIFICATION).count()
        deadline_reminders.remind(books, _morning(books, day, hour))
        return Notification.objects.filter(kind=loans.NOTIFICATION).count() - before

    # Three days before 10 February, at the morning hour, not before it.
    assert sent(date(2026, 2, 7), hour=7) == 0
    assert sent(date(2026, 2, 7)) == 1
    note = Notification.objects.get(kind=loans.NOTIFICATION)
    assert "Ipoteka bank" in note.title
    assert note.url.endswith(f"/finance/loans/{loan.pk}")
    # Once a day only, and nothing the day after.
    assert sent(date(2026, 2, 7), hour=10) == 0
    assert sent(date(2026, 2, 8)) == 0
    # On the day, the day after when it is late, then weekly.
    assert sent(date(2026, 2, 10)) == 1
    assert sent(date(2026, 2, 11)) == 1
    assert sent(date(2026, 2, 12)) == 0
    assert sent(date(2026, 2, 18)) == 1


def test_paid_from_the_reminder(books, owner, loan, money):
    from apps.finance import deadline_reminders

    books.morning_report_at = time(9, 0)
    books.save(update_fields=["morning_report_at"])
    deadline_reminders.remind(books, _morning(books, date(2026, 2, 7)))
    note = Notification.objects.get(kind=loans.NOTIFICATION, recipient=owner)
    message = loans.paid_action(note, owner, "")
    assert "Bank" in message
    loan.debt.refresh_from_db()
    assert loan.debt.paid == D(1_000_000)
    assert loans.paid_action(note, owner, "") == "Already paid."


def test_egasi_paneli_hears_of_a_late_payment(books, owner, loan):
    from apps.insights import engine
    from apps.insights.models import Insight

    books.features = ["finance"]
    books.save(update_fields=["features"])
    late = datetime.combine(date(2026, 2, 15), time(12), tzinfo=ZoneInfo(books.timezone))
    engine.run(books, late, notify=False)
    insight = Insight.objects.get(company=books, kind=Insight.Kind.LOAN_OVERDUE)
    assert insight.severity == Insight.Severity.WARNING
    assert insight.metrics["value"] == "1240000.00" and insight.metrics["oldest_days"] == 5
    assert "Ipoteka bank" in insight.explanation
    # Paid: the next run resolves it.
    first = loan.debt.installments.order_by("due_on").first()
    loans.pay(first, by=owner, account=loan.account, paid_on=date(2026, 2, 15))
    engine.run(books, late, notify=False)
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED
