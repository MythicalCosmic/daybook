"""The stock contract (docs/PLAN-OWNER.md §14.6.3): the signatures W2.a fixed, which J2, S, J3
and N call. J1 filled the bodies and keeps these exactly; what they do is tested here and in
test_golden.py."""

import inspect
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.inventory import queries, services
from apps.inventory.models import ProductCode, StockCount
from apps.inventory.tests.factories import ProductFactory

K = inspect.Parameter.KEYWORD_ONLY
P = inspect.Parameter.POSITIONAL_OR_KEYWORD
VAR = inspect.Parameter.VAR_KEYWORD

# name -> [(parameter, kind, default or EMPTY)]
EMPTY = inspect.Parameter.empty
CONTRACT = {
    services.deduct: [
        ("branch", P, EMPTY),
        ("product", P, EMPTY),
        ("quantity", P, EMPTY),
        ("by", K, EMPTY),
        ("document", K, EMPTY),
        ("kind", K, "sale"),
        ("series", K, None),
        ("reason", K, ""),
        ("at", K, None),
    ],
    services.restock: [
        ("branch", P, EMPTY),
        ("allocations", P, EMPTY),
        ("by", K, EMPTY),
        ("document", K, EMPTY),
        ("kind", K, "refund"),
        ("status", K, "quarantine"),
    ],
    services.start_count: [
        ("branch", P, EMPTY),
        ("by", K, EMPTY),
        ("kind", K, "partial"),
        ("category", K, None),
    ],
    services.remember_code: [
        ("product", P, EMPTY),
        ("by", K, EMPTY),
        ("kind", K, EMPTY),
        ("code", K, EMPTY),
        ("supplier", K, None),
    ],
    services.record_rx: [
        ("by", K, EMPTY),
        ("branch", K, EMPTY),
        ("product", K, EMPTY),
        ("quantity", K, EMPTY),
        ("document", K, None),
        ("fields", VAR, EMPTY),
    ],
    services.journal_pdf: [
        ("kind", P, EMPTY),
        ("branch", K, EMPTY),
        ("month", K, EMPTY),
        ("product", K, None),
        ("language", K, EMPTY),
    ],
    queries.match_code: [("company", P, EMPTY), ("code", P, EMPTY)],
    queries.lookup: [
        ("company", P, EMPTY),
        ("q", P, EMPTY),
        ("branch_ids", K, EMPTY),
        ("limit", K, 20),
    ],
    queries.levels: [("company", P, EMPTY), ("branch_ids", K, EMPTY), ("low", K, False)],
    queries.batches: [
        ("company", P, EMPTY),
        ("branch_ids", K, EMPTY),
        ("product_id", K, None),
        ("expiring_within", K, None),
        ("status", K, None),
    ],
    queries.expiring: [
        ("company", P, EMPTY),
        ("branch_ids", K, EMPTY),
        ("within_days", K, EMPTY),
        ("as_of", K, EMPTY),
    ],
    queries.movements: [
        ("company", P, EMPTY),
        ("start", P, EMPTY),
        ("end", P, EMPTY),
        ("branch_ids", K, EMPTY),
        ("kinds", K, None),
    ],
    queries.velocity: [("company", P, EMPTY), ("branch_ids", K, EMPTY), ("days", K, 28)],
    queries.analogs: [("product", P, EMPTY), ("branch_ids", K, EMPTY)],
    queries.price_cap: [("product", P, EMPTY), ("batch", K, None), ("unit_cost", K, None)],
    queries.mandatory_missing: [("company", P, EMPTY), ("branch_ids", K, EMPTY), ("day", K, EMPTY)],
    queries.last_applied_count: [("branch", P, EMPTY), ("kind", K, "handover")],
}


@pytest.mark.parametrize("function", list(CONTRACT), ids=lambda f: f.__qualname__)
def test_the_signatures_stay_as_w2a_fixed_them(function):
    found = [
        (name, param.kind, param.default)
        for name, param in inspect.signature(function).parameters.items()
    ]
    assert found == CONTRACT[function]


def test_an_allocation_is_batch_quantity_and_cost():
    assert services.Allocation._fields == ("batch_id", "quantity", "unit_cost")


