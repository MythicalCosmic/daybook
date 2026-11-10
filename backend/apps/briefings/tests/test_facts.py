"""The facts of a review: every number equals what the modules' own queries say (the P&L, the
cash forecast, the debts), compared only with periods that have data, and only what the
reader may see."""

import sys
import types
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.briefings import facts, periods, scope, signals
from apps.finance import planning
from apps.finance import queries as finance_queries
from apps.finance import services as finance
from apps.finance.tests.factories import CounterpartyFactory

from .conftest import AVERAGE, MONDAY, PREVIOUS, WEEK

pytestmark = pytest.mark.django_db
D = Decimal


def weekly(member):
    return facts.build(
        member.company, periods.latest("weekly", MONDAY), scope.of(member), today=MONDAY
    )


def pnl(company, start, end, branch_ids=None):
    return finance_queries.pnl(company, start, end, "month", branch_ids=branch_ids)


def goods(report) -> Decimal:
    return sum(
        (
            Decimal(node["total"])
            for node in report["expense"]["nodes"]
            if node["system_code"] == "goods"
        ),
        Decimal(0),
    )


def test_the_period_is_last_week_with_the_week_before_and_four_to_average():
    period = periods.latest("weekly", MONDAY)

    assert (period.start, period.end) == WEEK
    assert period.previous == PREVIOUS
    assert period.average == AVERAGE
    assert period.count == 4


def test_revenue_margin_and_profit_are_the_pnl(ledger, people, pharmacy):
    found = weekly(people.owner)["finance"]

    now = pnl(pharmacy, *WEEK)
    before = pnl(pharmacy, *PREVIOUS)
    window = pnl(pharmacy, *AVERAGE)
    assert D(found["revenue"]["value"]) == now["income"]["total"] == D("20000000.00")
    assert D(found["revenue"]["previous"]) == before["income"]["total"]
    assert D(found["revenue"]["average"]) == window["income"]["total"] / 4
    assert D(found["expenses"]["value"]) == now["expense"]["total"]
    assert D(found["profit"]["value"]) == now["profit"]["total"]
    assert D(found["profit"]["previous"]) == before["profit"]["total"]
    gross = now["income"]["total"] - goods(now)
    assert found["gross_profit"]["value"] == f"{gross:.2f}" == "7800000.00"
    assert found["gross_margin"]["value"] == "39.0"
    assert found["gross_margin"]["previous"] == "40.0"
    assert found["gross_margin"]["change_pts"] == "-1.0"
    assert found["revenue"]["change_pct"] == "11.1"
    assert found["compared_periods"] == 4


def test_each_pharmacy_is_its_own_pnl(ledger, people, pharmacy, chilonzor, yunusobod):
    rows = {row["name"]: row for row in weekly(people.owner)["finance"]["branches"]}

    for branch in (chilonzor, yunusobod):
        report = pnl(pharmacy, *WEEK, branch_ids=[branch.pk])
        assert D(rows[branch.name]["revenue"]["value"]) == report["income"]["total"]
        assert D(rows[branch.name]["profit"]["value"]) == report["profit"]["total"]
    assert rows["Yunusobod"]["gross_margin"]["value"] == "30.0"
    assert rows["Yunusobod"]["gross_margin"]["previous"] == "40.0"
    assert rows["Yunusobod"]["url"].endswith(f"&branch={yunusobod.pk}")


def test_cash_and_its_low_point_are_the_forecast(ledger, people, pharmacy):
    cash = weekly(people.owner)["finance"]["cash"]

    plan = planning.forecast(pharmacy, 90, branch_ids=None, today=MONDAY)
    assert cash["now"] == plan["start"]
    assert cash["low_90"] == plan["low"]
    assert cash["below_zero_on"] == plan["below_zero_on"]
    first_month = min(plan["points"][:31], key=lambda point: Decimal(point["balance"]))
    assert cash["low_30"] == {"date": first_month["date"], "balance": first_month["balance"]}


def test_money_running_out_is_the_heaviest_signal(ledger, people, pharmacy):
    party = CounterpartyFactory(company=pharmacy)
    finance.open_debt(
        pharmacy,
        by=people.owner,
        direction="payable",
        kind="trade",
        amount=Decimal(500_000_000),
        currency="UZS",
        issued_on=MONDAY,
        due_on=MONDAY + timedelta(days=10),
        counterparty=party,
        category="goods",
    )

    found = weekly(people.owner)
    cash = found["finance"]["cash"]

    assert Decimal(cash["low_30"]["balance"]) < 0
    assert cash["below_zero_on"] is not None
    assert cash["runway_days"] == (date.fromisoformat(cash["below_zero_on"]) - MONDAY).days
    assert found["signals"][0]["key"] == "cash:low"


