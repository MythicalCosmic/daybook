"""The golden cases of docs/PLAN-OWNER.md §14.6.2 as exact tests: parts and part price, FEFO,
negative stock, retail prices and the legal caps."""

from datetime import date
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.inventory import conf, pricing, queries, services
from apps.inventory.models import BatchStock, StockBatch, StockLevel, StockMovement
from apps.inventory.services import Allocation
from apps.inventory.tests.conftest import D, line, opening, receive
from apps.inventory.tests.factories import ProductFactory, StockBatchFactory

pytestmark = pytest.mark.django_db


def held(branch, batch) -> Decimal:
    row = BatchStock.objects.filter(branch=branch, batch=batch).first()
    return row.quantity if row else Decimal(0)


def level(branch, product) -> StockLevel:
    return StockLevel.objects.get(branch=branch, product=product)


# Parts and part price ---------------------------------------------------------------------


def test_part_prices(shop):
    settings = conf.get_settings(shop)
    assert settings.price_rounding == 100
    two = ProductFactory(company=shop, units_per_pack=2, sale_price=D(24000))
    assert pricing.part_price(two, settings=settings) == D("12000.00")
    ten = ProductFactory(company=shop, units_per_pack=10, sale_price=D(25150))
    assert pricing.part_price(ten, settings=settings) == D("2600.00")
    rx = ProductFactory(company=shop, units_per_pack=3, rx_required=True)
    batch = StockBatchFactory(product=rx, unit_cost=D(10340), retail_price=D(12400))
    # 12 400 / 3 = 4 133.33; up would be 4 200 > the part cap 12 408 / 3 = 4 136: down.
    assert pricing.part_price(rx, batch, settings=settings) == D("4100.00")
    fixed = ProductFactory(company=shop, units_per_pack=10, part_price=D(2700))
    assert pricing.part_price(fixed, settings=settings) == D(2700)


def test_quantities_are_parts_of_packs(shop, owner, chilonzor, supplier, product):
    receipt = receive(shop, owner, chilonzor, supplier, [line(product, packs=3)])
    [row] = receipt.lines.all()
    assert row.quantity == D(6)  # 3 packs of 2 blisters
    assert level(chilonzor, product).quantity == D(6)
    from apps.inventory.journals import packs_and_parts

    assert packs_and_parts(product, D(7)) == "3 packs 1 blister"
    with pytest.raises(DomainError):
        services.add_line(receipt, by=owner, **line(product, packs=D("0.25")))


# FEFO --------------------------------------------------------------------------------------


def test_fefo_takes_the_earliest_expiry_first(shop, chilonzor, product):
    a = opening(chilonzor, product, "A", expires_on=date(2026, 12, 31), quantity=10, cost=10000)
    b = opening(chilonzor, product, "B", expires_on=date(2027, 3, 31), quantity=20, cost=12000)
    allocations = services.deduct(chilonzor, product, D(15), by=None, document=("sales.sale", 1))
    assert allocations == [
        Allocation(a.pk, D(10), D("5000.00")),
        Allocation(b.pk, D(5), D("6000.00")),
    ]
    assert held(chilonzor, a) == 0 and held(chilonzor, b) == 15
    cost = sum(row.quantity * row.unit_cost for row in allocations)
    assert cost == 10 * D(5000) + 5 * D(6000)
    assert level(chilonzor, product).quantity == 15
    sales = StockMovement.objects.filter(kind="sale", product=product)
    assert sum(row.quantity for row in sales) == -15
    assert {row.document_type for row in sales} == {"sales.sale"}


def test_blocked_and_expired_batches_are_never_allocated(shop, chilonzor, product):
    expired = opening(chilonzor, product, "OLD", expires_on=date(2026, 11, 6), quantity=5)
    held_back = opening(chilonzor, product, "Q", expires_on=date(2026, 11, 30), quantity=5)
    recalled = opening(chilonzor, product, "R", expires_on=date(2026, 12, 1), quantity=5)
    good = opening(chilonzor, product, "OK", expires_on=date(2027, 6, 1), quantity=5)
    services.quarantine(held_back, by=None, reason="check")
    StockBatch.objects.filter(pk=recalled.pk).update(status=StockBatch.Status.RECALLED)
    today_is_last_day = opening(
        chilonzor, product, "LAST", expires_on=date(2026, 11, 7), quantity=1
    )

    allocations = services.deduct(chilonzor, product, 6, by=None, document=("sales.sale", 2))
    assert [row.batch_id for row in allocations] == [today_is_last_day.pk, good.pk]
    assert held(chilonzor, expired) == 5 and held(chilonzor, held_back) == 5
    assert held(chilonzor, recalled) == 5 and held(chilonzor, good) == 0