@pytest.mark.django_db
def test_the_catalogue_answers_codes_and_searches(company):
    product = ProductFactory(
        company=company, name="Amoksitsillin 500 mg kapsula №16", inn="amoxicillin", sku="AMX-500"
    )
    ProductFactory(company=company, name="Old one", inn="amoxicillin", is_active=False)

    assert queries.match_code(company, product.barcode) == product
    assert queries.match_code(company, " AMX-500 ") == product
    assert queries.match_code(company, "") is None
    [row] = queries.lookup(company, "amoxi", branch_ids=None)
    assert row["id"] == product.pk and row["quantity"] == 0
    assert queries.lookup(company, "kapsula", branch_ids=None)[0]["name"] == product.name

    services.remember_code(product, by=None, kind="pos", code="KASSA-77")
    services.remember_code(product, by=None, kind="pos", code="KASSA-77")
    assert ProductCode.objects.filter(product=product).count() == 1
    assert queries.match_code(company, "KASSA-77") == product
    assert queries.lookup(company, "KASSA-77", branch_ids=None)[0]["id"] == product.pk


@pytest.mark.django_db
def test_deductions_counts_and_queries_work_on_real_stock(company):
    branch = BranchFactory(company=company)
    other = BranchFactory(company=company)
    product = ProductFactory(company=company, units_per_pack=2)
    soon = date.today() + timedelta(days=20)
    batch = services.add_opening_stock(
        branch,
        by=None,
        product=product,
        series="X1",
        expires_on=soon,
        quantity=Decimal("4"),
        unit_cost=Decimal("10000"),
    )

    [allocation] = services.deduct(
        branch, product, Decimal("3"), by=None, document=("sales.sale", 1)
    )
    assert allocation == services.Allocation(batch.pk, Decimal("3"), Decimal("5000.00"))
    assert services.record_rx(by=None, branch=branch, product=product, quantity=1) is None
    count = services.start_count(branch, by=None)
    assert count.status == StockCount.Status.OPEN and count.lines.count() == 1
    with pytest.raises(DomainError):
        services.start_count(branch, by=None)
    [row] = queries.expiring(company, branch_ids=None, within_days=30, as_of=None)
    assert row["batch_id"] == batch.pk and row["quantity"] == 1 and row["value"] == 5000
    assert queries.expiring(company, branch_ids=[other.pk], within_days=30, as_of=None) == []
    assert queries.batches(company, branch_ids=None, product_id=product.pk).get() == batch
    assert queries.batches(company, branch_ids=[other.pk]).count() == 0
    assert queries.velocity(company, branch_ids=None)[(branch.pk, product.pk)] == Decimal("0.107")
    assert queries.levels(company, branch_ids=[branch.pk]).get().quantity == 1
    assert queries.last_applied_count(branch) is None
    assert (
        queries.movements(
            company, date.today() - timedelta(days=1), date.today(), branch_ids=[branch.pk]
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_the_legal_price_cap_of_a_pack(company):
    """§14.4 rows 13-14, §14.6.2 golden: Rx cost 10 340 → cap 12 408; socially significant
    11 374; never above the reference price; OTC has none."""
    from apps.inventory.tests.factories import StockBatchFactory

    rx = ProductFactory(company=company, rx_required=True)
    batch = StockBatchFactory(product=rx, unit_cost=Decimal("10340.00"))
    assert queries.price_cap(rx, batch=batch) == Decimal("12408.00")
    assert queries.price_cap(rx, unit_cost=Decimal("10340")) == Decimal("12408.00")
    social = ProductFactory(company=company, rx_required=True, socially_significant=True)
    assert queries.price_cap(social, unit_cost=Decimal("10340")) == Decimal("11374.00")
    capped = ProductFactory(company=company, rx_required=True, reference_price=Decimal("12000"))
    assert queries.price_cap(capped, unit_cost=Decimal("10340")) == Decimal("12000")
    assert queries.price_cap(capped) == Decimal("12000")
    assert queries.price_cap(ProductFactory(company=company, rx_required=True)) is None
    assert queries.price_cap(ProductFactory(company=company), unit_cost=Decimal("10340")) is None
