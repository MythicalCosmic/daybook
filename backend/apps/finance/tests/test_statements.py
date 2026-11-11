"""The balance sheet and what the business is worth (`apps.finance.statements`): a known
two-month ledger with dollars, a loan on instalments, credit both ways, owner money in and out
(the owner's own account too), an opening debt and dividends; every figure checked by hand, the
two sides balance and the reconciliation explains retained earnings to the tiyin."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.finance import partners, services, statements
from apps.finance.models import Category, MoneyAccount
from apps.finance.tests.factories import (
    CounterpartyFactory,
    ExchangeRateFactory,
    MoneyAccountFactory,
)

pytestmark = pytest.mark.django_db

D = Decimal
SEP_1 = date(2026, 9, 1)
SEP_30 = date(2026, 9, 30)
OCT_31 = date(2026, 10, 31)


def lines(section_list) -> dict[str, Decimal]:
    return {line["key"]: line["amount"] for section in section_list for line in section["lines"]}


def instalments(first: date, count: int, amount: str) -> list[tuple[date, Decimal]]:
    rows = []
    for index in range(count):
        month = first.month - 1 + index
        rows.append((date(first.year + month // 12, month % 12 + 1, first.day), D(amount)))
    return rows


@pytest.fixture
def ledger(books, owner, member, cash, bank):
    """September and October: openings (with $500), sales, rent, a 24-month loan, credit sales
    and a supplier on credit, owner money in and out, equipment booked as a cost and the owner's
    own account."""
    ExchangeRateFactory(date=SEP_1, rate=D("12000"))
    ExchangeRateFactory(date=OCT_31, rate=D("12500"))
    dollars = MoneyAccountFactory(company=books, name="Dollars", kind="safe", currency="USD")
    customer = CounterpartyFactory(company=books, name="Shifo klinikasi")
    supplier = CounterpartyFactory(company=books, name="Ko‘kterak Farm", kind="supplier")
    lender = CounterpartyFactory(company=books, name="Hamkor bank", kind="other")
    interest = services.create_category(books, by=owner, name="Interest", kind="expense")
    fridge = services.create_category(
        books, by=owner, name="Equipment", kind="expense", is_capex=True
    )
    worker = member(books, "Employee", first_name="Jasur")
    personal = services.create_account(
        books, by=owner, kind="owner", name="Olim's own money", holder=owner
    )

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

    book("opening", "2000000", SEP_1, cash)
    book("opening", "10000000", SEP_1, bank)
    book("opening", "500", SEP_1, dollars)  # $500 at 12 000 = 6 000 000
    services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=D("700000"),
        currency="UZS",
        issued_on=SEP_1,
        counterparty=customer,
        is_opening=True,
    )
    book("income", "8000000", date(2026, 9, 5), cash, "sales")
    book("expense", "1500000", date(2026, 9, 6), bank, "rent")
    loan = services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind="loan",
        amount=D("24000000"),
        currency="UZS",
        issued_on=date(2026, 9, 10),
        counterparty=lender,
        account=bank,
    )
    services.set_installments(loan, by=owner, rows=instalments(date(2026, 10, 10), 24, "1000000"))
    sale = services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="trade",
        amount=D("3000000"),
        currency="UZS",
        issued_on=date(2026, 9, 15),
        counterparty=customer,
        category="sales",
    )
    services.open_debt(
        books,
        by=owner,
        direction="payable",
        kind="trade",
        amount=D("4000000"),
        currency="UZS",
        issued_on=date(2026, 9, 20),
        counterparty=supplier,
        category="goods",
    )
    services.pay_debt(sale, by=owner, amount=D("1000000"), paid_on=date(2026, 10, 1), account=cash)
    services.open_debt(
        books,
        by=owner,
        direction="receivable",
        kind="advance",
        amount=D("400000"),
        currency="UZS",
        issued_on=date(2026, 10, 3),
        membership=worker,
        account=cash,
    )
    book("owner", "5000000", date(2026, 10, 5), bank)
    services.pay_debt(loan, by=owner, amount=D("1000000"), paid_on=date(2026, 10, 10), account=bank)
    book("expense", "150000", date(2026, 10, 10), bank, interest, debt=loan)
    book("expense", "2000000", date(2026, 10, 15), bank, fridge)
    book("owner", "-1000000", date(2026, 10, 20), cash)
    services.transfer(
        books,
        by=owner,
        from_account=bank,
        to_account=personal,
        amount_out=D("500000"),
        occurred_on=date(2026, 10, 25),
    )
    book("expense", "300000", date(2026, 10, 26), personal, "other_expense")
    return {"loan": loan, "dollars": dollars, "personal": personal, "customer": customer}


class TestBalanceSheet:
    def test_every_line_on_the_last_day_of_october(self, books, ledger):
        sheet = statements.balance_sheet(books, OCT_31, branch_ids=None)

        assets = lines(sheet["assets"]["sections"])
        # Cash 2.0M + 8.0M sales + 1.0M collected - 1.0M draw - 0.4M advance = 9.6M, and
        # $500 at October's 12 500.
        assert assets["cash_on_hand"] == D("15850000.00")
        # Bank 10M - 1.5M rent + 24M loan - 1M instalment - 0.15M interest + 5M put in - 2M
        # equipment - 0.5M moved to the owner's own account.
        assert assets["bank"] == D("33850000.00")
        assert assets["customers"] == D("2700000.00")  # 2.0M left of the sale + 0.7M opening
        assert assets["staff_owe_us"] == D("400000.00")
        assert sheet["assets"]["total"] == D("52800000.00")
        # The owner's own money is not the business's.
        assert [row["name"] for row in sheet["accounts"] if row["kind"] == "owner"] == []

        owed = lines(sheet["liabilities"]["sections"])
        assert owed["suppliers"] == D("4000000.00")
        # 23 instalments left: November to next October are due within a year, the rest later.
        assert owed["loans_current"] == D("12000000.00")
        assert owed["loans_long"] == D("11000000.00")
        assert sheet["liabilities"]["total"] == D("27000000.00")

        equity = {line["key"]: line["amount"] for line in sheet["equity"]["lines"]}
        # Put in: 5M, and the 0.3M the owner's own money paid for the business. Taken out: the
        # 1M draw and the 0.5M moved to the owner's own account.
        assert equity["owner_put_in"] == D("5300000.00")
        assert equity["owner_taken_out"] == D("-1500000.00")
        assert equity["retained"] == D("22000000.00")
        assert sheet["equity"]["total"] == D("25800000.00")
        assert sheet["check"]["balanced"] is True
        assert sheet["foreign"] == [
            {
                "currency": "USD",
                "amount": D("500.00"),
                "base": D("6250000.00"),
                "rate": D("12500"),
                "rate_date": OCT_31,
                "stale": False,
            }
        ]

    def test_the_reconciliation_explains_retained_earnings(self, books, ledger):
        sheet = statements.balance_sheet(books, OCT_31, branch_ids=None)
        made = {line["key"]: line["amount"] for line in sheet["reconciliation"]["lines"]}
        # Profit: 8M + 3M sales - 1.5M rent - 4M goods - 0.15M interest - 2M equipment - 0.3M.
        assert made["profit_recorded"] == D("3050000.00")
        assert made["opening_balances"] == D("18700000.00")  # 18M of accounts + 0.7M owed
        assert made["revaluation"] == D("250000.00")  # $500 from 12 000 to 12 500
        assert sheet["reconciliation"]["unexplained"] == D("0.00")
        assert not [gap for gap in sheet["gaps"] if gap["key"] == "unexplained"]

    @pytest.mark.parametrize("day", [SEP_1, SEP_30, date(2026, 10, 10), OCT_31])
    def test_it_balances_and_reconciles_on_any_day(self, books, ledger, day):
        sheet = statements.balance_sheet(books, day, branch_ids=None)
        assert sheet["check"]["balanced"] is True
        assert sheet["reconciliation"]["unexplained"] == D("0.00")

    def test_a_past_day_counts_what_was_owed_then(self, books, ledger):
        sheet = statements.balance_sheet(books, SEP_30, branch_ids=None)
        owed = lines(sheet["liabilities"]["sections"])
        assert owed["loans_current"] + owed["loans_long"] == D("24000000.00")
        assert lines(sheet["assets"]["sections"])["customers"] == D("3700000.00")

    def test_declared_dividends_are_owed_until_paid(self, books, owner, ledger, bank):
        partners.set_partners(
            books,
            by=owner,
            effective_on=SEP_1,
            rows=[{"membership": owner, "share": D("100")}],
        )
        dividend = partners.create_dividend(
            books, by=owner, period_start=SEP_1, period_end=SEP_30, amount=D("1000000")
        )
        today = statements.queries.local_today(books)
        sheet = statements.balance_sheet(books, today, branch_ids=None)
        assert lines(sheet["liabilities"]["sections"])["dividends"] == D("1000000.00")
        assert sheet["reconciliation"]["unexplained"] == D("0.00")
        partners.pay_dividend(dividend, by=owner, account=bank, paid_on=today)
        sheet = statements.balance_sheet(books, today, branch_ids=None)
        assert "dividends" not in lines(sheet["liabilities"]["sections"])
        assert sheet["reconciliation"]["unexplained"] == D("0.00")

    def test_modules_off_are_named_as_gaps(self, books, ledger):
        sheet = statements.balance_sheet(books, OCT_31, branch_ids=None)
        keys = [section["key"] for section in sheet["assets"]["sections"]]
        assert "stock" not in keys and "fixed_assets" not in keys
        gaps = {gap["key"]: gap["params"] for gap in sheet["gaps"]}
        assert "no_stock_module" in gaps
        assert gaps["no_assets_module"] == {"equipment": D("2000000.00")}

    def test_stock_on_shows_the_stock_line(self, books, ledger):
        books.features = ["finance", "stock"]
        books.save(update_fields=["features"])
        sheet = statements.balance_sheet(books, OCT_31, branch_ids=None)
        stock = next(s for s in sheet["assets"]["sections"] if s["key"] == "stock")
        assert stock["total"] == D("0.00")
        assert "no_stock_module" not in {gap["key"] for gap in sheet["gaps"]}

    def test_without_opening_balances_it_says_so(self, books, owner, cash):
        services.record_transaction(
            books,
            by=owner,
            kind="income",
            amount=D("100000"),
            occurred_on=SEP_1,
            account=cash,
            category="sales",
        )
        sheet = statements.balance_sheet(books, OCT_31, branch_ids=None)
        assert {"key": "no_opening", "params": {"day": SEP_1}} in sheet["gaps"]

    def test_a_branch_shows_its_own_net_assets(self, books, owner, ledger):
        branch = books.branches.first()
        till = MoneyAccountFactory(company=books, name="Branch till", kind="cash", branch=branch)
        services.record_transaction(
            books,
            by=owner,
            kind="income",
            amount=D("900000"),
            occurred_on=OCT_31,
            account=till,
            category="sales",
        )
        sheet = statements.balance_sheet(books, OCT_31, branch_ids=[branch.pk])
        assert sheet["whole_company"] is False
        assert sheet["assets"]["total"] == D("900000.00")
        assert sheet["equity"]["lines"] == [{"key": "net_assets", "amount": D("900000.00")}]
        assert sheet["reconciliation"] is None
        assert statements.balance_sheet(books, OCT_31, branch_ids=[])["assets"]["total"] == 0

    def test_a_future_day_is_today(self, books, ledger):
        today = statements.queries.local_today(books)
        sheet = statements.balance_sheet(books, today + timedelta(days=30), branch_ids=None)
        assert sheet["on"] == today


class TestWorth:
    def test_earnings_add_back_interest_and_equipment(self, books, ledger):
        made = statements.earnings(books, OCT_31)
        assert made["from"] == SEP_1 and made["days"] == 61 and made["enough"]
        parts = {line["key"]: line["amount"] for line in made["lines"]}
        assert parts == {
            "profit": D("3050000.00"),
            "depreciation": D("0.00"),
            "interest": D("150000.00"),
            "equipment": D("2000000.00"),
        }
        assert made["earnings"] == D("5200000.00")
        # Scaled up from 61 days to a year.
        assert made["yearly"] == (D("5200000") * 365 / 61).quantize(D("0.01"))

    def test_the_range_spans_both_methods(self, books, ledger):
        value = statements.worth(books, OCT_31)
        assert (value["multiple_low"], value["multiple_high"]) == (D("2.0"), D("3.0"))
        yearly = value["earnings"]["yearly"]
        method = value["earnings_method"]
        assert method["applies"] is True
        assert method["business_low"] == (yearly * 2).quantize(D("0.01"))
        assert method["cash"] == D("49700000.00")
        assert method["debt"] == D("23000000.00")  # what is left on the loan
        assert method["low"] == method["business_low"] + D("26700000.00")
        assert value["net_assets"]["value"] == D("25800000.00")
        assert value["range"] == {
            "low": min(method["low"], D("25800000.00")),
            "high": max(method["high"], D("25800000.00")),
        }

    def test_the_owner_sets_the_multiples(self, books, ledger):
        row = statements.conf.get_settings(books)
        row.valuation_multiple_low, row.valuation_multiple_high = D("4.0"), D("1.5")
        row.save()
        value = statements.worth(books, OCT_31)
        assert (value["multiple_low"], value["multiple_high"]) == (D("1.5"), D("4.0"))
        assert statements.worth(books, OCT_31, low="2.5", high="2.5")["multiple_low"] == D("2.5")

    def test_too_early_and_a_loss_leave_only_net_assets(self, books, owner, cash):
        services.record_transaction(
            books,
            by=owner,
            kind="opening",
            amount=D("1000000"),
            occurred_on=date(2026, 10, 1),
            account=cash,
        )
        early = statements.worth(books, OCT_31)
        assert early["earnings_method"]["reason"] == "too_early"
        assert early["range"] == {"low": D("1000000.00"), "high": D("1000000.00")}
        services.record_transaction(
            books,
            by=owner,
            kind="expense",
            amount=D("400000"),
            occurred_on=date(2026, 8, 1),
            account=cash,
            category="rent",
        )
        assert statements.worth(books, OCT_31)["earnings_method"]["reason"] == "loss"

    def test_non_cash_costs_count_as_depreciation(self, books, ledger, src):
        services.book_non_cash(
            books,
            amount=D("90000"),
            occurred_on=date(2026, 10, 31),
            category=Category.objects.create(
                company=books, name="Depreciation", kind="expense", system_code="depreciation"
            ),
            source=src(1),
        )
        parts = {
            line["key"]: line["amount"] for line in statements.earnings(books, OCT_31)["lines"]
        }
        assert parts["depreciation"] == D("90000.00")
        assert parts["profit"] == D("2960000.00")


def test_the_owner_account_is_never_cash(books, ledger):
    sheet = statements.balance_sheet(books, OCT_31, branch_ids=None)
    assert ledger["personal"].kind == MoneyAccount.Kind.OWNER
    listed = {row["id"] for row in sheet["accounts"]}
    assert listed == set(
        MoneyAccount.objects.filter(company=books)
        .exclude(kind="owner")
        .values_list("pk", flat=True)
    )
    cash = sum((line["amount"] for line in sheet["assets"]["sections"][0]["lines"]), D(0))
    assert cash == sum((row["base"] for row in sheet["accounts"]), D(0))
