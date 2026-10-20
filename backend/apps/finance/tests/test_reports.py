"""Reports on a seeded ledger with known totals: P&L by month with drill-down, cash flow in the
analytics shape with its sections, balances on a date, debt aging and category trends."""

from datetime import date
from decimal import Decimal

import pytest

from apps.finance import queries, services
from apps.finance.models import Category
from apps.finance.tests.factories import (
    CounterpartyFactory,
    ExchangeRateFactory,
    MoneyAccountFactory,
)

pytestmark = pytest.mark.django_db

SEP_5 = date(2026, 9, 5)
SEP_20 = date(2026, 9, 20)
OCT_3 = date(2026, 10, 3)
OCT_10 = date(2026, 10, 10)
D = Decimal


@pytest.fixture
def ledger(books, owner, cash, bank):
    """September and October of a small shop, with a dollar account, a loan and credit sales."""
    for day in (SEP_5, SEP_20, OCT_3, OCT_10):
        ExchangeRateFactory(date=day, rate=D("12000"))
    goods = Category.objects.get(company=books, system_code="goods")
    drinks = services.create_category(books, by=owner, name="Drinks", kind="expense", parent=goods)
    fridge = services.create_category(books, by=owner, name="Fridge", kind="expense", is_capex=True)
    dollars = MoneyAccountFactory(company=books, name="Dollars", kind="safe", currency="USD")
    party = CounterpartyFactory(company=books, name="Barakat Kafe")

    def book(kind, amount, day, account, category=None, **extra):
        return services.record_transaction(
            books,
            by=owner,
            kind=kind,
            amount=D(amount),
            occurred_on=day,
            account=account,
            category=category,
            **extra,
        )

    book("opening", "1000000", SEP_5, cash)
    book("opening", "100", SEP_5, dollars)  # $100 = 1 200 000
    book("income", "5000000", SEP_5, cash, "sales")
    book("expense", "2000000", SEP_20, cash, goods)
    book("expense", "500000", SEP_20, cash, drinks)
    book("income", "7000000", OCT_3, bank, "sales")
    book("expense", "1000000", OCT_3, bank, "rent")
    book("expense", "50", OCT_10, dollars, "rent")  # $50 = 600 000
    book("expense", "3000000", OCT_10, bank, fridge)  # equipment: investing
    book("owner", "-400000", OCT_10, cash)  # a draw, never profit
    services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind="loan",
        amount=D("2000000"),
        currency="UZS",
        issued_on=SEP_20,
        counterparty=party,
        account=bank,
    )
    sale = services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=D("800000"),
        currency="UZS",
        issued_on=OCT_3,
        due_on=date(2026, 10, 8),
        counterparty=party,
        category="sales",
    )
    services.pay_debt(sale, by=owner, amount=D("300000"), paid_on=OCT_10, account=cash)
    services.transfer(
        books,
        by=owner,
        from_account=cash,
        to_account=bank,
        amount_out=D("1000000"),
        occurred_on=OCT_10,
    )
    return {"goods": goods, "drinks": drinks, "fridge": fridge, "dollars": dollars, "party": party}


def test_pnl_by_month_with_drill_down(books, ledger):
    data = queries.pnl(books, SEP_5, date(2026, 10, 31), "month", branch_ids=None)
    assert [period["key"] for period in data["periods"]] == ["2026-09", "2026-10"]
    assert data["income"]["amounts"] == [D("5000000.00"), D("7800000.00")]
    assert data["expense"]["amounts"] == [D("2500000.00"), D("4600000.00")]
    assert data["profit"]["amounts"] == [D("2500000.00"), D("3200000.00")]
    assert data["profit"]["total"] == D("5700000.00")
    assert data["margin"]["amounts"] == ["50.0", "41.0"]
    goods = next(node for node in data["expense"]["nodes"] if node["id"] == ledger["goods"].pk)
    assert goods["amounts"] == [D("2500000.00"), D("0.00")]
    assert goods["own"] == [D("2000000.00"), D("0.00")]
    assert [child["name"] for child in goods["children"]] == ["Drinks"]
    names = {node["name"] for node in data["expense"]["nodes"]}
    assert "Fridge" in names  # the P&L counts equipment; the cash flow puts it under investing


