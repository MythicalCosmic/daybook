"""Read functions of stock, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`): None is
every branch, an empty list is none.

The stock contract (docs/PLAN-OWNER.md §14.6.3) keeps the signatures W2.a fixed: `match_code`,
`lookup`, `levels`, `batches`, `expiring`, `movements`, `velocity`, `price_cap`, `analogs`,
`mandatory_missing`, `last_applied_count`. Quantities are parts; values are in the company's
base currency, at the batches' cost (`value`) and at their retail price (`retail_value`).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F, Min, OuterRef, Q, QuerySet, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.companies.models import BranchKind
from apps.core.money import quantize
from apps.inventory import engine
from apps.inventory.models import (
    BatchStock,
    GoodsReceipt,
    Product,
    ProductCode,
    RecallNotice,
    StockBatch,
    StockCount,
    StockLevel,
    StockMovement,
    StockTransfer,
    WriteOff,
)

ZERO = Decimal(0)


def _scope(rows: QuerySet, branch_ids: list[int] | None, field: str = "branch") -> QuerySet:
    if branch_ids is None:
        return rows
    return rows.filter(**{f"{field}__in": branch_ids})


def match_code(company, code: str) -> Product | None:
    """The product a barcode, SKU, POS or supplier code names."""
    code = (code or "").strip()
    if not code:
        return None
    found = (
        Product.objects.for_company(company)
        .filter(Q(barcode=code) | Q(sku=code))
        .order_by("-is_active", "pk")
        .first()
    )
    if found is not None:
        return found
    other = (
        ProductCode.objects.for_company(company)
        .filter(code=code)
        .select_related("product")
        .order_by("-product__is_active", "pk")
        .first()
    )
    return other.product if other is not None else None


def _search(company, q: str) -> QuerySet:
    q = (q or "").strip()
    rows = Product.objects.for_company(company)
    if not q:
        return rows.none()
    coded = ProductCode.objects.for_company(company).filter(code=q).values("product_id")
    return rows.filter(
        Q(name__icontains=q)
        | Q(trade_name__icontains=q)
        | Q(inn__icontains=q)
        | Q(barcode=q)
        | Q(sku=q)
        | Q(pk__in=coded)
    )


def quantities(company, product_ids, *, branch_ids: list[int] | None) -> dict[int, Decimal]:
    """Product id → parts on hand at the branches (less any shortfall)."""
    rows = _scope(
        StockLevel.objects.filter(product__company=company, product_id__in=list(product_ids)),
        branch_ids,
    )
    return {
        row["product_id"]: row["total"] or ZERO
        for row in rows.values("product_id").annotate(total=Sum("quantity"))
    }


def lookup(company, q: str, *, branch_ids: list[int] | None, limit: int = 20) -> list[dict]:
    """Products by name, trade name, INN, barcode or another code, for the counter and the
    dashboard, with the parts on hand at `branch_ids`."""
    found = list(_search(company, q).filter(is_active=True).order_by("name", "pk")[:limit])
    held = quantities(company, [product.pk for product in found], branch_ids=branch_ids)
    return [
        {
            "id": product.pk,
            "name": product.name,
            "trade_name": product.trade_name,
            "inn": product.inn,
            "barcode": product.barcode,
            "rx_required": product.rx_required,
            "control_class": product.control_class,
            "storage": product.storage,
            "units_per_pack": product.units_per_pack,
            "part_label": product.part_label,
            "sale_price": product.sale_price,
            "quantity": held.get(product.pk, ZERO) if product.track_stock else None,
        }
        for product in found
    ]


def levels(company, *, branch_ids: list[int] | None, low: bool = False):
    """Stock per branch and product (`StockLevel`, with `product` and `branch` loaded).
    `low`: only those below their minimum."""
    rows = _scope(
        StockLevel.objects.filter(product__company=company).select_related("product", "branch"),
        branch_ids,
    )
    if low:
        rows = rows.filter(min_qty__isnull=False, quantity__lt=F("min_qty"))
    return rows.order_by("product__name", "branch__order", "branch_id")


def batches(
    company,
    *,
    branch_ids: list[int] | None,
    product_id: int | None = None,
    expiring_within: int | None = None,
    status: str | None = None,
):
    """Batches with parts on hand at `branch_ids`, earliest expiry first, each with `on_hand`
    (parts there). `status`: sellable, quarantine, recalled, or expired (derived)."""
    held = _scope(BatchStock.objects.filter(batch=OuterRef("pk")), branch_ids)
    on_hand = Subquery(held.values("batch").annotate(total=Sum("quantity")).values("total")[:1])
    today = engine.local_today(company)
    rows = (
        StockBatch.objects.for_company(company)
        .annotate(on_hand=Coalesce(on_hand, ZERO))
        .filter(on_hand__gt=0)
        .select_related("product", "supplier")
    )
    if product_id is not None:
        rows = rows.filter(product_id=product_id)
    if expiring_within is not None:
        rows = rows.filter(expires_on__lte=today + timedelta(days=expiring_within))
    if status == "expired":
        rows = rows.filter(expires_on__lt=today)
    elif status == StockBatch.Status.SELLABLE:
        rows = rows.filter(status=status, expires_on__gte=today)
    elif status:
        rows = rows.filter(status=status)
    return rows.order_by("expires_on", "created_at", "pk")


def stock_rows(company, *, branch_ids: list[int] | None, product_id=None, batch_ids=None):
    """`BatchStock` rows with parts on hand (branch, batch and product loaded)."""
    rows = _scope(
        BatchStock.objects.filter(batch__company=company, quantity__gt=0).select_related(
            "branch", "batch__product", "batch__supplier"
        ),
        branch_ids,
    )
    if product_id is not None:
        rows = rows.filter(batch__product_id=product_id)
    if batch_ids is not None:
        rows = rows.filter(batch_id__in=batch_ids)
    return rows.order_by("batch__expires_on", "batch__product__name", "branch_id")


def expiring(company, *, branch_ids: list[int] | None, within_days: int, as_of: date) -> list[dict]:
    """What expires within `within_days` of `as_of` (or already expired), per branch and batch,
    with its value at cost and at retail."""
    as_of = as_of or engine.local_today(company)
    until = as_of + timedelta(days=within_days)
    rows = stock_rows(company, branch_ids=branch_ids).filter(batch__expires_on__lte=until)
    found = []
    for stock in rows:
        batch = stock.batch
        found.append(
            {
                "id": stock.pk,
                "batch_id": batch.pk,
                "branch_id": stock.branch_id,
                "branch": stock.branch.name,
                "product_id": batch.product_id,
                "product": batch.product.name,
                "series": batch.series,
                "expires_on": batch.expires_on,
                "days_left": (batch.expires_on - as_of).days,
                "expired": batch.expires_on < as_of,
                "status": batch.status,
                "quantity": stock.quantity,
                "units_per_pack": batch.product.units_per_pack,
                "value": engine.value_of(batch, stock.quantity),
                "retail_value": engine.retail_value_of(batch, stock.quantity),
            }
        )
    return found


def expiry_board(company, *, branch_ids: list[int] | None, within: int, as_of: date) -> dict:
    """The expiry board: expired and the 30 / 60 / 90-day buckets (as many as `within`
    covers), each with its batches, count and value."""
    rows = expiring(company, branch_ids=branch_ids, within_days=within, as_of=as_of)
    edges = [step for step in (30, 60, 90) if step <= max(within, 30)]
    buckets = [{"key": "expired", "days": 0, "rows": []}] + [
        {"key": f"d{step}", "days": step, "rows": []} for step in edges
    ]
    for row in rows:
        if row["expired"]:
            buckets[0]["rows"].append(row)
            continue
        for bucket in buckets[1:]:
            if row["days_left"] <= bucket["days"]:
                bucket["rows"].append(row)
                break
    for bucket in buckets:
        bucket["count"] = len(bucket["rows"])
        bucket["value"] = quantize(sum((row["value"] for row in bucket["rows"]), ZERO))
        bucket["retail_value"] = quantize(
            sum((row["retail_value"] for row in bucket["rows"]), ZERO)
        )
    return {"as_of": as_of, "within": within, "buckets": buckets}


def _day_bounds(company, start: date, end: date) -> tuple[datetime, datetime]:
    zone = engine.zone_of(company)
    return (
        datetime.combine(start, time.min, tzinfo=zone),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
    )


def movements(company, start: date, end: date, *, branch_ids: list[int] | None, kinds=None):
    """Stock movements on the company days [start, end] (J3's and N's source), newest first,
    with branch, product and batch loaded."""
    since, until = _day_bounds(company, start, end)
    rows = _scope(
        StockMovement.objects.for_company(company)
        .filter(at__gte=since, at__lt=until)
        .select_related("branch", "product", "batch", "created_by"),
        branch_ids,
    )
    if kinds:
        rows = rows.filter(kind__in=list(kinds))
    return rows.order_by("-at", "-pk")


def velocity(
    company, *, branch_ids: list[int] | None, days: int = 28
) -> dict[tuple[int, int], Decimal]:
    """(branch id, product id) → parts sold a day over the last `days` (refunds subtracted)."""
    today = engine.local_today(company)
    rows = movements(
        company,
        today - timedelta(days=days - 1),
        today,
        branch_ids=branch_ids,
        kinds=(StockMovement.Kind.SALE, StockMovement.Kind.REFUND),
    )
    found = {}
    for row in rows.order_by().values("branch_id", "product_id").annotate(total=Sum("quantity")):
        sold = -(row["total"] or ZERO)
        if sold > 0:
            found[(row["branch_id"], row["product_id"])] = (sold / days).quantize(Decimal("0.001"))
    return found


def price_cap(product, *, batch=None, unit_cost: Decimal | None = None) -> Decimal | None:
    """The legal maximum retail price of one pack, or None when the law sets none (an OTC item,
    or a prescription item with neither a cost nor a reference price). The cap is the batch's
    purchase price (or `unit_cost`) times one plus the company's Rx markup cap (the socially
    significant one when it applies, `StockSettings`), never above the product's reference
    price. Unrounded: the stock module's own prices round down below it, so a sale at the batch
    price never breaches it. J2's cap check reads it."""
    from apps.inventory import conf, pricing

    if not product.rx_required:
        return None
    cost = batch.unit_cost if batch is not None else unit_cost
    return pricing.legal_cap(product, cost, conf.get_settings(product.company))


