"""Posting depreciation and booking it in Finance: the purchase leaves the P&L, depreciation
comes in month by month, nothing is booked twice, closed books stay closed, and a disposal
shows its gain or loss."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.assets import posting, queries, services
from apps.assets.models import Asset, AssetEvent, DepreciationEntry
from apps.assets.tests.conftest import local
from apps.core.exceptions import DomainError
from apps.finance import queries as finance_queries
from apps.finance import services as finance
from apps.finance.models import Transaction

pytestmark = pytest.mark.django_db


def buy(shop, owner, cash, equipment, chilonzor, *, amount=12_000_000, day=date(2026, 5, 20)):
    return finance.record_transaction(
        shop,
        by=owner,
        kind="expense",
        amount=D(amount),
        occurred_on=day,
        account=cash,
        category=equipment,
        branch=chilonzor,
        description="Muzlatgich Pozis",
    )


def depreciation_rows(shop):
    return Transaction.objects.filter(company=shop, kind=Transaction.Kind.NON_CASH)


def test_a_purchase_leaves_the_pnl_and_comes_back_month_by_month(
    shop, owner, cash, equipment, chilonzor, category
):
    txn = buy(shop, owner, cash, equipment, chilonzor)
    before = finance_queries.totals(shop, date(2026, 5, 1), date(2026, 10, 31), branch_ids=None)
    assert before["expense"] == D("12000000.00")

    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich Pozis",
        purchase_transaction=txn,
        in_service_on=date(2026, 5, 25),
    )
    txn.refresh_from_db()
    assert txn.capitalized
    assert asset.cost == D("12000000.00") and asset.branch == chilonzor
    assert asset.life_months == 84  # the category's default

    # June … October are over: five months posted and booked, one row a month.
    entries = list(asset.entries.order_by("month"))
    assert [entry.month for entry in entries] == [date(2026, month, 1) for month in range(6, 11)]
    assert {entry.amount for entry in entries} == {D("142857.14")}
    assert all(not entry.opening and entry.transaction_id for entry in entries)
    rows = depreciation_rows(shop).order_by("occurred_on")
    assert rows.count() == 5
    assert rows[0].occurred_on == date(2026, 6, 30) and rows[0].account_id is None
    assert rows[0].branch == chilonzor and rows[0].category.system_code == "depreciation"

    after = finance_queries.totals(shop, date(2026, 5, 1), date(2026, 10, 31), branch_ids=None)
    assert after["expense"] == D("714285.70")  # 5 x 142 857.14, the purchase itself left out
    cash.refresh_from_db()
    assert cash.balance == D("38000000.00")  # the money really left; depreciation moved none

    # Booking again books nothing.
    assert posting.book_company(shop) == 0
    assert posting.post_company(shop) == 0
    assert depreciation_rows(shop).count() == 5


def test_the_nightly_job_posts_the_month_that_just_ended(
    shop, owner, cash, equipment, chilonzor, category, freeze
):
    txn = buy(shop, owner, cash, equipment, chilonzor)
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 5, 25),
    )
    freeze(local(date(2026, 12, 1), 1))
    from apps.assets.tasks import post_depreciation

    assert post_depreciation() == 1
    assert asset.entries.filter(month=date(2026, 11, 1)).exists()
    assert depreciation_rows(shop).filter(occurred_on=date(2026, 11, 30)).count() == 1


def test_months_before_it_was_entered_stay_out_of_the_books(shop, owner, category, freeze):
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Eski muzlatgich",
        cost=D(6_000_000),
        life_months=60,
        in_service_on=date(2025, 1, 15),
    )
    entries = asset.entries.all()
    assert entries.count() == 21  # February 2025 … October 2026
    assert all(entry.opening for entry in entries)
    assert depreciation_rows(shop).count() == 0
    assert queries.with_values(Asset.objects.filter(pk=asset.pk)).get().book == D("3900000.00")

    freeze(local(date(2026, 12, 2), 3))
    posting.post_company(shop)
    posting.book_company(shop)
    november = asset.entries.get(month=date(2026, 11, 1))
    assert not november.opening and november.amount == D("100000.00")
    assert depreciation_rows(shop).get().base_amount == D("-100000.00")


def test_the_old_books_sum_opens_the_asset(shop, owner, category):
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Konditsioner",
        cost=D(6_000_000),
        life_months=60,
        in_service_on=date(2024, 1, 10),
        opening_accumulated=D(3_000_000),
    )
    opening = asset.entries.get()
    assert opening.opening and opening.month == date(2026, 10, 1)
    assert opening.amount == D("3000000.00")
    page = queries.detail(asset)
    assert page["values"].book == D("3000000.00")
    planned = [row for row in page["schedule"] if row["state"] == "planned"]
    # February 2024 … October 2026 = 33 months in the old books; 27 months left.
    assert planned[0]["amount"] == D("111111.11")
    assert len(planned) == 27
    assert page["values"].months_used == 33


def test_disposal_books_the_book_value_and_the_sale(
    shop, owner, cash, equipment, chilonzor, category
):
    txn = buy(shop, owner, cash, equipment, chilonzor)
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 5, 25),
    )
    services.dispose(
        asset, by=owner, on=date(2026, 11, 5), kind="sold", amount=D(9_000_000), account=cash
    )
    asset.refresh_from_db()
    assert asset.status == Asset.Status.DISPOSED
    # November is its last month (the next-month rule): six months posted.
    assert asset.entries.count() == 6
    written_off = Transaction.objects.get(company=shop, category__system_code="asset_disposal")
    assert written_off.base_amount == D("-11142857.16")
    sale = Transaction.objects.get(company=shop, category__system_code="asset_sale")
    assert sale.base_amount == D("9000000.00") and sale.account == cash
    event = asset.events.get(kind=AssetEvent.Kind.DISPOSED)
    assert event.details["result"] == "-2142857.16"
    nov = finance_queries.totals(shop, date(2026, 11, 1), date(2026, 11, 30), branch_ids=None)
    assert nov["income"] == D("9000000.00")
    assert nov["expense"] == D("11285714.30")  # November's depreciation + the book value


def test_a_purchase_in_closed_books_stays_an_expense_of_its_month(
    shop, owner, cash, equipment, chilonzor, category
):
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
    txn.refresh_from_db()
    assert not txn.capitalized
    assert not asset.books_depreciation
    assert asset.entries.count() == 5  # tracked for the register
    assert depreciation_rows(shop).count() == 0  # but never counted twice in the P&L


def test_late_months_in_closed_books_land_on_the_first_open_day(shop, owner, category):
    finance.lock_period(shop, by=owner, until=date(2026, 9, 30))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        cost=D(8_400_000),
        life_months=84,
        in_service_on=date(2026, 7, 10),
    )
    # Entered in November: August … October happened before it was entered (opening).
    assert all(entry.opening for entry in asset.entries.all())
    asset.created_at = local(date(2026, 7, 10))
    asset.save(update_fields=["created_at"])
    DepreciationEntry.objects.filter(asset=asset).update(opening=False)
    posting.book_company(shop)
    days = sorted(depreciation_rows(shop).values_list("occurred_on", flat=True))
    assert days == [date(2026, 10, 1), date(2026, 10, 1), date(2026, 10, 31)]


def test_facts_change_freely_until_a_month_is_booked(
    shop, owner, cash, equipment, chilonzor, category
):
    asset = services.create_asset(
        shop, by=owner, category=category, name="Muzlatgich", cost=D(1_000_000), life_months=10
    )
    services.update_asset(asset, by=owner, cost=D(2_000_000), in_service_on=date(2026, 9, 3))
    asset.refresh_from_db()
    assert asset.entries.count() == 1  # October, opening (entered in November)
    assert asset.entries.get().amount == D("200000.00")

    txn = buy(shop, owner, cash, equipment, chilonzor, amount=3_000_000)
    booked = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Pozis",
        purchase_transaction=txn,
        in_service_on=date(2026, 6, 1),
    )
    with pytest.raises(DomainError):
        services.update_asset(booked, by=owner, cost=D(1))
    services.update_asset(booked, by=owner, name="Pozis RK-102", serial="SN-1")
    with pytest.raises(DomainError):
        finance.void_transaction(txn, by=owner, reason="xato")
    with pytest.raises(DomainError):
        services.delete_asset(booked, by=owner)


def test_deleting_an_asset_gives_its_purchase_back_to_the_pnl(
    shop, owner, cash, equipment, chilonzor, category
):
    txn = buy(shop, owner, cash, equipment, chilonzor, day=date(2026, 11, 2))
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 11, 3),
    )
    txn.refresh_from_db()
    assert txn.capitalized
    services.delete_asset(asset, by=owner)
    txn.refresh_from_db()
    assert not txn.capitalized
    assert not Asset.objects.filter(pk=asset.pk).exists()


def test_write_down_and_new_estimate_change_only_later_months(shop, owner, category):
    asset = services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        cost=D(12_000_000),
        life_months=60,
        in_service_on=date(2026, 3, 15),
    )
    asset.created_at = local(date(2026, 3, 15))
    asset.save(update_fields=["created_at"])
    asset.entries.update(opening=False)
    posting.book_company(shop)
    services.write_down(asset, by=owner, on=date(2026, 11, 3), amount=D(1_000_000))
    services.change_estimate(asset, by=owner, on=date(2026, 11, 4), life_months=72)
    page = queries.detail(asset)
    values = page["values"]
    # April … October: 7 x 200 000 posted; 12 000 000 - 1 400 000 - 1 000 000 = 9 600 000.
    assert values.book == D("9600000.00")
    planned = [row for row in page["schedule"] if row["state"] == "planned"]
    assert planned[0]["month"] == date(2026, 11, 1)
    # November runs on the new life (72 - 7 = 65 months left) before the write-down, which
    # lands at the end of its month like an improvement: 10 600 000 / 65.
    assert planned[0]["amount"] == D("163076.92")
    assert planned[0]["closing"] == D("9436923.08")
    # From December the lower value: 9 436 923.08 over 64 months.
    assert planned[1]["amount"] == D("147451.92")
    loss = Transaction.objects.get(company=shop, category__system_code="asset_disposal")
    assert loss.base_amount == D("-1000000.00")


def test_custody_is_given_confirmed_and_taken_back(shop, owner, ali, category):
    asset = services.create_asset(
        shop, by=owner, category=category, name="Noutbuk", cost=D(9_000_000), life_months=48
    )
    assignment = services.issue(asset, by=owner, membership=ali, on=date(2026, 11, 7))
    asset.refresh_from_db()
    assert asset.custodian == ali
    with pytest.raises(DomainError):
        services.issue(asset, by=owner, membership=owner, on=date(2026, 11, 7))
    with pytest.raises(DomainError):
        services.acknowledge(assignment, by=owner)
    services.acknowledge(assignment, by=ali)
    assignment.refresh_from_db()
    assert assignment.acknowledged_at is not None
    assert queries.mine(ali) == [assignment]
    services.take_back(asset, by=owner, on=date(2026, 11, 8), condition="worn")
    asset.refresh_from_db()
    assert asset.custodian is None and asset.condition == "worn"
    assert queries.mine(ali) == []


def test_a_count_finds_what_is_there(shop, owner, ali, chilonzor, category):
    first = services.create_asset(
        shop, by=owner, category=category, name="A", cost=D(1_000_000), branch=chilonzor
    )
    second = services.create_asset(
        shop, by=owner, category=category, name="B", cost=D(1_000_000), branch=chilonzor
    )
    count = services.start_count(shop, by=owner, branch=chilonzor)
    with pytest.raises(DomainError):
        services.start_count(shop, by=owner, branch=chilonzor)
    lines = {line.asset_id: line for line in count.lines.all()}
    services.mark(lines[first.pk], by=ali, result="found")
    services.mark(lines[second.pk], by=ali, result="missing")
    summary = services.close_count(count, by=owner)
    assert summary == {"found": 1, "damaged": 0, "missing": 1, "pending": 0}
    assert first.events.filter(kind=AssetEvent.Kind.COUNTED).exists()
    assert second.events.filter(details__missing=True).exists()


def test_reports_add_up(shop, owner, cash, equipment, chilonzor, yunusobod, category):
    txn = buy(shop, owner, cash, equipment, chilonzor)
    services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich",
        purchase_transaction=txn,
        in_service_on=date(2026, 5, 25),
    )
    services.create_asset(
        shop,
        by=owner,
        category=category,
        name="Muzlatgich 2",
        cost=D(8_400_000),
        life_months=84,
        branch=yunusobod,
        in_service_on=date(2026, 10, 2),
    )
    report = queries.depreciation_report(shop, branch_ids=None, year=2026, group="branch")
    by_branch = {group["name"]: group for group in report["groups"]}
    assert by_branch["Chilonzor"]["total"] == D("999999.98")  # June … December: 7 x 142 857.14
    assert by_branch["Yunusobod"]["total"] == D("200000.00")  # November, December
    summary = queries.summary(shop, branch_ids=None)
    assert summary["count"] == 2
    assert summary["this_month"] == D("242857.14")
    movement = queries.movement(
        shop, branch_ids=None, start=date(2026, 1, 1), end=date(2026, 10, 31)
    )
    line = movement["lines"][0]
    assert line["in_cost"] == D("20400000.00")
    assert line["depreciation"] == D("714285.70")
    assert line["close_book"] == D("19685714.30")
    scoped = queries.summary(shop, branch_ids=[yunusobod.pk])
    assert scoped["count"] == 1
