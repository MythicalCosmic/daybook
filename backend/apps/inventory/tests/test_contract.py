"""The stock contract (docs/PLAN-OWNER.md §14.6.3): the signatures W2.a fixed, which J2, S, J3
and N call. J1 fills the bodies and keeps these exactly; the stub behaviour is tested here
until then (J1 replaces those tests with real ones)."""

import inspect
from decimal import Decimal

import pytest

from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.inventory import queries, services
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
    assert row["id"] == product.pk and row["quantity"] is None
    assert queries.lookup(company, "kapsula", branch_ids=None)[0]["name"] == product.name


@pytest.mark.django_db
def test_until_the_stock_module_deductions_move_nothing(company):
    branch = BranchFactory(company=company)
    product = ProductFactory(company=company)

    [allocation] = services.deduct(
        branch, product, Decimal("3"), by=None, document=("sales.sale", 1)
    )
    assert allocation == services.Allocation(None, Decimal("3"), None)
    assert services.record_rx(by=None, branch=branch, product=product, quantity=1) is None
    with pytest.raises(DomainError):
        services.start_count(branch, by=None)
    assert queries.expiring(company, branch_ids=None, within_days=30, as_of=None) == []


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
