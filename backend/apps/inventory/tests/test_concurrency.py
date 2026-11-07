"""Stock changes only under row locks: two parallel deductions of the last five parts give
them to one sale and a shortfall to the other (§14.6.4 acceptance)."""

import threading
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection

from apps.companies.tests.factories import BranchFactory, CompanyFactory
from apps.inventory import services
from apps.inventory.models import BatchStock, StockLevel
from apps.inventory.tests.factories import ProductFactory


@pytest.mark.django_db(transaction=True)
def test_two_sales_of_the_last_five_parts():
    company = CompanyFactory(features=["stock"])
    branch = BranchFactory(company=company)
    product = ProductFactory(company=company, units_per_pack=1)
    batch = services.add_opening_stock(
        branch,
        by=None,
        product=product,
        series="LAST",
        expires_on=date(2030, 1, 1),
        quantity=Decimal(5),
        unit_cost=Decimal(1000),
    )
    results = []
    errors = []
    start = threading.Barrier(2)

    def sell(document_id):
        try:
            start.wait(timeout=10)
            results.append(
                services.deduct(
                    branch, product, Decimal(5), by=None, document=("sales.sale", document_id)
                )
            )
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=sell, args=(number,)) for number in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    got = sorted((allocation[0].batch_id is None, allocation) for allocation in results)
    from_batch = [row for shortfall, row in got if not shortfall]
    from_nothing = [row for shortfall, row in got if shortfall]
    assert len(from_batch) == 1 and len(from_nothing) == 1
    assert from_batch[0] == [services.Allocation(batch.pk, Decimal(5), Decimal("1000.00"))]
    assert from_nothing[0] == [services.Allocation(None, Decimal(5), None)]
    assert BatchStock.objects.get(batch=batch).quantity == 0
    level = StockLevel.objects.get(branch=branch, product=product)
    assert level.quantity == -5 and level.shortfall == 5
