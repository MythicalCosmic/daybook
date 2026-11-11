"""The owner's monthly draw suggestion before and after the cash forecast learned payroll's pay
days: for the same data it comes out the same (v12)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.console import registry
from apps.console.registry import CompanyFactsProvider
from apps.finance import owner_draw, services
from apps.finance.models import MoneyAccount
from apps.finance.tests.factories import CounterpartyFactory, MoneyAccountFactory

pytestmark = pytest.mark.django_db
D = Decimal
# A fixed day, so the draws (the 1st of each coming month) and the pay days fall alike on every run.
TODAY = date(2026, 10, 7)


@pytest.fixture
def boss(fin, member):
    return member(fin, "Owner", first_name="Dilnoza")


@pytest.fixture
def today(fin):
    return TODAY


@pytest.fixture
def bank(fin):
    return MoneyAccountFactory(company=fin, name="Bank", kind=MoneyAccount.Kind.BANK)


@pytest.fixture
def payroll_says(fin, isolated_registries):
    """`payroll_says(day, amount)`: payroll's own figure for its next pay day (and the same
    again on the months after it)."""
    fin.features = ["finance", "payroll"]
    fin.save(update_fields=["features"])

    def say(day, amount):
        registry.COMPANY_FACTS._entries.pop("payroll", None)
        registry.COMPANY_FACTS.add(
            CompanyFactsProvider(
                "payroll",
                None,
                None,
                None,
                lambda company, range_, member: {
                    "next_run_on": day.isoformat(),
                    "next_run_amount": amount,
                },
            )
        )

    return say


def opening(company, by, account, amount, day):
    services.record_transaction(
        company, by=by, kind="opening", amount=D(amount), occurred_on=day, account=account
    )


def salary(company, by, amount, day):
    """Pay booked for the team (a finalized payslip): owed now, without a due day."""
    services.open_debt(
        company,
        by=by,
        direction="payable",
        kind="salary",
        amount=amount,
        currency="UZS",
        issued_on=day,
        membership=by,
        category="salaries",
    )


def outcome(data: dict) -> tuple:
    return (data["monthly"], data["low"]["date"], data["low"]["balance"], data["below_buffer_on"])


# The same data, the same suggestion ------------------------------------------------------------


def test_payroll_only_estimated(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")
    payroll_says(today + timedelta(days=12), "20000000.00")

    data = owner_draw.suggested_monthly(fin, today)

    assert outcome(data) == GOLDEN["estimated"](today)


def test_payroll_booked_above_its_figure(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")
    payroll_says(today + timedelta(days=12), "20000000.00")
    salary(fin, boss, "25000000", today - timedelta(days=3))

    data = owner_draw.suggested_monthly(fin, today)

    assert outcome(data) == GOLDEN["booked"](today)


def test_payroll_with_spending_debts_and_the_owners_own_money(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "300000000", today - timedelta(days=60))
    for back in (50, 35, 20, 5):
        services.record_transaction(
            fin,
            by=boss,
            kind="expense",
            amount=D("4000000"),
            occurred_on=today - timedelta(days=back),
            account=bank,
            category="rent",
        )
    services.open_debt(
        fin,
        by=boss,
        direction="payable",
        kind="trade",
        amount="30000000",
        currency="UZS",
        issued_on=today - timedelta(days=2),
        due_on=today + timedelta(days=40),
        counterparty=CounterpartyFactory(company=fin, name="Grand Farm"),
        category="goods",
    )
    mine = services.account_for_holder(fin, boss, kind="owner")
    opening(fin, boss, mine, "7000000", today - timedelta(days=1))
    payroll_says(today + timedelta(days=3), "40000000.00")

    data = owner_draw.suggested_monthly(fin, today)

    assert outcome(data) == GOLDEN["mixed"](today)


def test_payroll_off(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")
    payroll_says(today + timedelta(days=12), "20000000.00")
    fin.features = ["finance"]
    fin.save(update_fields=["features"])

    data = owner_draw.suggested_monthly(fin, today)

    assert outcome(data) == GOLDEN["off"](today)


def test_payroll_too_much_for_the_cash(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "50000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")
    payroll_says(today + timedelta(days=12), "45000000.00")

    data = owner_draw.suggested_monthly(fin, today)

    assert outcome(data) == GOLDEN["short"](today)


def test_payroll_booked_below_its_figure(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    owner_draw.update_settings(fin, by=boss, cash_buffer="10000000")
    payroll_says(today + timedelta(days=12), "20000000.00")
    salary(fin, boss, "8000000", today - timedelta(days=3))

    data = owner_draw.suggested_monthly(fin, today)

    assert outcome(data) == GOLDEN["below"](today)


def _golden(monthly, low_in, low, below_in=None):
    return lambda today: (
        D(monthly),
        today + timedelta(days=low_in),
        D(low),
        today + timedelta(days=below_in) if below_in is not None else None,
    )


# What `suggested_monthly` gave for each case before the forecast counted payroll (ebd0481b).
GOLDEN = {
    "estimated": _golden("10000000.00", 86, "10000000.00"),
    "booked": _golden("8300000.00", 86, "10100000.00"),
    "mixed": _golden("32400000.00", 90, "8000000.00"),
    "off": _golden("30000000.00", 86, "10000000.00"),
    "short": _golden("0", 73, "-85000000.00", 12),
    "below": _golden("7300000.00", 86, "10100000.00"),
}
