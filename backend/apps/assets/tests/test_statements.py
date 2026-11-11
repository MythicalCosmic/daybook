"""Fixed assets in the finance statements' balance sheet (v12): at net book value, and the
reconciliation still explains retained earnings to the tiyin when assets were bought through the
ledger, entered from before the books, depreciated and sold."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.assets import posting, queries, services
from apps.assets.tests.conftest import DAY
from apps.assets.tests.test_posting import buy
from apps.finance import statements

pytestmark = pytest.mark.django_db


def fixed_line(sheet) -> dict:
    section = next(s for s in sheet["assets"]["sections"] if s["key"] == "fixed_assets")
    return section["lines"][0]


def test_fixed_assets_at_book_value_and_the_books_still_reconcile(
    shop, owner, cash, equipment, chilonzor, category
):
    bought = buy(shop, owner, cash, equipment, chilonzor, amount=12_000_000, day=date(2026, 5, 20))
    services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=bought,
        in_service_on=date(2026, 5, 25),
    )
    older = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Konditsioner",
        cost=D(6_000_000),
        life_months=60,
        purchased_on=date(2025, 3, 1),
        in_service_on=date(2025, 3, 1),
    )
    posting.book_company(shop)
    services.dispose(older, by=owner, on=DAY, kind="sold", amount=D(2_500_000), account=cash)

    sheet = statements.balance_sheet(shop, DAY, branch_ids=None)
    line = fixed_line(sheet)
    assert line["amount"] == queries.summary(shop, branch_ids=None, today=DAY)["book"]
    assert line["amount"] > 0
    assert sheet["check"]["balanced"] is True
    assert sheet["reconciliation"]["unexplained"] == D("0.00")
    assert "no_assets_module" not in {gap["key"] for gap in sheet["gaps"]}

    # Before the sale the older asset was there too, and nothing is unexplained either.
    before = statements.balance_sheet(shop, date(2026, 10, 31), branch_ids=None)
    assert fixed_line(before)["amount"] > line["amount"]
    assert before["reconciliation"]["unexplained"] == D("0.00")


def test_depreciation_is_added_back_to_earnings(shop, owner, cash, equipment, chilonzor, category):
    bought = buy(shop, owner, cash, equipment, chilonzor, amount=12_000_000, day=date(2026, 5, 20))
    services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=bought,
        in_service_on=date(2026, 5, 25),
    )
    posting.book_company(shop)
    made = statements.earnings(shop, DAY)
    parts = {line["key"]: line["amount"] for line in made["lines"]}
    assert parts["depreciation"] > 0
    # The purchase became a fixed asset: it is no longer a cost to add back.
    assert parts["equipment"] == D("0.00")
    assert made["earnings"] == parts["profit"] + parts["depreciation"]
