"""The v6 money review of fixed assets and its seam with Finance: each test failed on 0.4.2 and
pins the fix (docs: the review hand-off, v6-review-assets.md)."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.assets import services
from apps.assets.models import AssetCategory, DepreciationEntry
from apps.assets.tests.test_posting import buy, depreciation_rows
from apps.core.exceptions import DomainError
from apps.finance import queries as finance_queries
from apps.finance import services as finance
from apps.finance.models import Transaction

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


def test_an_asset_written_down_in_finance_is_never_deleted(shop, owner, category):
    """Deleting it would leave the write-down in the P&L with nothing to correct it from."""
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        cost=D(6_000_000),
        life_months=60,
        in_service_on=date(2026, 11, 2),
    )
    services.write_down(asset, by=owner, on=date(2026, 11, 5), amount=D(1_000_000))
    assert Transaction.objects.filter(company=shop, category__system_code="asset_disposal").exists()
    with pytest.raises(DomainError):
        services.delete_asset(asset, by=owner)


def test_an_asset_written_off_in_finance_is_never_deleted(shop, owner, category):
    asset = services.create_asset(
        shop, by=owner, category=category, name="Kassa", cost=D(3_000_000), life_months=60
    )
    services.dispose(asset, by=owner, on=date(2026, 11, 5), kind="written_off", reason="Singan")
    assert Transaction.objects.filter(company=shop, category__system_code="asset_disposal").exists()
    with pytest.raises(DomainError):
        services.delete_asset(asset, by=owner)


def test_a_low_value_item_bought_in_finance_stays_an_expense_once(
    shop, owner, cash, equipment, chilonzor
):
    """Low-value items are never depreciated: their cost is an expense of the month they are
    bought, never taken out of the P&L, and never booked a second time when thrown away."""
    uniforms = AssetCategory.objects.get(company=shop, system_code="low_value")
    txn = buy(shop, owner, cash, equipment, chilonzor, amount=450_000, day=date(2026, 11, 2))
    item = services.create_asset(
        shop, by=owner, category=uniforms, name="Xalatlar", purchase_transaction=txn
    )
    txn.refresh_from_db()
    assert not txn.capitalized
    assert november(shop)["expense"] == D("450000.00")
    services.write_down(item, by=owner, on=date(2026, 11, 5), amount=D(50_000))
    services.dispose(item, by=owner, on=date(2026, 11, 6), kind="written_off", reason="Eskirdi")
    assert november(shop)["expense"] == D("450000.00")


def test_an_asset_bought_or_booked_in_finance_never_turns_low_value(
    shop, owner, cash, equipment, chilonzor, category
):
    """A low-value item never depreciates: a fridge moved into that category would keep its
    purchase out of the P&L (or its booked months) with nothing left to bring the rest in."""
    uniforms = AssetCategory.objects.get(company=shop, system_code="low_value")
    txn = buy(shop, owner, cash, equipment, chilonzor, amount=6_000_000, day=date(2026, 11, 2))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 11, 3),
    )
    with pytest.raises(DomainError):
        services.update_asset(asset, by=owner, category=uniforms)
    old = buy(shop, owner, cash, equipment, chilonzor, amount=8_400_000, day=date(2026, 9, 5))
    booked = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Konditsioner",
        purchase_transaction=old,
        in_service_on=date(2026, 9, 10),
    )
    assert booked.entries.filter(transaction__isnull=False).exists()
    with pytest.raises(DomainError):
        services.update_asset(booked, by=owner, category=uniforms)


def test_the_cost_of_an_asset_bought_in_finance_stays_the_expense(
    shop, owner, cash, equipment, chilonzor, category
):
    """Before its first month is booked the facts may be corrected, but the cost of an asset
    whose purchase left the P&L is that purchase: anything else would lose or add money."""
    txn = buy(shop, owner, cash, equipment, chilonzor, amount=6_000_000, day=date(2026, 11, 2))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 11, 3),
    )
    with pytest.raises(DomainError):
        services.update_asset(asset, by=owner, cost=D(5_000_000))
    # The form sends the cost back unchanged with every correction.
    services.update_asset(asset, by=owner, cost=D(6_000_000), life_months=60)
    asset.refresh_from_db()
    assert asset.cost == D("6000000.00") and asset.life_months == 60


def test_an_asset_that_books_no_depreciation_keeps_its_purchases_as_expenses(
    shop, owner, cash, equipment, chilonzor, category
):
    """Without depreciation in Finance nothing would bring a capitalized purchase back."""
    txn = buy(shop, owner, cash, equipment, chilonzor, amount=6_000_000, day=date(2026, 11, 2))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 11, 3),
        books_depreciation=False,
    )
    txn.refresh_from_db()
    assert not txn.capitalized
    extra = buy(shop, owner, cash, equipment, chilonzor, amount=600_000, day=date(2026, 11, 4))
    services.add_to_cost(asset, by=owner, on=date(2026, 11, 4), amount=D(600_000), purchase=extra)
    extra.refresh_from_db()
    assert not extra.capitalized
    assert november(shop)["expense"] == D("6600000.00")


def test_books_depreciation_follows_the_purchase_in_finance(
    shop, owner, cash, equipment, chilonzor, category
):
    txn = buy(shop, owner, cash, equipment, chilonzor, amount=6_000_000, day=date(2026, 11, 2))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 11, 3),
    )
    with pytest.raises(DomainError):
        services.update_asset(asset, by=owner, books_depreciation=False)
    services.update_asset(asset, by=owner, books_depreciation=True)  # unchanged is fine


def test_a_sale_brings_the_money_in_even_when_the_purchase_was_an_expense(
    shop, owner, cash, equipment, chilonzor, category
):
    """Its purchase is in closed books, so it books no depreciation; sold, the money still
    comes in on the account picked (all of it a gain: the cost was an expense long ago)."""
    txn = buy(shop, owner, cash, equipment, chilonzor)
    finance.lock_period(shop, by=owner, until=date(2026, 6, 30))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 5, 25),
    )
    assert not asset.books_depreciation
    services.dispose(
        asset, by=owner, on=date(2026, 11, 5), kind="sold", amount=D(9_000_000), account=cash
    )
    cash.refresh_from_db()
    assert cash.balance == D("47000000.00")  # 50 000 000 - 12 000 000 + 9 000 000
    assert november(shop) == {
        "income": D("9000000.00"),
        "expense": D("0.00"),
        "profit": D("9000000.00"),
    }


def test_a_sale_goes_only_to_an_account_the_person_may_record_on(
    shop, keeper, owner_api, cash, category, chilonzor
):
    """The keeper manages Chilonzor's assets but holds no Finance permission: a sale's money
    can't be put on an account through the assets page either."""
    fridge = services.create_asset(
        shop,
        by=keeper,
        category=category,
        name="Muzlatgich",
        cost=D(8_400_000),
        life_months=84,
        branch=chilonzor,
        in_service_on=date(2026, 9, 10),
    )
    reply = owner_api(keeper).post(
        f"{base(shop)}/items/{fridge.pk}/dispose/",
        {"on": "2026-11-06", "kind": "sold", "amount": "5000000", "account": cash.pk},
        format="json",
    )
    assert reply.status_code == 400, reply.json()
    cash.refresh_from_db()
    assert cash.balance == D("50000000.00")
    assert not Transaction.objects.filter(company=shop, category__system_code="asset_sale").exists()
