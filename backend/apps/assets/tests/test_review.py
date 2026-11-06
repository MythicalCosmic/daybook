"""The v6 money review of fixed assets and its seam with Finance: each test failed on 0.4.2 and
pins the fix (docs: the review hand-off, v6-review-assets.md)."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.assets import services
from apps.assets.models import DepreciationEntry
from apps.assets.tests.test_posting import buy, depreciation_rows
from apps.core.exceptions import DomainError
from apps.finance import queries as finance_queries

pytestmark = pytest.mark.django_db

NOV_1, NOV_30 = date(2026, 11, 1), date(2026, 11, 30)


def base(company) -> str:
    return f"/api/v1/owner/companies/{company.pk}/assets"


def november(shop) -> dict:
    return finance_queries.totals(shop, NOV_1, NOV_30, branch_ids=None)


def test_one_expense_is_capitalized_once(shop, owner, cash, equipment, chilonzor, category):
    """An expense that bought an asset (or was added to one) leaves the P&L once: using it a
    second time would bring its cost back twice as depreciation."""
    txn = buy(shop, owner, cash, equipment, chilonzor, amount=1_200_000, day=date(2026, 11, 2))
    fridge = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 11, 3),
    )
    other = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Konditsioner",
        cost=D(5_000_000),
        life_months=60,
        in_service_on=date(2026, 11, 3),
    )
    with pytest.raises(DomainError):
        services.add_to_cost(
            other, by=owner, on=date(2026, 11, 4), amount=D(1_200_000), purchase=txn.pk
        )
    extra = buy(shop, owner, cash, equipment, chilonzor, amount=300_000, day=date(2026, 11, 4))
    services.add_to_cost(fridge, by=owner, on=date(2026, 11, 4), amount=D(300_000), purchase=extra)
    with pytest.raises(DomainError):
        services.add_to_cost(
            fridge, by=owner, on=date(2026, 11, 5), amount=D(300_000), purchase=extra.pk
        )
    with pytest.raises(DomainError):
        services.create_asset(
            shop, by=owner, category=category, name="Javon", purchase_transaction=extra
        )


def test_a_late_month_after_a_move_still_reaches_finance(
    shop, owner, cash, equipment, chilonzor, yunusobod, category
):
    """October of a fridge is booked at Chilonzor, then the fridge moves to Yunusobod. Another
    Chilonzor asset entered later gets its October: it must land in a row of its own, not be
    "found" in the fridge's row (whose amount never included it)."""
    bought = buy(shop, owner, cash, equipment, chilonzor, amount=8_400_000, day=date(2026, 9, 5))
    fridge = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=bought,
        in_service_on=date(2026, 9, 10),
    )
    services.move(fridge, by=owner, branch=yunusobod, on=date(2026, 11, 2))
    later = buy(shop, owner, cash, equipment, chilonzor, amount=4_200_000, day=date(2026, 9, 6))
    services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich 2",
        purchase_transaction=later,
        in_service_on=date(2026, 9, 10),
    )
    october = DepreciationEntry.objects.filter(company=shop, month=date(2026, 10, 1))
    assert sorted(entry.amount for entry in october) == [D("50000.00"), D("100000.00")]
    for row in depreciation_rows(shop):
        linked = sum((entry.amount for entry in row.depreciation_entries.all()), D(0))
        assert -row.base_amount == linked, row.description
    in_finance = sum(-row.base_amount for row in depreciation_rows(shop))
    assert in_finance == sum(
        entry.amount for entry in DepreciationEntry.objects.filter(company=shop)
    )