def analogs(product, *, branch_ids: list[int] | None) -> list[dict]:
    """Products with the same INN, dosage form and strength (a catalogue fact, never advice),
    with the parts on hand at `branch_ids`."""
    if not product.inn:
        return []
    rows = list(
        Product.objects.for_company(product.company_id)
        .filter(
            inn=product.inn,
            dosage_form=product.dosage_form,
            strength=product.strength,
            is_active=True,
        )
        .exclude(pk=product.pk)
        .select_related("manufacturer")
        .order_by("name", "pk")
    )
    held = quantities(product.company, [row.pk for row in rows], branch_ids=branch_ids)
    return [
        {
            "id": row.pk,
            "name": row.name,
            "trade_name": row.trade_name,
            "inn": row.inn,
            "dosage_form": row.dosage_form,
            "strength": row.strength,
            "manufacturer": row.manufacturer.name if row.manufacturer else "",
            "rx_required": row.rx_required,
            "sale_price": row.sale_price,
            "quantity": held.get(row.pk, ZERO),
        }
        for row in rows
    ]


def sellable_quantities(company, *, branch_ids: list[int] | None, day: date):
    """(branch id, product id) → parts on sale (sellable batches, not expired)."""
    rows = _scope(
        BatchStock.objects.filter(
            batch__company=company,
            quantity__gt=0,
            batch__status=StockBatch.Status.SELLABLE,
            batch__expires_on__gte=day,
        ),
        branch_ids,
    )
    return {
        (row["branch_id"], row["batch__product_id"]): row["total"]
        for row in rows.values("branch_id", "batch__product_id").annotate(total=Sum("quantity"))
    }