def test_pnl_by_quarter_and_compare(books, ledger):
    data = queries.pnl(books, OCT_3, OCT_10, "quarter", branch_ids=None, compare=(SEP_5, SEP_20))
    assert [period["key"] for period in data["periods"]] == ["2026-Q4"]
    assert data["income"]["previous"] == D("5000000.00")
    assert data["profit"]["previous"] == D("2500000.00")


def test_cash_flow_in_the_analytics_shape(books, ledger):
    data = queries.cash_flow(books, OCT_3, OCT_10, "day", branch_ids=None)
    assert data["totals"] == {
        "income": D("7300000.00"),  # sales on the bank + the customer's payment
        "expense": D("5000000.00"),  # rent, dollar rent, the fridge, the owner's draw
        "net": D("2300000.00"),
    }
    assert len(data["series"]) == 8
    assert data["series"][0] == {
        "date": "2026-10-03",
        "income": D("7000000.00"),
        "expense": D("1000000.00"),
        "net": D("6000000.00"),
    }
    sections = {row["key"]: row for row in data["sections"]}
    assert sections["investing"]["expense"] == D("3000000.00")
    assert sections["owner"]["expense"] == D("400000.00")
    assert sections["transfers"]["income"] == sections["transfers"]["expense"] == D("1000000.00")
    # Start + every section = end: the statement reconciles.
    assert data["start_cash"] == D("6700000.00")
    assert data["end_cash"] == D("9000000.00")


def test_balances_on_a_date(books, ledger):
    data = queries.balances_on(books, SEP_20, branch_ids=None)
    rows = {row["name"]: row for row in data["accounts"]}
    assert rows["Dollars"]["balance"] == D("100.00")
    assert rows["Dollars"]["base"] == D("1200000.00")
    assert data["total"] == D("6700000.00")  # 3.5 M cash + 2 M loan on the bank + $100
    assert data["payable"]["total"] == D("2000000.00")
    assert data["receivable"]["total"] == D("0.00")
    assert data["net"] == D("4700000.00")


def test_debt_aging(books, ledger):
    data = queries.debts_aging(books, "receivable", branch_ids=None, today=date(2026, 10, 21))
    assert data["totals"]["d1_30"] == D("500000.00")
    assert data["parties"][0]["name"] == "Barakat Kafe"
    assert data["parties"][0]["oldest_due"] == date(2026, 10, 8)


def test_category_trend(books, ledger):
    data = queries.category_trend(books, ledger["goods"], 3, branch_ids=None, today=OCT_10)
    assert [point["amount"] for point in data["series"]] == [D("0.00"), D("2500000.00"), D("0.00")]


def test_totals_ignore_owner_money_transfers_and_openings(books, ledger):
    result = queries.totals(books, SEP_5, date(2026, 10, 31), "month", branch_ids=None)
    assert result["income"] == D("12800000.00")
    assert result["expense"] == D("7100000.00")
    assert [point["profit"] for point in result["series"]] == [D("2500000.00"), D("3200000.00")]


def test_branch_scope_narrows_every_report(books, owner, member):
    from apps.companies.models import Branch

    main = books.branches.first()
    other = Branch.objects.create(company=books, name="Yunusobod")
    here = MoneyAccountFactory(company=books, name="Here", branch=main)
    there = MoneyAccountFactory(company=books, name="There", branch=other)
    for account, amount in ((here, "100"), (there, "900")):
        services.record_transaction(
            books,
            by=owner,
            kind="income",
            amount=D(amount),
            occurred_on=OCT_3,
            account=account,
            category="sales",
        )
    assert queries.totals(books, OCT_3, OCT_3, branch_ids=[main.pk])["income"] == D("100.00")
    assert queries.cash_flow(books, OCT_3, OCT_3, "day", branch_ids=[other.pk])["totals"][
        "income"
    ] == D("900.00")
    assert queries.cash_position(books, None, branch_ids=[main.pk], today=OCT_3)["total"] == D(
        "100.00"
    )
    assert queries.pnl(books, OCT_3, OCT_3, "month", branch_ids=[])["income"]["total"] == D("0.00")
