"""Read functions of stock, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).

The stock contract (docs/PLAN-OWNER.md §14.6.3) has its final signatures from W2.a. `match_code`,
`lookup` and `price_cap` work on the catalogue from day one (barcode and SKU; quantities are None
until J1 keeps stock; the caps at the law's defaults until J1's settings carry them); the others
answer empty until J1 fills them, keeping every signature.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q

from apps.inventory.models import Product, StockBatch


def match_code(company, code: str) -> Product | None:
    """The product a barcode, SKU, POS or supplier code names."""
    code = (code or "").strip()
    if not code:
        return None
    return (
        Product.objects.for_company(company)
        .filter(Q(barcode=code) | Q(sku=code))
        .order_by("-is_active", "pk")
        .first()
    )


def lookup(company, q: str, *, branch_ids: list[int] | None, limit: int = 20) -> list[dict]:
    """Products by name, trade name, INN or barcode, for the counter and the dashboard."""
    q = (q or "").strip()
    if not q:
        return []
    found = (
        Product.objects.for_company(company)
        .filter(is_active=True)
        .filter(
            Q(name__icontains=q)
            | Q(trade_name__icontains=q)
            | Q(inn__icontains=q)
            | Q(barcode=q)
            | Q(sku=q)
        )
        .order_by("name", "pk")[:limit]
    )
    return [
        {
            "id": product.pk,
            "name": product.name,
            "trade_name": product.trade_name,
            "inn": product.inn,
            "barcode": product.barcode,
            "rx_required": product.rx_required,
            "sale_price": product.sale_price,
            "quantity": None,  # J1: parts at the person's branches
        }
        for product in found
    ]


def levels(company, *, branch_ids: list[int] | None, low: bool = False) -> list:
    return []


def batches(
    company,
    *,
    branch_ids: list[int] | None,
    product_id: int | None = None,
    expiring_within: int | None = None,
    status: str | None = None,
):
    return StockBatch.objects.none()


def expiring(company, *, branch_ids: list[int] | None, within_days: int, as_of: date) -> list[dict]:
    """Batches expiring within `within_days` of `as_of`, with their value at cost and retail."""
    return []


def movements(company, start: date, end: date, *, branch_ids: list[int] | None, kinds=None) -> list:
    """Stock movements in [start, end]: J3's and N's source (a QuerySet from J1)."""
    return []


def velocity(
    company, *, branch_ids: list[int] | None, days: int = 28
) -> dict[tuple[int, int], Decimal]:
    """(branch id, product id) → parts sold a day over the last `days`."""
    return {}


# The legal Rx caps the stub uses until J1's StockSettings carries them (§14.4 row 13-14, §14.21).
RX_MAX_MARKUP = Decimal("20.00")
SOCIAL_MAX_MARKUP = Decimal("10.00")


def price_cap(product, *, batch=None, unit_cost: Decimal | None = None) -> Decimal | None:
    """The legal maximum retail price of one pack, or None when the law sets none (an OTC item,
    or a prescription item with neither a cost nor a reference price). The cap is the batch's
    purchase price (or `unit_cost`) times one plus the Rx markup cap (the socially significant
    one when it applies), never above the product's reference price. Unrounded: J1's own prices
    round down below it, so a sale at the batch price never breaches it. J2's cap check reads it."""
    if not product.rx_required:
        return None
    caps = []
    cost = batch.unit_cost if batch is not None else unit_cost
    if cost is not None:
        markup = SOCIAL_MAX_MARKUP if product.socially_significant else RX_MAX_MARKUP
        caps.append((Decimal(cost) * (1 + markup / 100)).quantize(Decimal("0.01")))
    if product.reference_price is not None:
        caps.append(product.reference_price)
    return min(caps) if caps else None


def analogs(product, *, branch_ids: list[int] | None) -> list[dict]:
    """Products with the same INN, dosage form and strength (a catalogue fact, never advice)."""
    return []


def mandatory_missing(company, *, branch_ids: list[int] | None, day: date) -> list[dict]:
    """Mandatory-list products with no sellable stock at a pharmacy branch."""
    return []


def last_applied_count(branch, *, kind: str = "handover") -> datetime | None:
    """When the branch's last count of `kind` was applied (S's handover blocker)."""
    return None
