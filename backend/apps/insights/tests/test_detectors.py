"""Each detection rule fires once on its numbers, updates the same insight when run again
(dedupe), and resolves it once the numbers no longer show it."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.finance import conf as finance_conf
from apps.finance import queries
from apps.insights import conf, engine
from apps.insights.models import Insight, Snapshot
from apps.insights.tests.conftest import NOW, TODAY, days_before, mln

pytestmark = pytest.mark.django_db

Kind = Insight.Kind


def live(company, kind):
    return list(
        Insight.objects.filter(company=company, kind=kind, status__in=Insight.LIVE).order_by("pk")
    )


def run(company, now=NOW):
    return engine.run(company, now, notify=False)


def assert_fires_once_and_dedupes(company, kind, now=NOW) -> Insight:
    run(company, now)
    found = live(company, kind)
    assert len(found) == 1, found
    first = found[0]
    run(company, now + timedelta(hours=6))
    again = live(company, kind)
    assert [insight.pk for insight in again] == [first.pk]
    assert Insight.objects.filter(company=company, kind=kind).count() == 1
    again[0].refresh_from_db()
    assert again[0].last_seen_at > first.last_seen_at
    return again[0]


# Cash ---------------------------------------------------------------------------------------


def test_cash_low_point_under_the_buffer(shop, books):
    row = finance_conf.get_settings(shop)
    row.cash_buffer = mln(10)
    row.save()
    books.income(mln(5), days_before(70), category="other_income")
    insight = assert_fires_once_and_dedupes(shop, Kind.CASH_LOW)
    assert insight.severity == Insight.Severity.WARNING
    assert insight.branch_id is None
    # The low of the next 30 days of the cockpit's 90-day forecast.
    points = queries.forecast(shop, 90, branch_ids=None, today=TODAY)["points"][:31]
    lowest = min(points, key=lambda point: Decimal(point["balance"]))
    assert insight.metrics["value"] == lowest["balance"]
    assert insight.metrics["low_date"] == lowest["date"]
    assert insight.metrics["threshold"] == "10000000.00"
    assert insight.metrics["short_by"] == "5000000.00"
    assert insight.metrics["buffer_source"] == "setting"
    assert len(insight.metrics["series"]) == 31

    books.income(mln(50), days_before(65), category="other_income")
    run(shop, NOW + timedelta(hours=12))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED
    assert insight.resolved_at is not None


def test_cash_running_out_is_urgent_and_names_the_payment(shop, books):
    books.income(mln(5), days_before(70), category="other_income")
    party = books.party("Oqtosh Med")
    books.owed("payable", mln(8), days_before(20), TODAY + timedelta(days=5), party)
    run(shop)
    [insight] = live(shop, Kind.CASH_LOW)
    assert insight.severity == Insight.Severity.CRITICAL
    assert insight.metrics["below_zero_on"] == (TODAY + timedelta(days=5)).isoformat()
    assert insight.metrics["causes"][0]["title"] == "Oqtosh Med"
    assert insight.metrics["causes"][0]["amount"] == "8000000.00"
    assert insight.title.startswith("Cash runs out on")


def test_the_buffer_is_the_owners_one_buffer_from_finance(shop, books):
    books.income(mln(500), days_before(70), category="other_income")
    for day in range(1, 57):
        books.expense(mln(1), days_before(day), category="utilities")
    run(shop)
    # A month of fixed costs (utilities, 1 mln a day) is about 30 mln: 500 mln minus a month of
    # spending stays far above it.
    assert live(shop, Kind.CASH_LOW) == []
    from apps.finance import owner_draw
    from apps.insights import detectors

    buffer, source = detectors.cash_buffer(shop, TODAY)
    assert source == "fixed_costs"
    assert buffer == owner_draw.cash_buffer(shop, TODAY)["amount"] > 0
    # The owner's own buffer ("Mening pulim") is the cockpit's too.
    row = finance_conf.get_settings(shop)
    row.cash_buffer = mln(20)
    row.save()
    assert detectors.cash_buffer(shop, TODAY) == (mln(20), "setting")


# Branch margin ------------------------------------------------------------------------------


def test_a_branch_margin_falling(shop, books, branches):
    chilonzor, yunusobod = branches
    for branch in branches:
        books.income(mln(100), days_before(40), branch)  # 10 September: the same days
        books.expense(mln(80), days_before(39), branch)
    books.income(mln(100), days_before(10), chilonzor)  # 10 October
    books.expense(mln(95), days_before(9), chilonzor)
    books.income(mln(100), days_before(10), yunusobod)
    books.expense(mln(80), days_before(9), yunusobod)
    insight = assert_fires_once_and_dedupes(shop, Kind.BRANCH_MARGIN)
    assert insight.branch_id == chilonzor.pk
    assert insight.severity == Insight.Severity.WARNING
    assert insight.metrics["value"] == "5.0"
    assert insight.metrics["baseline"] == "20.0"
    assert insight.metrics["period"] == "month"
    pnl = queries.pnl(
        shop,
        TODAY.replace(day=1),
        TODAY,
        "month",
        branch_ids=[chilonzor.pk],
        compare=(TODAY.replace(month=9, day=1), TODAY.replace(month=9)),
    )
    assert insight.metrics["profit"] == str(pnl["profit"]["total"])
    assert insight.metrics["profit_previous"] == str(pnl["profit"]["previous"])
    assert insight.subject_label == "Chilonzor"
    assert "Chilonzor" in insight.title

    books.income(mln(100), days_before(5), chilonzor)
    run(shop, NOW + timedelta(hours=12))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED


def test_a_branch_losing_money_is_urgent(shop, books, branches):
    chilonzor = branches[0]
    books.income(mln(100), days_before(40), chilonzor)
    books.expense(mln(80), days_before(39), chilonzor)
    books.income(mln(50), days_before(10), chilonzor)
    books.expense(mln(70), days_before(9), chilonzor)
    run(shop)
    [insight] = live(shop, Kind.BRANCH_MARGIN)
    assert insight.severity == Insight.Severity.CRITICAL
    assert "losing money" in insight.title


def test_early_in_the_month_the_margin_compares_last_month(shop, books, branches):
    chilonzor = branches[0]
    books.income(mln(100), days_before(75), chilonzor)  # August
    books.expense(mln(80), days_before(75), chilonzor)
    books.income(mln(100), days_before(40), chilonzor)  # September
    books.expense(mln(97), days_before(40), chilonzor)
    third = NOW.replace(day=3)
    run(shop, third)
    [insight] = live(shop, Kind.BRANCH_MARGIN)
    assert insight.metrics["period"] == "last_month"
    assert insight.metrics["from"] == "2026-09-01"
    assert insight.metrics["to"] == "2026-09-30"


# Expense spike ------------------------------------------------------------------------------


def test_an_expense_category_jumping(shop, books):
    for week in range(1, 9):
        books.expense(Decimal(400_000), days_before(7 * week), category="transport")
    books.expense(mln(2), days_before(1), category="transport")
    insight = assert_fires_once_and_dedupes(shop, Kind.EXPENSE_SPIKE)
    assert insight.subject_type == "category"
    assert insight.metrics["value"] == "2000000.00"
    assert insight.metrics["baseline"] == "400000.00"
    assert insight.metrics["ratio"] == "5.0"
    assert insight.severity == Insight.Severity.WARNING

    # A week later the spike has left the last 7 days.
    run(shop, NOW + timedelta(days=8))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED


def test_lumpy_and_new_expenses_are_not_spikes(shop, books):
    # Rent is monthly by nature; a category seen once before isn't a usual expense.
    books.expense(mln(9), days_before(33), category="rent")
    books.expense(mln(9), days_before(2), category="rent")
    books.expense(Decimal(300_000), days_before(30), category="repairs")
    books.expense(mln(5), days_before(1), category="repairs")
    run(shop)
    assert live(shop, Kind.EXPENSE_SPIKE) == []


def test_a_small_jump_isnt_worth_a_word(shop, books):
    for week in range(1, 9):
        books.expense(Decimal(100_000), days_before(7 * week), category="transport")
    books.expense(Decimal(600_000), days_before(1), category="transport")  # 6x, but 0.5 mln
    run(shop)
    assert live(shop, Kind.EXPENSE_SPIKE) == []


# Overdue debts ------------------------------------------------------------------------------


def test_overdue_receivables_piling_up(shop, books):
    clinic = books.party("Shifo klinikasi", kind="customer")
    neighbour = books.party("Botir aka", kind="customer")
    first = books.owed("receivable", mln(2), days_before(40), days_before(10), clinic)
    second = books.owed("receivable", mln(2), days_before(30), days_before(5), neighbour)
    insight = assert_fires_once_and_dedupes(shop, Kind.OVERDUE_RECEIVABLES)
    assert insight.metrics["value"] == "4000000.00"
    assert insight.metrics["count"] == 2
    assert insight.metrics["oldest_days"] == 10
    assert [party["name"] for party in insight.metrics["parties"]] == [
        "Shifo klinikasi",
        "Botir aka",
    ]

    books.pay(first, mln(2), days_before(1))
    books.pay(second, mln(2), days_before(1))
    run(shop, NOW + timedelta(hours=12))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED


def test_overdue_supplier_bills(shop, books):
    supplier = books.party("Tolzor Farm")
    debt = books.owed("payable", mln(4), days_before(20), days_before(3), supplier)
    insight = assert_fires_once_and_dedupes(shop, Kind.OVERDUE_PAYABLES)
    assert insight.metrics["value"] == "4000000.00"
    assert insight.severity == Insight.Severity.WARNING
    books.pay(debt, mln(4), days_before(0))
    run(shop, NOW + timedelta(hours=12))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED


def test_people_debts_are_not_supplier_bills(shop, books, member):
    from apps.finance import services as finance

    worker = member.registered(shop, "Employee")
    finance.open_debt(
        shop,
        by=books.by,
        direction="payable",
        kind="salary",
        amount=mln(9),
        currency="UZS",
        issued_on=days_before(20),
        due_on=days_before(5),
        membership=worker,
        category="salaries",
    )
    run(shop)
    assert live(shop, Kind.OVERDUE_PAYABLES) == []


# Stock --------------------------------------------------------------------------------------


@pytest.fixture
def stock_values(monkeypatch):
    values = {}

    def value(company, *, branch_ids):
        return {"value": values.get(branch_ids[0], Decimal(0)), "retail_value": Decimal(0)}

    monkeypatch.setattr("apps.inventory.queries.stock_value", value)
    return values


def test_stock_growing_while_sales_fall(shop, books, branches, stock_values):
    shop.features = ["finance", "stock"]
    shop.save(update_fields=["features"])
    chilonzor = branches[0]
    Snapshot.objects.create(
        company=shop, day=days_before(28), metric="stock_value", branch=chilonzor, value=mln(100)
    )
    stock_values[chilonzor.pk] = mln(120)
    books.income(mln(100), days_before(40), chilonzor)  # the four weeks before
    books.income(mln(80), days_before(10), chilonzor)  # the last four weeks
    insight = assert_fires_once_and_dedupes(shop, Kind.STOCK_BUILD)
    assert insight.branch_id == chilonzor.pk
    assert insight.metrics["stock_change"] == "20.0"
    assert insight.metrics["sales_change"] == "-20.0"
    assert Snapshot.objects.filter(company=shop, day=TODAY, branch=chilonzor).exists()

    stock_values[chilonzor.pk] = mln(101)
    run(shop, NOW + timedelta(hours=12))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED


def test_stock_rule_waits_for_the_stock_module(shop, books, stock_values):
    run(shop)
    assert not Snapshot.objects.filter(company=shop).exists()


# Staff costs --------------------------------------------------------------------------------


def test_staff_cost_share_rising(shop, books):
    from apps.finance import services as finance

    for month in (6, 7, 8):
        day = TODAY.replace(month=month, day=15)
        books.income(mln(100), day)
        books.expense(mln(15), day, category="salaries")
    september = TODAY.replace(month=9, day=15)
    books.income(mln(100), september)
    books.expense(mln(20), september, category="salaries")
    insight = assert_fires_once_and_dedupes(shop, Kind.STAFF_COST)
    assert insight.domain == Insight.Domain.PAYROLL
    assert insight.metrics["value"] == "20.0"
    assert insight.metrics["baseline"] == "15.0"
    assert insight.metrics["month"] == "2026-09"
    assert finance  # the salaries above are plain expenses of the system category

    books.income(mln(60), september)
    run(shop, NOW + timedelta(hours=12))
    insight.refresh_from_db()
    assert insight.status == Insight.Status.RESOLVED


# Switches -----------------------------------------------------------------------------------


def test_a_kind_switched_off_doesnt_run(shop, books):
    supplier = books.party("Tolzor Farm")
    books.owed("payable", mln(4), days_before(20), days_before(3), supplier)
    row = conf.get_settings(shop)
    row.disabled_kinds = [Kind.OVERDUE_PAYABLES]
    row.save()
    run(shop)
    assert live(shop, Kind.OVERDUE_PAYABLES) == []


def test_without_finance_nothing_runs(shop, books):
    supplier = books.party("Tolzor Farm")
    books.owed("payable", mln(4), days_before(20), days_before(3), supplier)
    shop.features = []
    shop.save(update_fields=["features"])
    assert engine.run(shop, NOW, notify=False)["created"] == 0


def test_lower_sensitivity_needs_a_bigger_change(shop, books):
    supplier = books.party("Tolzor Farm")
    books.owed("payable", mln(4), days_before(20), days_before(3), supplier)
    row = conf.get_settings(shop)
    row.sensitivity = "low"  # 3 mln times 1.5: 4 mln is not enough
    row.save()
    run(shop)
    assert live(shop, Kind.OVERDUE_PAYABLES) == []