def test_naming_a_later_series_needs_a_reason(shop, chilonzor, product):
    a = opening(chilonzor, product, "A", expires_on=date(2026, 12, 31), quantity=10)
    b = opening(chilonzor, product, "B", expires_on=date(2027, 3, 31), quantity=10)
    with pytest.raises(DomainError, match="expires earlier"):
        services.deduct(chilonzor, product, 2, by=None, document=("sales.sale", 3), series="B")
    [taken] = services.deduct(
        chilonzor,
        product,
        2,
        by=None,
        document=("sales.sale", 3),
        series="B",
        reason="customer",
    )
    assert taken.batch_id == b.pk
    assert StockMovement.objects.get(batch=b, kind="sale").reason == "customer"
    settings = conf.get_settings(shop)
    settings.fefo_strict = False
    settings.save()
    [taken] = services.deduct(
        chilonzor, product, 1, by=None, document=("sales.sale", 4), series="B"
    )
    assert taken.batch_id == b.pk and held(chilonzor, a) == 10


def test_a_sale_of_an_expired_series_is_recorded_and_flagged(shop, chilonzor, product):
    old = opening(chilonzor, product, "OLD", expires_on=date(2026, 10, 31), quantity=4)
    opening(chilonzor, product, "NEW", expires_on=date(2027, 10, 31), quantity=4)
    [taken] = services.deduct(
        chilonzor, product, 1, by=None, document=("sales.sale", 5), series="OLD"
    )
    assert taken.batch_id == old.pk
    assert StockMovement.objects.get(batch=old, kind="sale").reason == "expired"
    assert (
        queries.sold_after_expiry(
            shop, date(2026, 11, 1), date(2026, 11, 30), branch_ids=None
        ).count()
        == 1
    )
    with pytest.raises(DomainError):
        services.deduct(
            chilonzor, product, 1, by=None, document=("x.y", 1), series="OLD", kind="writeoff"
        )


# Negative stock ------------------------------------------------------------------------------


def test_a_shortfall_waits_for_the_next_delivery(shop, owner, chilonzor, supplier, product):
    a = opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=5)
    allocations = services.deduct(chilonzor, product, 8, by=None, document=("sales.sale", 6))
    assert allocations == [Allocation(a.pk, D(5), D("5170.00")), Allocation(None, D(3), None)]
    row = level(chilonzor, product)
    assert row.quantity == -3 and row.shortfall == 3

    receipt = receive(shop, owner, chilonzor, supplier, [line(product, "NEW", packs=5)])
    batch = StockBatch.objects.get(receipt_line__receipt=receipt)
    row = level(chilonzor, product)
    assert row.quantity == 7 and row.shortfall == 0  # 10 parts arrived, 3 were already sold
    assert held(chilonzor, batch) == 7
    pair = StockMovement.objects.filter(
        kind="count_adjustment", document_type="inventory.goodsreceipt", document_id=receipt.pk
    )
    assert {(row.batch_id, row.quantity) for row in pair} == {(batch.pk, D(-3)), (None, D(3))}


def test_without_negative_stock_a_short_sale_is_refused(shop, chilonzor, product):
    settings = conf.get_settings(shop)
    settings.allow_negative = False
    settings.save()
    opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=5)
    with pytest.raises(DomainError, match="Only 5"):
        services.deduct(chilonzor, product, 8, by=None, document=("sales.sale", 7))
    assert level(chilonzor, product).quantity == 5


def test_a_service_has_no_stock(shop, chilonzor):
    service = ProductFactory(company=shop, kind="service", track_stock=False)
    assert services.deduct(chilonzor, service, 1, by=None, document=("sales.sale", 8)) == [
        Allocation(None, D(1), None)
    ]
    assert not StockMovement.objects.exists()


