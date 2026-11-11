"""The owner's monthly draw suggestion before and after the cash forecast learned payroll's pay
days (v12): for the same data it comes out the same, except that pay booked below payroll's
figure for the next pay day no longer counts on top of it."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.finance import owner_draw, planning, services
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
def payroll_says(fin, payroll_pays):
    """`payroll_says(day, amount)`: payroll's own figure for its next pay day (and the same
    again on the months after it)."""
    fin.features = ["finance", "payroll"]
    fin.save(update_fields=["features"])
    return lambda day, amount: payroll_pays(day, amount)


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

    # The one change: before, the 8 mln booked and payroll's 20 mln for the same pay day both
    # counted. Now the larger stands, as "safe to take" always counted it: 100 - 20 - 20 - 20
    # leaves 40, three draws of 10 keep the 10 mln buffer.
    assert GOLDEN["below"](today)[0] == D("7300000.00")
    assert outcome(data) == GOLDEN["estimated"](today)


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


# The cash plan counts payroll's pay days -----------------------------------------------------


def estimates(company, today, days, *, branch_ids=None) -> list[dict]:
    rows = planning.upcoming(company, days, branch_ids=branch_ids, today=today)["items"]
    return [row for row in rows if row["kind"] == "payroll" and row["estimate"]]


def test_a_pay_day_inside_the_horizon_is_an_estimate(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    pay_day = today + timedelta(days=18)
    payroll_says(pay_day, "40000000.00")

    [row] = estimates(fin, today, 30)

    assert row == {
        "key": f"payroll:{pay_day.isoformat()}:estimate",
        "kind": "payroll",
        "title": "Payroll (estimate)",
        "subtitle": "Pay day",
        "date": pay_day.isoformat(),
        "amount": "40000000.00",
        "currency": "UZS",
        "direction": "out",
        "overdue": False,
        "estimate": True,
        "rule_id": None,
        "debt_id": None,
        "url": f"/c/{fin.pk}/payroll",
    }
    plan = planning.forecast(fin, 30, branch_ids=None, today=today)
    point = next(point for point in plan["points"] if point["date"] == pay_day.isoformat())
    assert point["out"] == "40000000.00"
    assert plan["end"] == "60000000.00"
    assert {
        "date": pay_day.isoformat(),
        "title": "Payroll (estimate)",
        "amount": "40000000.00",
        "direction": "out",
    } in plan["events"]
    # Outside the horizon it isn't counted; the next month's pay day comes into a longer one.
    assert estimates(fin, today, 17) == []
    assert planning.forecast(fin, 17, branch_ids=None, today=today)["end"] == "100000000.00"
    assert [row["date"] for row in estimates(fin, today, 60)] == [
        pay_day.isoformat(),
        owner_draw._add_months(pay_day, 1).isoformat(),
    ]


def test_pay_booked_as_much_as_payrolls_figure_stands_for_the_next_pay_day(
    fin, boss, bank, today, payroll_says
):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    pay_day = today + timedelta(days=18)
    payroll_says(pay_day, "40000000.00")
    salary(fin, boss, "45000000", today - timedelta(days=3))

    rows = [
        row
        for row in planning.upcoming(fin, 60, branch_ids=None, today=today)["items"]
        if row["kind"] == "payroll"
    ]

    # The booked pay (owed now) and the month after it; never both for the next pay day.
    assert [(row["date"], row["amount"], row["estimate"]) for row in rows] == [
        (today.isoformat(), "45000000.00", False),
        (owner_draw._add_months(pay_day, 1).isoformat(), "40000000.00", True),
    ]
    assert planning.forecast(fin, 30, branch_ids=None, today=today)["end"] == "55000000.00"


def test_pay_booked_below_payrolls_figure_is_topped_up_to_it(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    payroll_says(today + timedelta(days=18), "40000000.00")
    salary(fin, boss, "15000000", today - timedelta(days=3))

    [row] = estimates(fin, today, 30)

    assert (row["amount"], row["subtitle"]) == ("25000000.00", "Beyond the pay already booked")
    # 15 booked and 25 more on the pay day: payroll's 40, not 55.
    assert planning.forecast(fin, 30, branch_ids=None, today=today)["end"] == "60000000.00"
    reasons = owner_draw.safe_amount(fin, today, horizon_days=30)["reasons"]
    payroll = [(r["title"], r["amount"], r["estimate"]) for r in reasons if r["kind"] == "payroll"]
    assert sorted(payroll) == [
        ("Pay owed to the team", D("15000000.00"), False),
        ("Payroll", D("25000000.00"), True),
    ]


def test_nothing_while_payroll_is_off_or_cant_say(fin, boss, bank, today, payroll_says):
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    payroll_says(today + timedelta(days=18), "40000000.00")
    fin.features = ["finance"]
    fin.save(update_fields=["features"])

    assert estimates(fin, today, 30) == []

    fin.features = ["finance", "payroll"]
    fin.save(update_fields=["features"])

    def broken(company, today, until, *, branch_ids):
        raise RuntimeError("payroll is down")

    planning._pay_days[:] = [broken]
    assert planning.forecast(fin, 30, branch_ids=None, today=today)["end"] == "100000000.00"
    assert estimates(fin, today, 30) == []


def test_branch_scope_asks_payroll_for_those_branches(fin, boss, bank, today, payroll_says):
    first = fin.branches.order_by("pk").first()
    second = BranchFactory(company=fin, name="Yunusobod")
    opening(fin, boss, bank, "100000000", today - timedelta(days=1))
    calls = payroll_says(
        today + timedelta(days=18),
        lambda branch_ids: "10000000.00" if branch_ids == [second.pk] else "40000000.00",
    )
    services.open_debt(
        fin,
        by=boss,
        direction="payable",
        kind="salary",
        amount="12000000",
        currency="UZS",
        issued_on=today - timedelta(days=3),
        membership=boss,
        category="salaries",
        branch=second,
    )

    mine = estimates(fin, today, 30, branch_ids=[second.pk])
    everyone = estimates(fin, today, 30)
    others = estimates(fin, today, 30, branch_ids=[first.pk])

    # Yunusobod's 12 mln booked covers its own 10 mln; the company's 40 mln is topped up from
    # the 12 booked; the other branch has nothing booked, so its whole figure counts.
    assert mine == []
    assert [row["amount"] for row in everyone] == ["28000000.00"]
    assert [row["amount"] for row in others] == ["40000000.00"]
    assert [second.pk] in calls and None in calls and [first.pk] in calls
