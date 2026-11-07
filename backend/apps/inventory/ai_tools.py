"""Read-only AI tools of stock (docs/PLAN-OWNER.md §8.3, §14.12).

Each wraps a function of `queries.py` and registers with `apps.ai.tools.registry.ai_tool`. They
answer business questions about the company's stock in the asker's branches; none of them gives
medical advice: analogs are a catalogue fact (same active ingredient, form and strength) for the
pharmacist to choose from. Values at cost appear only for holders of finance.view while the
"share finance" switch is on; customer phones on defektura rows are never sent.

Registry permissions are single codes: the reading tools take sales.view, which the owner, the
manager and the accountant roles hold (the dashboard's own stock pages also accept stock.manage
and stock.operate).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils.translation import gettext_lazy as _
from pydantic import BaseModel, Field

from apps.ai.tools.registry import ToolContext, ToolNotFound, ToolResult, ai_tool
from apps.inventory import conf, engine, pricing, queries
from apps.inventory.models import GoodsReceipt, MissingRequest, Product
from apps.members.permissions import Perm

DOMAIN = "inventory"
FEATURE = "stock"


def _costs(ctx: ToolContext) -> bool:
    return ctx.membership.has_perm(Perm.FINANCE_VIEW) and "share_finance" in ctx.switches


def _branches(ctx: ToolContext, branch_id: int | None) -> list[int] | None:
    if branch_id is None:
        return ctx.branch_ids
    if not ctx.company.branches.filter(pk=branch_id).exists():
        raise ToolNotFound
    if ctx.branch_ids is not None and branch_id not in ctx.branch_ids:
        raise ToolNotFound
    return [branch_id]


def _qty(value) -> str:
    value = Decimal(value or 0)
    return f"{value.normalize():f}"


class FindItemInput(BaseModel):
    q: str = Field(..., min_length=2, max_length=100, description="Name, INN or barcode.")


@ai_tool(
    "inventory_find_item",
    domain=DOMAIN,
    perm=Perm.SALES_VIEW,
    label=_(
        "Find a medicine or other item in the catalogue by name, active ingredient (INN) or "
        "barcode: parts on hand per pharmacy, the price per pack and per part, whether it is "
        "prescription-only or controlled, and the nearest expiry date on hand"
    ),
    input=FindItemInput,
    feature=FEATURE,
)
def inventory_find_item(ctx: ToolContext, args: FindItemInput) -> ToolResult:
    company = ctx.company
    settings = conf.get_settings(company)
    found = queries.lookup(company, args.q, branch_ids=ctx.branch_ids, limit=10)
    ids = [row["id"] for row in found]
    products = {product.pk: product for product in Product.objects.filter(pk__in=ids)}
    nearest = queries.nearest_expiry(company, ids, branch_ids=ctx.branch_ids)
    rows = []
    for row in found:
        product = products[row["id"]]
        rows.append(
            {
                "id": product.pk,
                "name": product.name,
                "inn": product.inn,
                "prescription_only": product.rx_required,
                "controlled": product.control_class,
                "storage": product.storage,
                "parts_per_pack": product.units_per_pack,
                "price_per_pack": str(product.sale_price),
                "price_per_part": str(pricing.part_price(product, settings=settings)),
                "parts_on_hand": _qty(row["quantity"]) if row["quantity"] is not None else None,
                "by_pharmacy": [
                    {"pharmacy": level["branch"], "parts": _qty(level["quantity"])}
                    for level in queries.by_branch(company, product, branch_ids=ctx.branch_ids)
                ],
                "nearest_expiry": nearest[product.pk].isoformat()
                if product.pk in nearest
                else None,
            }
        )
    return ToolResult(rows=rows, currency=company.base_currency, as_of=ctx.now)


class AnalogsInput(BaseModel):
    product_id: int | None = Field(None, description="The item's id from inventory_find_item.")
    q: str | None = Field(None, max_length=100, description="Or its name or INN.")


@ai_tool(
    "inventory_analogs",
    domain=DOMAIN,
    perm=Perm.SALES_VIEW,
    label=_(
        "Catalogue items with the same active ingredient, form and strength as an item, with the "
        "parts on hand and the price: a catalogue fact for the pharmacist to choose from, never "
        "a recommendation"
    ),
    input=AnalogsInput,
    feature=FEATURE,
)
def inventory_analogs(ctx: ToolContext, args: AnalogsInput) -> ToolResult:
    company = ctx.company
    product = None
    if args.product_id is not None:
        product = Product.objects.for_company(company).filter(pk=args.product_id).first()
        if product is None:
            raise ToolNotFound
    elif args.q:
        match = queries.lookup(company, args.q, branch_ids=ctx.branch_ids, limit=1)
        if match:
            product = Product.objects.get(pk=match[0]["id"])
    if product is None:
        return ToolResult(rows=[], data={"item": None}, as_of=ctx.now)
    rows = [
        {
            "id": row["id"],
            "name": row["name"],
            "inn": row["inn"],
            "form": row["dosage_form"],
            "strength": row["strength"],
            "manufacturer": row["manufacturer"],
            "prescription_only": row["rx_required"],
            "price_per_pack": str(row["sale_price"]),
            "parts_on_hand": _qty(row["quantity"]),
        }
        for row in queries.analogs(product, branch_ids=ctx.branch_ids)
    ]
    return ToolResult(
        rows=rows,
        data={
            "item": {"id": product.pk, "name": product.name, "inn": product.inn},
            "note": "Same active ingredient, form and strength (catalogue data, not advice).",
        },
        currency=company.base_currency,
        as_of=ctx.now,
    )


class ExpiringInput(BaseModel):
    days: int = Field(30, ge=0, le=365, description="Expiring within this many days.")
    branch_id: int | None = Field(None, description="One pharmacy; all in scope by default.")


@ai_tool(
    "inventory_expiring",
    domain=DOMAIN,
    perm=Perm.SALES_VIEW,
    label=_(
        "Batches that expire within a number of days (or already expired) per pharmacy: series, "
        "expiry date, parts on hand and their value at retail (and at cost when finance data is "
        "shared)"
    ),
    input=ExpiringInput,
    feature=FEATURE,
)
def inventory_expiring(ctx: ToolContext, args: ExpiringInput) -> ToolResult:
    company = ctx.company
    today = engine.local_today(company, ctx.now)
    costs = _costs(ctx)
    found = queries.expiring(
        company, branch_ids=_branches(ctx, args.branch_id), within_days=args.days, as_of=today
    )
    rows = []
    for row in found:
        item = {
            "id": row["id"],
            "pharmacy": row["branch"],
            "item": row["product"],
            "series": row["series"],
            "expires_on": row["expires_on"].isoformat(),
            "days_left": row["days_left"],
            "expired": row["expired"],
            "parts": _qty(row["quantity"]),
            "value_retail": str(row["retail_value"]),
        }
        if costs:
            item["value_cost"] = str(row["value"])
        rows.append(item)
    data = {
        "today": today.isoformat(),
        "batches": len(rows),
        "value_retail": str(sum((row["retail_value"] for row in found), Decimal(0))),
    }
    if costs:
        data["value_cost"] = str(sum((row["value"] for row in found), Decimal(0)))
    return ToolResult(rows=rows, data=data, currency=company.base_currency, as_of=ctx.now)


class ReceiptsInput(BaseModel):
    days: int = Field(30, ge=1, le=366, description="Invoices of the last this many days.")
    distributor: str | None = Field(None, max_length=100, description="Part of its name.")
    unposted: bool = Field(False, description="Only drafts and those waiting for posting.")


@ai_tool(
    "inventory_receipts",
    domain=DOMAIN,
    perm=Perm.SALES_VIEW,
    label=_(
        "Goods receipts (distributors' invoices): distributor, invoice number and date, pharmacy, "
        "status, due date, and the amount and how much of the payable is paid when finance data "
        "is shared"
    ),
    input=ReceiptsInput,
    feature=FEATURE,
)
def inventory_receipts(ctx: ToolContext, args: ReceiptsInput) -> ToolResult:
    company = ctx.company
    today = engine.local_today(company, ctx.now)
    costs = _costs(ctx)
    rows_ = queries.receipts(company, branch_ids=ctx.branch_ids).filter(
        supplier_invoice_date__gte=today - timedelta(days=args.days)
    )
    if args.distributor:
        rows_ = rows_.filter(supplier__name__icontains=args.distributor)
    if args.unposted:
        rows_ = rows_.filter(status__in=(GoodsReceipt.Status.DRAFT, GoodsReceipt.Status.SUBMITTED))
    rows = []
    for receipt in rows_.exclude(status=GoodsReceipt.Status.VOID).select_related("debt")[:100]:
        item = {
            "id": receipt.pk,
            "number": receipt.number or None,
            "distributor": receipt.supplier.name,
            "invoice": receipt.supplier_invoice_number,
            "invoice_date": receipt.supplier_invoice_date.isoformat(),
            "pharmacy": receipt.branch.name,
            "status": receipt.status,
            "due_on": receipt.due_on.isoformat() if receipt.due_on else None,
        }
        if costs:
            item["amount"] = str(receipt.total)
            if receipt.debt_id:
                item["paid"] = str(receipt.debt.paid)
                item["payable_status"] = receipt.debt.status
        rows.append(item)
    return ToolResult(rows=rows, currency=company.base_currency, as_of=ctx.now)


class LevelsInput(BaseModel):
    q: str | None = Field(None, max_length=100, description="Name or INN.")
    low: bool = Field(False, description="Only items below their minimum.")
    branch_id: int | None = Field(None, description="One pharmacy; all in scope by default.")


@ai_tool(
    "inventory_stock_levels",
    domain=DOMAIN,
    perm=Perm.SALES_VIEW,
    label=_(
        "Stock per pharmacy and item: parts on hand, parts sold before their delivery was "
        "recorded, the minimum, and whether it is low"
    ),
    input=LevelsInput,
    feature=FEATURE,
)
def inventory_stock_levels(ctx: ToolContext, args: LevelsInput) -> ToolResult:
    company = ctx.company
    rows_ = queries.levels(company, branch_ids=_branches(ctx, args.branch_id), low=args.low)
    if args.q:
        rows_ = rows_.filter(product__in=queries._search(company, args.q))
    rows_ = rows_.exclude(quantity=0, shortfall=0)
    total = rows_.count()
    rows = [
        {
            "id": level.pk,
            "pharmacy": level.branch.name,
            "item": level.product.name,
            "parts": _qty(level.quantity),
            "sold_without_stock": _qty(level.shortfall),
            "minimum": _qty(level.min_qty) if level.min_qty is not None else None,
            "low": level.min_qty is not None and level.quantity < level.min_qty,
        }
        for level in rows_[:50]
    ]
    return ToolResult(rows=rows, total=total, as_of=ctx.now)


class DefekturaInput(BaseModel):
    days: int = Field(30, ge=1, le=366)
    status: str | None = Field(None, description="open, ordered, fulfilled or cancelled.")


@ai_tool(
    "inventory_defektura",
    domain=DOMAIN,
    perm=Perm.SALES_VIEW,
    label=_(
        "Defektura: what customers asked for that a pharmacy didn't have, how many packs, when, "
        "and whether it was ordered or arrived"
    ),
    input=DefekturaInput,
    feature=FEATURE,
)
def inventory_defektura(ctx: ToolContext, args: DefekturaInput) -> ToolResult:
    company = ctx.company
    since = ctx.now - timedelta(days=args.days)
    rows_ = MissingRequest.objects.for_company(company).filter(requested_at__gte=since)
    if ctx.branch_ids is not None:
        rows_ = rows_.filter(branch_id__in=ctx.branch_ids)
    if args.status:
        rows_ = rows_.filter(status=args.status)
    rows = [
        {
            "id": row.pk,
            "pharmacy": row.branch.name,
            "item": row.product.name if row.product_id else row.name,
            "in_catalogue": row.product_id is not None,
            "packs": _qty(row.packs),
            "source": row.source,
            "status": row.status,
            "asked_on": engine.local_today(company, row.requested_at).isoformat(),
        }
        for row in rows_.select_related("branch", "product")[:100]
    ]
    return ToolResult(rows=rows, as_of=ctx.now)
