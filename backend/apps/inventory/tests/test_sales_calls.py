"""The stock contract as the sales lines (J2) call it on main: imported sales with the file's
series, refunds per line, voided invoices, the prescription log from an imported line."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from apps.core.exceptions import DomainError
from apps.inventory import services
from apps.inventory.models import BatchStock, RxRecord, StockBatch, StockLevel, StockMovement
from apps.inventory.services import Allocation
from apps.inventory.tests.conftest import TZ, D, opening

pytestmark = pytest.mark.django_db


def held(branch, batch) -> Decimal:
    row = BatchStock.objects.filter(branch=branch, batch=batch).first()
    return row.quantity if row else Decimal(0)


def test_an_imported_sale_of_a_later_series_is_taken_and_flagged(shop, chilonzor, product):
    early = opening(chilonzor, product, "A", expires_on=date(2026, 12, 31), quantity=10)
    late = opening(chilonzor, product, "B", expires_on=date(2027, 6, 30), quantity=10)
    sold_at = datetime(2026, 11, 6, 15, tzinfo=TZ)
    [taken] = services.deduct(
        chilonzor,
        product,
        D(2),
        by=None,
        document=("sales.sale", 41),
        kind="sale",
        series="B",
        at=sold_at,
    )
    assert taken.batch_id == late.pk and held(chilonzor, early) == 10
    movement = StockMovement.objects.get(batch=late, kind="sale")
    assert movement.reason == "not_fefo" and movement.at == sold_at
    # Live at the counter the strict rule holds.
    with pytest.raises(DomainError):
        services.deduct(chilonzor, product, 1, by=None, document=("sales.sale", 42), series="B")


def test_a_voided_invoice_line_that_had_no_stock_takes_its_shortfall_back(
    shop, chilonzor, product, rx
):
    opening(chilonzor, rx, "R", expires_on=date(2027, 6, 30), quantity=2)
    document = ("sales.invoice", 7)
    services.deduct(chilonzor, product, D(3), by=None, document=document)  # nothing on hand
    rx_alloc = services.deduct(chilonzor, rx, D(5), by=None, document=document)
    assert StockLevel.objects.get(branch=chilonzor, product=product).shortfall == 3
    # J2 voids line by line: the product's line has no batch at all.
    services.restock(
        chilonzor, [Allocation(None, D(3), None)], by=None, document=document, status="sellable"
    )
    services.restock(chilonzor, rx_alloc, by=None, document=document, status="sellable")
    level = StockLevel.objects.get(branch=chilonzor, product=product)
    assert level.quantity == 0 and level.shortfall == 0
    rx_level = StockLevel.objects.get(branch=chilonzor, product=rx)
    assert rx_level.quantity == 2 and rx_level.shortfall == 0


def test_refunds_per_line(shop, chilonzor, product):
    batch = opening(chilonzor, product, "A", expires_on=date(2027, 6, 30), quantity=10)
    sold = services.deduct(chilonzor, product, D(4), by=None, document=("sales.sale", 50))
    services.restock(chilonzor, sold, by=None, document=("sales.sale", 51), kind="refund")
    twin = StockBatch.objects.get(origin=batch)
    assert held(chilonzor, twin) == 4
    # A refund whose sale the file doesn't name can't say which item it was.
    with pytest.raises(DomainError, match="doesn't say which sale"):
        services.restock(
            chilonzor, [Allocation(None, D(1), None)], by=None, document=("sales.sale", 52)
        )
    services.restock_product(
        chilonzor, product, D(1), by=None, document=("sales.sale", 52), kind="refund"
    )
    assert held(chilonzor, twin) == 5


def test_the_prescription_log_from_an_imported_line(shop, chilonzor, rx):
    record = services.record_rx(
        by=None,
        branch=chilonzor,
        product=rx,
        quantity=D(2),
        document=("sales.saleline", 812),
        prescription_number="148-1203",
    )
    assert record is not None and record.prescriber == "" and record.prescribed_on is None
    assert RxRecord.objects.get().document_id == 812