def mandatory_missing(company, *, branch_ids: list[int] | None, day: date) -> list[dict]:
    """Mandatory-list products with no sellable stock at a pharmacy branch."""
    branches = company.branches.filter(is_active=True, kind=BranchKind.PHARMACY)
    if branch_ids is not None:
        branches = branches.filter(pk__in=branch_ids)
    branches = list(branches.order_by("order", "pk"))
    if not branches:
        return []
    products = list(
        Product.objects.for_company(company)
        .filter(mandatory_list=True, is_active=True)
        .order_by("name", "pk")
    )
    on_sale = sellable_quantities(company, branch_ids=[branch.pk for branch in branches], day=day)
    return [
        {
            "id": product.pk,
            "product_id": product.pk,
            "product": product.name,
            "inn": product.inn,
            "branch_id": branch.pk,
            "branch": branch.name,
        }
        for branch in branches
        for product in products
        if not on_sale.get((branch.pk, product.pk))
    ]


def last_applied_count(branch, *, kind: str = "handover") -> datetime | None:
    """When the branch's last count of `kind` was applied (S's handover blocker)."""
    count = (
        StockCount.objects.filter(branch=branch, kind=kind, status=StockCount.Status.APPLIED)
        .order_by("-applied_at")
        .first()
    )
    return count.applied_at if count is not None else None


# For the dashboard and the registries ---------------------------------------------------------