# Refunds ---------------------------------------------------------------------------------------


def test_a_refund_lands_in_quarantine_and_a_voided_invoice_goes_back_on_sale(
    shop, chilonzor, product
):
    a = opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=10)
    sold = services.deduct(chilonzor, product, 4, by=None, document=("sales.sale", 9))
    services.restock(chilonzor, sold[:1], by=None, document=("sales.sale", 10))
    twin = StockBatch.objects.get(origin=a)
    assert twin.status == StockBatch.Status.QUARANTINE and twin.series == "A"
    assert held(chilonzor, twin) == 4 and held(chilonzor, a) == 6
    assert StockBatch.objects.get(pk=a.pk).status == StockBatch.Status.SELLABLE

    invoice = services.deduct(chilonzor, product, 2, by=None, document=("sales.invoice", 1))
    services.restock(chilonzor, invoice, by=None, document=("sales.invoice", 1), status="sellable")
    assert held(chilonzor, a) == 6
    assert level(chilonzor, product).quantity == 10


def test_a_refund_without_its_batch_books_against_the_last_one_sold(shop, chilonzor, product):
    opening(chilonzor, product, "A", expires_on=date(2027, 1, 31), quantity=2)
    sold = services.deduct(chilonzor, product, 5, by=None, document=("sales.sale", 11))
    assert sold[-1].batch_id is None
    services.restock(chilonzor, sold, by=None, document=("sales.invoice", 2), status="sellable")
    row = level(chilonzor, product)
    assert row.quantity == 2 and row.shortfall == 0


# Prices and the legal caps ----------------------------------------------------------------------


def test_retail_prices_and_caps(shop):
    settings = conf.get_settings(shop)
    otc = ProductFactory(company=shop)
    assert pricing.suggest_price(otc, D(10340), settings) == (D("13000.00"), False)
    rx = ProductFactory(company=shop, rx_required=True)
    assert pricing.suggest_price(rx, D(10340), settings) == (D("12400.00"), True)
    capped = ProductFactory(company=shop, rx_required=True, reference_price=D(12000))
    assert pricing.suggest_price(capped, D(10340), settings) == (D("12000.00"), True)
    social = ProductFactory(company=shop, rx_required=True, socially_significant=True)
    assert pricing.suggest_price(social, D(10340), settings) == (D("11300.00"), True)


def test_the_caps_follow_the_company_settings(shop, owner):
    rx = ProductFactory(company=shop, rx_required=True)
    assert queries.price_cap(rx, unit_cost=D(10340)) == D("12408.00")
    services.update_settings(shop, by=owner, rx_max_markup_percent=D(15))
    assert queries.price_cap(rx, unit_cost=D(10340)) == D("11891.00")


def test_receipt_prices_respect_the_cap(shop, owner, chilonzor, supplier, rx, product):
    receipt = receive(
        shop,
        owner,
        chilonzor,
        supplier,
        [line(rx, "RX1", cost=10340), line(product, "OTC1", cost=10340)],
    )
    prices = {batch.product_id: batch.retail_price for batch in StockBatch.objects.all()}
    assert prices == {rx.pk: D("12400.00"), product.pk: D("13000.00")}
    assert all("over_price_cap" not in row.warnings for row in receipt.lines.all())

    typed = receive(
        shop,
        owner,
        chilonzor,
        supplier,
        [line(rx, "RX2", cost=10340, retail_price=D(14000))],
        invoice="N-2",
    )
    [row] = typed.lines.all()
    assert row.retail_price == D("12400.00") and "over_price_cap" in row.warnings


def test_an_rx_batch_is_never_priced_above_its_cap(shop, owner, chilonzor, rx):
    batch = opening(chilonzor, rx, "RX", expires_on=date(2027, 5, 1), quantity=4)
    with pytest.raises(DomainError, match="legal maximum"):
        services.set_price(batch, by=owner, price=D(12500))
    services.set_price(batch, by=owner, price=D(12400))
    settings = conf.get_settings(shop)
    settings.cap_enforced = False
    settings.save()
    assert services.set_price(batch, by=owner, price=D(12500)).retail_price == D(12500)