def test_an_expense_group_that_jumped_but_not_rent_paid_once_a_month(ledger, people):
    found = weekly(people.owner)
    jumps = {row["name"]: row for row in found["finance"]["expense_jumps"]}

    assert set(jumps) == {"Transport"}
    assert jumps["Transport"]["value"] == "2500000.00"
    assert jumps["Transport"]["average"] == "500000.00"
    assert jumps["Transport"]["vs_average_pct"] == "400.0"
    assert any(signal["kind"] == "expense_jump" for signal in found["signals"])


def test_a_pharmacy_whose_margin_fell_is_a_signal(ledger, people, yunusobod):
    found = signals.by_key(weekly(people.owner))

    margin = found[f"branch:{yunusobod.pk}:margin"]
    assert margin["tone"] == signals.BAD
    assert margin["values"]["change_pts"] == "-10.0"
    assert margin["subject"] == "Yunusobod"


def test_a_weekly_review_leaves_profit_and_payroll_to_the_monthly_one(ledger, people):
    kinds = {signal["kind"] for signal in weekly(people.owner)["signals"]}

    assert not kinds & {"loss", "profit", "branch_loss", "payroll_share"}


def test_only_periods_with_data_are_compared(pharmacy, people, tills):
    """Books started on 2 November: the week before is whole, there are no four weeks."""
    for day in (PREVIOUS[0], WEEK[0]):
        finance.record_transaction(
            pharmacy,
            by=people.owner,
            kind="income",
            amount=Decimal(1_000_000),
            occurred_on=day,
            account=tills.chilonzor,
            category="sales",
        )

    found = weekly(people.owner)["finance"]

    assert found["revenue"]["previous"] == "1000000.00"
    assert found["revenue"]["average"] == "1000000.00"
    assert found["compared_periods"] == 1


def test_a_first_week_has_nothing_to_compare(pharmacy, people, tills):
    finance.record_transaction(
        pharmacy,
        by=people.owner,
        kind="income",
        amount=Decimal(1_000_000),
        occurred_on=WEEK[0] + timedelta(days=1),
        account=tills.chilonzor,
        category="sales",
    )

    found = weekly(people.owner)

    assert found["finance"]["revenue"]["previous"] is None
    assert found["finance"]["revenue"]["average"] is None
    assert not any(signal["key"] == "revenue" for signal in found["signals"])


def test_a_manager_without_finance_sees_no_money_and_only_their_pharmacy(
    ledger, people, pharmacy, yunusobod
):
    found = weekly(people.manager)

    assert "finance" not in found
    assert found["domains"] == ["attendance", "insights", "people", "sales", "stock"]
    assert found["every_branch"] is False
    assert all(
        not signal["key"].startswith(("revenue", "cash", "debts")) for signal in found["signals"]
    )
    assert scope.of(people.manager).key != scope.of(people.owner).key
    assert scope.of(people.manager).branch_ids == [yunusobod.pk]


def test_sales_are_the_daily_sales_of_the_scope(pharmacy, people, till_days):
    mine = weekly(people.manager)["sales"]
    everyone = weekly(people.owner)["sales"]

    assert mine["net"]["value"] == "600000.00" and mine["net"]["previous"] == "500000.00"
    assert mine["receipts"]["value"] == 20
    assert mine["average_receipt"]["value"] == "30000.00"
    assert everyone["net"]["value"] == "1500000.00"


@pytest.fixture
def insights_app(monkeypatch):
    """`insights_app(open_for)`: apps.insights.queries as builder P makes it, with `open_for`."""
    import apps.insights

    def install(open_for):
        module = types.ModuleType("apps.insights.queries")
        module.open_for = open_for
        monkeypatch.setitem(sys.modules, "apps.insights.queries", module)
        monkeypatch.setattr(apps.insights, "queries", module, raising=False)

    return install


def test_open_insights_come_from_the_insights_app_when_it_is_there(
    ledger, people, pharmacy, insights_app
):
    calls = []

    def open_for(company, branch_ids):
        calls.append((company.pk, branch_ids))
        return [
            {"id": 7, "domain": "finance", "severity": "critical", "title": "Cash falls short"},
            {"id": 8, "domain": "sales", "severity": "info", "title": "Quiet Sunday"},
        ]

    insights_app(open_for)

    owner = weekly(people.owner)
    manager = weekly(people.manager)

    assert [row["id"] for row in owner["insights"]] == [7, 8]
    assert [row["id"] for row in manager["insights"]] == [8]
    assert calls == [(pharmacy.pk, None), (pharmacy.pk, scope.of(people.manager).branch_ids)]
    assert signals.by_key(owner)["insight:7"]["weight"] >= 20


def test_without_the_insights_app_there_are_none(ledger, people, insights_app):
    def broken(company, branch_ids):
        raise RuntimeError("not built yet")

    insights_app(broken)

    assert weekly(people.owner)["insights"] == []


def test_the_scaffold_without_open_for_gives_none(ledger, people):
    assert weekly(people.owner)["insights"] == []


def test_nothing_to_review_in_a_new_company(pharmacy, people):
    assert facts.is_empty(weekly(people.owner))