def stock_value(company, *, branch_ids: list[int] | None) -> dict:
    """What is on the shelves at cost and at retail."""
    cost = retail = ZERO
    for stock in stock_rows(company, branch_ids=branch_ids):
        cost += engine.value_of(stock.batch, stock.quantity)
        retail += engine.retail_value_of(stock.batch, stock.quantity)
    return {"value": quantize(cost), "retail_value": quantize(retail)}


def expiring_value(company, *, branch_ids: list[int] | None, within_days: int, as_of: date):
    rows = expiring(company, branch_ids=branch_ids, within_days=within_days, as_of=as_of)
    live = [row for row in rows if not row["expired"]]
    return {
        "count": len(live),
        "value": quantize(sum((row["value"] for row in live), ZERO)),
        "retail_value": quantize(sum((row["retail_value"] for row in live), ZERO)),
        "expired_count": len(rows) - len(live),
        "expired_value": quantize(sum((row["value"] for row in rows if row["expired"]), ZERO)),
    }


def low_count(company, *, branch_ids: list[int] | None) -> int:
    return levels(company, branch_ids=branch_ids, low=True).count()


def receipts(company, *, branch_ids: list[int] | None) -> QuerySet:
    return _scope(
        GoodsReceipt.objects.for_company(company).select_related("branch", "supplier"),
        branch_ids,
    )


def to_post(company, *, branch_ids: list[int] | None) -> QuerySet:
    return receipts(company, branch_ids=branch_ids).filter(status=GoodsReceipt.Status.SUBMITTED)


def transfers(company, *, branch_ids: list[int] | None) -> QuerySet:
    rows = StockTransfer.objects.for_company(company).select_related("from_branch", "to_branch")
    if branch_ids is None:
        return rows
    return rows.filter(Q(from_branch__in=branch_ids) | Q(to_branch__in=branch_ids))


def writeoffs(company, *, branch_ids: list[int] | None) -> QuerySet:
    return _scope(WriteOff.objects.for_company(company).select_related("branch"), branch_ids)


def counts(company, *, branch_ids: list[int] | None) -> QuerySet:
    return _scope(
        StockCount.objects.for_company(company)
        .select_related("branch", "category", "started_by")
        .annotate(line_count=Count("lines")),
        branch_ids,
    )


def recalls_open(company) -> QuerySet:
    return RecallNotice.objects.for_company(company).filter(status=RecallNotice.Status.OPEN)


def recall_visible(recall: RecallNotice, branch_ids: list[int] | None) -> list[dict]:
    """The rows of a recall's findings inside the branch scope."""
    rows = recall.found or []
    if branch_ids is None:
        return list(rows)
    return [row for row in rows if row.get("branch_id") in branch_ids]


def nearest_expiry(company, product_ids, *, branch_ids: list[int] | None) -> dict[int, date]:
    rows = _scope(
        BatchStock.objects.filter(
            batch__company=company, batch__product_id__in=list(product_ids), quantity__gt=0
        ),
        branch_ids,
    )
    return {
        row["batch__product_id"]: row["first"]
        for row in rows.values("batch__product_id").annotate(first=Min("batch__expires_on"))
    }


def by_branch(company, product, *, branch_ids: list[int] | None) -> list[dict]:
    """What each branch in scope holds of `product` (and its shortfall)."""
    rows = _scope(
        StockLevel.objects.filter(product=product).select_related("branch"), branch_ids
    ).order_by("branch__order", "branch_id")
    return [
        {
            "branch_id": row.branch_id,
            "branch": row.branch.name,
            "quantity": row.quantity,
            "shortfall": row.shortfall,
            "min_qty": row.min_qty,
            "max_qty": row.max_qty,
        }
        for row in rows
    ]


def sold_after_expiry(company, start: date, end: date, *, branch_ids: list[int] | None):
    """Sales recorded from batches past their expiry (flagged for owners)."""
    return movements(
        company, start, end, branch_ids=branch_ids, kinds=(StockMovement.Kind.SALE,)
    ).filter(batch__isnull=False, batch__expires_on__lt=F("at__date"))


def totals_by_branch(company, *, branch_ids: list[int] | None) -> dict[int, dict]:
    found: dict[int, dict] = defaultdict(lambda: {"value": ZERO, "items": 0})
    for stock in stock_rows(company, branch_ids=branch_ids):
        entry = found[stock.branch_id]
        entry["value"] += engine.value_of(stock.batch, stock.quantity)
        entry["items"] += 1
    return dict(found)
