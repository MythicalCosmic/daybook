"""Business logic of stock: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`. Stock itself moves
only through `apps.inventory.engine.move`, with the product's level locked first.

The stock contract (docs/PLAN-OWNER.md §14.6.3) keeps the signatures W2.a fixed (the sales
lines (J2), the people lifecycle (S) and later J3 and N call them; `tests/test_contract.py`
checks them): `deduct`, `restock`, `start_count`, `remember_code`, `record_rx`, `journal_pdf`.

Documents and their movements (`StockMovement.document_type`, `document_id`):
``inventory.goodsreceipt`` (delivery, and the settlement of a shortfall it pays back),
``inventory.stocktransfer``, ``inventory.writeoff``, ``inventory.stockcount`` and
``inventory.stockbatch`` (opening stock, quarantine, release).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import NamedTuple

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch, BranchKind
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.inventory import conf, engine, pricing
from apps.inventory.audit_actions import InventoryAction as Action
from apps.inventory.engine import ZERO, lock_levels, move, parts
from apps.inventory.models import (
    BatchStock,
    GoodsReceipt,
    GoodsReceiptLine,
    Manufacturer,
    MissingRequest,
    PricingRule,
    Product,
    ProductCategory,
    ProductCode,
    RecallNotice,
    RxRecord,
    StockBatch,
    StockCount,
    StockCountLine,
    StockLevel,
    StockMovement,
    StockSettings,
    StockTransfer,
    StockTransferLine,
    SupplierProfile,
    WriteOff,
    WriteOffFile,
    WriteOffLine,
)
from apps.members.models import Membership

PULSE = "inventory"
RECEIPT = "inventory.goodsreceipt"
TRANSFER = "inventory.stocktransfer"
WRITEOFF = "inventory.writeoff"
COUNT = "inventory.stockcount"
BATCH = "inventory.stockbatch"

Kind = StockMovement.Kind
DEDUCT_KINDS = frozenset({Kind.SALE, Kind.WRITEOFF, Kind.TRANSFER_OUT, Kind.COUNT_ADJUSTMENT})
RESTOCK_KINDS = frozenset({Kind.REFUND, Kind.TRANSFER_IN, Kind.COUNT_ADJUSTMENT})
LICENSED_CLASSES = (
    Product.ControlClass.NARCOTIC,
    Product.ControlClass.PSYCHOTROPIC,
    Product.ControlClass.PRECURSOR,
)


class Allocation(NamedTuple):
    """What a deduction took from one batch: `quantity` in parts, `unit_cost` per part at the
    batch's cost. `batch_id` None: no batch held it (a shortfall, or an item without stock)."""

    batch_id: int | None
    quantity: Decimal
    unit_cost: Decimal | None


# Helpers -----------------------------------------------------------------------------------------


def _audit(action: str, company_id: int, by: Membership | None, target, **details) -> None:
    audit.record(
        action,
        company_id=company_id,
        actor=by.user if by is not None else None,
        target=target,
        **details,
    )


def _bump(company_id: int, *keys: str) -> None:
    keys = (PULSE, *keys)
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _same_company(company_id: int, *rows) -> None:
    for row in rows:
        if row is not None and getattr(row, "company_id", company_id) != company_id:
            raise DomainError(_("That belongs to another company."))


def _company_id(row) -> int:
    return row.company_id if hasattr(row, "company_id") else row.pk


def _text(value, limit: int) -> str:
    return (value or "").strip()[:limit]


def _now(at: datetime | None = None) -> datetime:
    return at or timezone.now()


def _next_number(company, field: str) -> int:
    settings = conf.locked_settings(company)
    number = getattr(settings, field)
    setattr(settings, field, number + 1)
    settings.save(update_fields=[field, "updated_at"])
    return number


def _code(branch) -> str:
    return (branch.code or str(branch.pk)).upper()


def _product_label(product: Product) -> str:
    return product.name


def is_licensed_for(branch, product: Product) -> bool:
    """Narcotics, psychotropics and precursors only at a branch licensed for them; a starred
    strong-acting item also at a social pharmacy (§14.4 rows 22-23)."""
    if product.control_class in LICENSED_CLASSES and not branch.controlled_licence:
        return False
    return not product.restricted_channel or branch.controlled_licence or branch.social_pharmacy


def _check_licensed(branch, product: Product) -> None:
    if not is_licensed_for(branch, product):
        raise DomainError(
            _(
                "%(branch)s isn't licensed for %(product)s: only a pharmacy licensed for "
                "narcotics and psychotropics may receive it."
            )
            % {"branch": branch.name, "product": product.name}
        )


# The stock contract ---------------------------------------------------------------------------


@transaction.atomic
def deduct(
    branch,
    product,
    quantity,
    *,
    by,
    document: tuple[str, int],
    kind: str = "sale",
    series: str | None = None,
    reason: str = "",
    at: datetime | None = None,
) -> list[Allocation]:
    """Take `quantity` parts of `product` at `branch`, earliest-expiring sellable batch first
    (FEFO), for `document` ("sales.sale", id). Returns what each batch gave.

    Quarantined, recalled and expired batches are never picked. A caller may name a `series`;
    with `fefo_strict`, naming a later batch while an earlier sellable one has stock needs a
    `reason` (stored on the movement). A sale of a named series that isn't on sale (expired,
    in quarantine, recalled) is still recorded from it, because it happened; the movement
    says why ("expired", "quarantine", "recalled"). With `allow_negative`, what the batches
    can't cover is booked as a shortfall (`batch_id` None) that the next delivery settles;
    without it the deduction is refused."""
    if kind not in DEDUCT_KINDS:
        raise ValueError(f"deduct() books {sorted(DEDUCT_KINDS)}, not {kind!r}.")
    quantity = parts(quantity)
    if quantity <= 0:
        raise DomainError(_("Give a quantity above zero."))
    _same_company(branch.company_id, product)
    if not product.track_stock or product.kind == Product.Kind.SERVICE:
        return [Allocation(None, quantity, None)]
    company = product.company
    settings = conf.get_settings(company)
    moment = _now(at)
    today = engine.local_today(company, moment)
    reason = _text(reason, 16)
    level = engine.lock_level(branch, product)
    fefo = engine.fefo_stocks(branch, product, today)
    order = fefo
    named_reason = reason
    if series and (series := series.strip()):
        named = engine.fefo_stocks(branch, product, today, sellable_only=False)
        named = [stock for stock in named if stock.batch.series == series]
        pick = next((s for s in named if engine.is_sellable(s.batch, today)), None)
        if pick is None and named and kind == Kind.SALE:
            pick = named[0]
            batch = pick.batch
            named_reason = reason or (
                "expired" if engine.is_expired(batch, today) else str(batch.status)
            )
        elif pick is None and named:
            raise DomainError(
                _("Series %(series)s isn't on sale.") % {"series": series},
            )
        if pick is not None:
            earlier = [
                stock
                for stock in fefo
                if stock.pk != pick.pk and stock.batch.expires_on < pick.batch.expires_on
            ]
            if earlier and settings.fefo_strict and not reason:
                first = earlier[0].batch
                raise DomainError(
                    _(
                        "Series %(earlier)s expires earlier (%(day)s) and is on sale: sell it "
                        "first, or give a reason to take %(series)s."
                    )
                    % {
                        "earlier": first.series,
                        "day": first.expires_on.strftime("%d.%m.%Y"),
                        "series": series,
                    }
                )
            order = [pick, *[stock for stock in fefo if stock.pk != pick.pk]]
    allocations: list[Allocation] = []
    remaining = quantity
    for stock in order:
        if remaining <= 0:
            break
        take = min(stock.quantity, remaining)
        if take <= 0:
            continue
        batch = stock.batch
        move(
            level=level,
            batch=batch,
            quantity=-take,
            kind=kind,
            by=by,
            document=document,
            reason=named_reason if order and stock is order[0] else reason,
            at=moment,
            stock=stock,
        )
        allocations.append(Allocation(batch.pk, take, engine.part_cost(batch)))
        remaining -= take
    if remaining > 0:
        if not settings.allow_negative:
            raise DomainError(
                _("Only %(left)s parts of %(product)s are on sale here.")
                % {"left": (quantity - remaining).normalize(), "product": product.name}
            )
        move(
            level=level,
            batch=None,
            quantity=-remaining,
            kind=kind,
            by=by,
            document=document,
            reason="shortfall",
            at=moment,
        )
        allocations.append(Allocation(None, remaining, None))
    engine.refresh_sale_price(product)
    _bump(company.pk, "inventory.low")
    return allocations


@transaction.atomic
def restock(
    branch,
    allocations: list[Allocation],
    *,
    by,
    document: tuple[str, int],
    kind: str = "refund",
    status: str = "quarantine",
) -> None:
    """Put deducted parts back (a refund lands in quarantine: medicines sold aren't resold; a
    voided invoice passes status="sellable", the goods never left).

    A refund goes into a quarantine twin of its batch (same series, expiry and cost, kept apart
    so the batch itself stays on sale). An allocation without a batch (a shortfall, or a refund
    whose sale the file doesn't name) books against the batch most recently deducted for that
    product at that branch; with status="sellable" it first takes back the shortfall it made.
    Its product comes from the other allocations of the call."""
    if kind not in RESTOCK_KINDS:
        raise ValueError(f"restock() books {sorted(RESTOCK_KINDS)}, not {kind!r}.")
    if status not in (StockBatch.Status.QUARANTINE, StockBatch.Status.SELLABLE):
        raise ValueError(f"restock() puts goods in quarantine or on sale, not {status!r}.")
    rows = [Allocation(*allocation) for allocation in allocations]
    wanted = {row.batch_id for row in rows if row.batch_id}
    batches = {
        batch.pk: batch
        for batch in StockBatch.objects.select_related("product__company").filter(
            company_id=branch.company_id, pk__in=wanted
        )
    }
    if len(batches) != len(wanted):
        raise DomainError(_("That batch isn't in this company's stock."))
    hint = next(iter(batches.values())).product if batches else None
    plan: list[tuple[Product, StockBatch | None, Decimal]] = []
    for row in rows:
        quantity = parts(row.quantity)
        if quantity <= 0:
            continue
        batch = batches.get(row.batch_id) if row.batch_id else None
        product = batch.product if batch is not None else hint
        if product is None:
            raise DomainError(_("Name the batch the goods came from to put them back."))
        plan.append((product, batch, quantity))
    if not plan:
        return
    levels = lock_levels((branch, product) for product, _batch, _quantity in plan)
    for product, batch, quantity in plan:
        level = levels[(branch.pk, product.pk)]
        if batch is None:
            if status == StockBatch.Status.SELLABLE and level.shortfall > 0:
                settle = min(level.shortfall, quantity)
                move(
                    level=level,
                    batch=None,
                    quantity=settle,
                    kind=kind,
                    by=by,
                    document=document,
                    reason="shortfall",
                )
                quantity -= settle
                if quantity <= 0:
                    continue
            batch = _last_deducted(branch, product)
            if batch is None:
                raise DomainError(
                    _("Nothing of %(product)s was sold here to take back.")
                    % {"product": product.name}
                )
        target = batch
        if status == StockBatch.Status.QUARANTINE and batch.status == StockBatch.Status.SELLABLE:
            target = _quarantine_twin(batch)
        move(
            level=level,
            batch=target,
            quantity=quantity,
            kind=kind,
            by=by,
            document=document,
            reason="quarantine" if target.status != StockBatch.Status.SELLABLE else "",
        )
    for product in {product.pk: product for product, _b, _q in plan}.values():
        engine.refresh_sale_price(product)
    _bump(branch.company_id)


def _last_deducted(branch, product) -> StockBatch | None:
    movement = (
        StockMovement.objects.filter(
            branch=branch, product=product, batch__isnull=False, quantity__lt=0
        )
        .select_related("batch__product")
        .order_by("-at", "-pk")
        .first()
    )
    return movement.batch if movement is not None else None


def _quarantine_twin(batch: StockBatch) -> StockBatch:
    """The batch's quarantine twin, made once: refunds of it wait there, off sale."""
    StockBatch.objects.select_for_update().get(pk=batch.pk)
    twin = batch.twins.filter(status=StockBatch.Status.QUARANTINE).first()
    if twin is None:
        twin = StockBatch.objects.create(
            company_id=batch.company_id,
            product=batch.product,
            series=batch.series,
            expires_on=batch.expires_on,
            made_on=batch.made_on,
            supplier_id=batch.supplier_id,
            unit_cost=batch.unit_cost,
            retail_price=batch.retail_price,
            status=StockBatch.Status.QUARANTINE,
            origin=batch,
        )
    twin.product = batch.product
    return twin


def remember_code(product, *, by, kind: str, code: str, supplier=None) -> None:
    """An import line matched by hand: the code finds this product from now on."""
    code = _text(code, 64)
    if not code:
        return
    if kind not in ProductCode.Kind.values:
        raise ValueError(f"Unknown product code kind {kind!r}.")
    _same_company(product.company_id, supplier)
    if kind == ProductCode.Kind.BARCODE and product.barcode == code:
        return
    with transaction.atomic():
        found = ProductCode.objects.filter(
            company_id=product.company_id,
            kind=kind,
            code=code,
            supplier=supplier if kind == ProductCode.Kind.SUPPLIER else None,
        ).first()
        if found is not None:
            if found.product_id == product.pk:
                return
            found.product = product
            found.save(update_fields=["product", "updated_at"])
        else:
            try:
                with transaction.atomic():
                    found = ProductCode.objects.create(
                        company_id=product.company_id,
                        product=product,
                        kind=kind,
                        code=code,
                        supplier=supplier if kind == ProductCode.Kind.SUPPLIER else None,
                    )
            except IntegrityError:
                return
        _audit(Action.CODE_SAVED, product.company_id, by, product, kind=kind, code=code)


@transaction.atomic
def record_rx(
    *, by, branch, product, quantity, document: tuple[str, int] | None = None, **fields
) -> RxRecord | None:
    """A prescription log entry for a dispensed prescription medicine (or an invalid
    prescription, `status="invalid"`). None while the company keeps no prescription log or the
    product isn't prescription-only. One entry per `document`: recording it again updates it.
    Never a patient's name, ID or PINFL."""
    from apps.inventory import prescriptions

    return prescriptions.record(
        by=by, branch=branch, product=product, quantity=quantity, document=document, **fields
    )


def journal_pdf(kind: str, *, branch, month: date, product=None, language: str) -> bytes:
    """The printed journal: kind rx, rx_invalid or controlled."""
    from apps.inventory import journals

    return journals.pdf(kind, branch=branch, month=month, product=product, language=language)


@transaction.atomic
def start_count(branch, *, by, kind: str = "partial", category=None) -> StockCount:
    """A stock count at `branch`: one line per batch on hand (of `category` when given, its
    subgroups included), with the expected quantity frozen and never shown to counters."""
    if kind not in StockCount.Kind.values:
        raise DomainError(_("Pick a kind of count."))
    _same_company(branch.company_id, category)
    if StockCount.objects.filter(
        branch=branch, status__in=(StockCount.Status.OPEN, StockCount.Status.SUBMITTED)
    ).exists():
        raise DomainError(_("A count is already open at %(branch)s.") % {"branch": branch.name})
    count = StockCount.objects.create(
        company_id=branch.company_id,
        branch=branch,
        kind=kind,
        category=category,
        started_by=by,
    )
    stocks = (
        BatchStock.objects.filter(branch=branch, quantity__gt=0)
        .select_related("batch__product")
        .order_by("batch__product__name", "batch__expires_on", "batch_id")
    )
    if category is not None:
        stocks = stocks.filter(
            Q(batch__product__category=category) | Q(batch__product__category__parent=category)
        )
    StockCountLine.objects.bulk_create(
        StockCountLine(
            count=count,
            product=stock.batch.product,
            batch=stock.batch,
            expected=stock.quantity,
            order=index,
        )
        for index, stock in enumerate(stocks)
    )
    _audit(Action.COUNT_STARTED, branch.company_id, by, count, branch=branch.name, kind=kind)
    _bump(branch.company_id)
    return count


# Settings ---------------------------------------------------------------------------------------

SETTINGS_FIELDS = (
    "expiry_steps",
    "min_shelf_days",
    "fefo_strict",
    "allow_negative",
    "default_markup_percent",
    "rx_max_markup_percent",
    "social_max_markup_percent",
    "cap_enforced",
    "price_rounding",
    "price_jump_percent",
    "writeoff_approval",
    "show_other_branches",
    "camera_scanning",
    "rx_log",
    "count_tolerance",
    "destroy_within_days",
    "destroy_commission_min",
    "rx_keep_months",
    "rx_destroy_commission_min",
    "narcotic_rx_valid_days",
    "psychotropic_rx_valid_months",
    "psychotropic_stock_months",
    "controlled_close_day",
    "controlled_report_days",
)


@transaction.atomic
def update_settings(company, *, by: Membership, **fields) -> StockSettings:
    unknown = set(fields) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"Unknown stock settings: {sorted(unknown)}")
    row = conf.locked_settings(company)
    if "expiry_steps" in fields:
        steps = sorted(
            {int(step) for step in fields["expiry_steps"] if int(step) > 0}, reverse=True
        )
        fields["expiry_steps"] = steps
    if "rx_keep_months" in fields:
        keep = dict(row.rx_keep_months or {})
        for rx_kind, months in (fields["rx_keep_months"] or {}).items():
            if rx_kind in RxRecord.RxKind.values and int(months) >= 0:
                keep[rx_kind] = int(months)
        fields["rx_keep_months"] = keep
    if "controlled_close_day" in fields and not 1 <= int(fields["controlled_close_day"]) <= 28:
        raise DomainError(_("Pick a day between 1 and 28."))
    changed = {}
    for field, value in fields.items():
        if getattr(row, field) != value:
            changed[field] = str(value) if isinstance(value, Decimal) else value
            setattr(row, field, value)
    if changed:
        row.save()
        _audit(Action.SETTINGS_CHANGED, company.pk, by, row, **changed)
        _bump(company.pk)
    return row


# The catalogue ----------------------------------------------------------------------------------

PRODUCT_FIELDS = (
    "name",
    "trade_name",
    "inn",
    "kind",
    "dosage_form",
    "strength",
    "units_per_pack",
    "part_label",
    "manufacturer",
    "category",
    "rx_required",
    "e_rx_group",
    "control_class",
    "restricted_channel",
    "storage",
    "light_sensitive",
    "barcode",
    "sku",
    "mxik_code",
    "package_code",
    "registration_number",
    "registration_until",
    "marking_required",
    "vat_percent",
    "socially_significant",
    "mandatory_list",
    "reference_price",
    "reference_price_on",
    "sale_price",
    "part_price",
    "track_stock",
    "is_active",
)
PRICE_FIELDS = ("sale_price", "part_price", "reference_price")


def normalize_inn(value: str) -> str:
    """Lowercase Latin INN; a combination sorted and joined with "+"."""
    parts_ = [part.strip().lower() for part in (value or "").replace(",", "+").split("+")]
    return "+".join(sorted(part for part in parts_ if part))[:200]


def _apply_product(product: Product, fields: dict) -> dict:
    changed = {}
    for field, value in fields.items():
        if field == "inn":
            value = normalize_inn(value)
        elif field in ("name", "trade_name", "strength", "part_label", "barcode", "sku"):
            value = (value or "").strip()
        if field in ("manufacturer", "category"):
            _same_company(product.company_id, value)
            before = getattr(product, f"{field}_id")
            after = value.pk if value is not None else None
            if before != after:
                changed[field] = str(value) if value is not None else None
                setattr(product, field, value)
            continue
        if getattr(product, field) != value:
            changed[field] = str(value) if isinstance(value, Decimal | date) else value
            setattr(product, field, value)
    if not product.name:
        raise DomainError(_("Give the item a name."))
    if product.units_per_pack < 1:
        raise DomainError(_("A pack has at least one part."))
    if product.kind == Product.Kind.SERVICE:
        product.track_stock = False
    return changed


def _save_product(product: Product) -> None:
    try:
        with transaction.atomic():
            product.save()
    except IntegrityError as exc:
        text = str(exc)
        if "barcode" in text:
            raise DomainError(_("Another item already has this barcode.")) from exc
        if "sku" in text:
            raise DomainError(_("Another item already has this SKU.")) from exc
        raise


@transaction.atomic
def create_product(company, *, by: Membership, **fields) -> Product:
    unknown = set(fields) - set(PRODUCT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown product fields: {sorted(unknown)}")
    product = Product(company=company)
    _apply_product(product, fields)
    _save_product(product)
    _audit(Action.PRODUCT_CREATED, company.pk, by, product, name=product.name)
    _bump(company.pk)
    return product


@transaction.atomic
def update_product(product: Product, *, by: Membership, **fields) -> Product:
    unknown = set(fields) - set(PRODUCT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown product fields: {sorted(unknown)}")
    product = Product.objects.select_for_update().select_related("company").get(pk=product.pk)
    changed = _apply_product(product, fields)
    if changed:
        _save_product(product)
        _audit(Action.PRODUCT_CHANGED, product.company_id, by, product, **changed)
        if set(changed) & set(PRICE_FIELDS):
            _audit(
                Action.PRICE_CHANGED,
                product.company_id,
                by,
                product,
                **{key: changed[key] for key in changed if key in PRICE_FIELDS},
            )
        _bump(product.company_id)
    return product


@transaction.atomic
def merge_products(keep: Product, other: Product, *, by: Membership) -> Product:
    """Two catalogue rows for one item: everything of `other` moves to `keep`, `other` is
    switched off with its codes kept as `keep`'s."""
    if keep.pk == other.pk or keep.company_id != other.company_id:
        raise DomainError(_("Pick two different items of this company."))
    if keep.units_per_pack != other.units_per_pack:
        raise DomainError(_("The two items have different parts per pack: fix that first."))
    list(Product.objects.select_for_update().filter(pk__in=(keep.pk, other.pk)).order_by("pk"))
    from apps.inventory.models import ControlledPeriod

    if ControlledPeriod.objects.filter(product=other).exists():
        raise DomainError(_("This item has closed months in the controlled register."))
    StockBatch.objects.filter(product=other).update(product=keep)
    StockMovement.objects.filter(product=other).update(product=keep)
    GoodsReceiptLine.objects.filter(product=other).update(product=keep)
    StockTransferLine.objects.filter(product=other).update(product=keep)
    StockCountLine.objects.filter(product=other).update(product=keep)
    MissingRequest.objects.filter(product=other).update(product=keep)
    RxRecord.objects.filter(product=other).update(product=keep)
    RecallNotice.objects.filter(product=other).update(product=keep)
    for code in ProductCode.objects.filter(product=other):
        if (
            ProductCode.objects.filter(
                company_id=keep.company_id, kind=code.kind, supplier=code.supplier, code=code.code
            )
            .exclude(pk=code.pk)
            .exists()
        ):
            code.delete()
        else:
            code.product = keep
            code.save(update_fields=["product", "updated_at"])
    for level in StockLevel.objects.select_for_update().filter(product=other):
        target = engine.lock_level(level.branch, keep)
        target.quantity += level.quantity
        target.shortfall += level.shortfall
        target.save(update_fields=["quantity", "shortfall", "updated_at"])
        level.delete()
    if other.barcode and not keep.barcode:
        code = other.barcode
        Product.objects.filter(pk=other.pk).update(barcode="")
        Product.objects.filter(pk=keep.pk).update(barcode=code)
    elif other.barcode:
        code = other.barcode
        Product.objects.filter(pk=other.pk).update(barcode="")
        remember_code(keep, by=by, kind=ProductCode.Kind.BARCODE, code=code)
    Product.objects.filter(pk=other.pk).update(is_active=False, sku="")
    keep.refresh_from_db()
    _audit(Action.PRODUCTS_MERGED, keep.company_id, by, keep, merged=other.name, merged_id=other.pk)
    _bump(keep.company_id)
    return keep


@transaction.atomic
def save_category(company, *, by: Membership, category=None, **fields) -> ProductCategory:
    parent = fields.get("parent", category.parent if category else None)
    _same_company(company.pk, parent)
    if parent is not None and parent.parent_id is not None:
        raise DomainError(_("Categories go two levels deep at most."))
    if category is not None and parent is not None and parent.pk == category.pk:
        raise DomainError(_("A category can't be inside itself."))
    row = category or ProductCategory(company=company)
    for field in ("name", "parent", "order"):
        if field in fields:
            setattr(row, field, fields[field])
    row.name = _text(row.name, 100)
    if not row.name:
        raise DomainError(_("Give the category a name."))
    row.save()
    _audit(Action.CATEGORY_SAVED, company.pk, by, row, name=row.name)
    _bump(company.pk)
    return row


@transaction.atomic
def delete_category(category: ProductCategory, *, by: Membership) -> None:
    if category.children.exists():
        raise DomainError(_("Move or delete its subgroups first."))
    _audit(Action.CATEGORY_DELETED, category.company_id, by, category, name=category.name)
    category.delete()
    _bump(category.company_id)


@transaction.atomic
def save_manufacturer(company, *, by: Membership, manufacturer=None, **fields) -> Manufacturer:
    row = manufacturer or Manufacturer(company=company)
    if "name" in fields:
        row.name = _text(fields["name"], 120)
    if "country" in fields:
        row.country = _text(fields["country"], 2).upper()
    if not row.name:
        raise DomainError(_("Give the manufacturer's name."))
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError as exc:
        raise DomainError(_("A manufacturer with this name already exists.")) from exc
    _audit(Action.MANUFACTURER_SAVED, company.pk, by, row, name=row.name)
    return row


SUPPLIER_FIELDS = (
    "payment_terms_days",
    "official_dealer",
    "delivery_days",
    "min_order",
    "order_channel",
    "telegram_username",
    "notes",
)


@transaction.atomic
def save_supplier(counterparty, *, by: Membership, **fields) -> SupplierProfile:
    """A distributor's terms (its counterparty lives in Finance's party directory)."""
    from apps.finance.models import Counterparty

    unknown = set(fields) - set(SUPPLIER_FIELDS)
    if unknown:
        raise ValueError(f"Unknown supplier fields: {sorted(unknown)}")
    if counterparty.kind not in (Counterparty.Kind.SUPPLIER, Counterparty.Kind.BOTH):
        Counterparty.objects.filter(pk=counterparty.pk).update(
            kind=Counterparty.Kind.BOTH
            if counterparty.kind == Counterparty.Kind.CUSTOMER
            else Counterparty.Kind.SUPPLIER
        )
    profile, _made = SupplierProfile.objects.get_or_create(
        company_id=counterparty.company_id, counterparty=counterparty
    )
    changed = {}
    for field, value in fields.items():
        if field == "telegram_username":
            value = _text(value, 64).lstrip("@")
        if getattr(profile, field) != value:
            changed[field] = str(value) if isinstance(value, Decimal) else value
            setattr(profile, field, value)
    if changed:
        profile.save()
    _audit(Action.SUPPLIER_SAVED, counterparty.company_id, by, profile, **changed)
    _bump(counterparty.company_id)
    return profile


def due_date(supplier, invoice_date: date) -> date:
    """The invoice date plus the distributor's payment terms; the invoice date itself when it
    has none (paid on delivery). Invoice 05.10.2026 on 30 days → 04.11.2026."""
    profile = SupplierProfile.objects.filter(counterparty=supplier).first()
    days = profile.payment_terms_days if profile is not None else None
    return invoice_date + timedelta(days=days or 0)


@transaction.atomic
def set_level_limits(branch, product, *, by: Membership, min_qty=None, max_qty=None) -> StockLevel:
    _same_company(branch.company_id, product)
    if min_qty is not None and max_qty is not None and max_qty < min_qty:
        raise DomainError(_("The maximum can't be below the minimum."))
    level = engine.lock_level(branch, product)
    level.min_qty, level.max_qty = min_qty, max_qty
    engine._flag_low(level)
    level.save(update_fields=["min_qty", "max_qty", "low_since", "updated_at"])
    _audit(
        Action.LEVEL_CHANGED,
        branch.company_id,
        by,
        product,
        branch=branch.name,
        min_qty=str(min_qty) if min_qty is not None else None,
        max_qty=str(max_qty) if max_qty is not None else None,
    )
    _bump(branch.company_id, "inventory.low")
    return level


# Opening stock -------------------------------------------------------------------------------


@transaction.atomic
def add_opening_stock(
    branch,
    *,
    by: Membership | None,
    product: Product,
    series: str,
    expires_on: date,
    quantity,
    unit_cost,
    retail_price=None,
    made_on: date | None = None,
    supplier=None,
    at: datetime | None = None,
) -> StockBatch:
    """Stock that was on the shelf before the books moved here: a batch without a delivery
    (series, expiry, cost per pack) and an `opening` movement. `quantity` is in parts."""
    _same_company(branch.company_id, product, supplier)
    series = _text(series, 40)
    if not series:
        raise DomainError(_("Give the series printed on the pack."))
    quantity = parts(quantity)
    if quantity <= 0:
        raise DomainError(_("Give a quantity above zero."))
    _check_licensed(branch, product)
    settings = conf.get_settings(product.company)
    price, _lowered = pricing.suggest_price(product, unit_cost, settings, wanted=retail_price)
    batch = StockBatch.objects.create(
        company_id=branch.company_id,
        product=product,
        series=series,
        expires_on=expires_on,
        made_on=made_on,
        supplier=supplier,
        unit_cost=quantize(Decimal(unit_cost)),
        retail_price=price,
    )
    level = engine.lock_level(branch, product)
    move(
        level=level,
        batch=batch,
        quantity=quantity,
        kind=Kind.OPENING,
        by=by,
        document=(BATCH, batch.pk),
        at=at,
    )
    if product.cost_price is None:
        Product.objects.filter(pk=product.pk).update(cost_price=batch.unit_cost)
    _settle_shortfall(level, batch, by=by, document=(BATCH, batch.pk), at=at)
    engine.refresh_sale_price(product)
    _audit(
        Action.OPENING_STOCK,
        branch.company_id,
        by,
        batch,
        branch=branch.name,
        product=product.name,
        series=series,
        quantity=str(quantity),
    )
    _bump(branch.company_id, "inventory.low", "inventory.expiring")
    return batch


def _settle_shortfall(level: StockLevel, batch: StockBatch, *, by, document, at=None) -> Decimal:
    """Parts sold before this batch was recorded come out of it first: a count-adjustment
    pair, at the new batch's cost."""
    if level.shortfall <= 0:
        return ZERO
    stock = engine.lock_stock(level.branch, batch)
    settle = min(level.shortfall, stock.quantity)
    if settle <= 0:
        return ZERO
    move(
        level=level,
        batch=batch,
        quantity=-settle,
        kind=Kind.COUNT_ADJUSTMENT,
        by=by,
        document=document,
        reason="shortfall",
        at=at,
        stock=stock,
    )
    move(
        level=level,
        batch=None,
        quantity=settle,
        kind=Kind.COUNT_ADJUSTMENT,
        by=by,
        document=document,
        reason="shortfall",
        at=at,
    )
    return settle


# Goods receipts ------------------------------------------------------------------------------

LINE_FIELDS = (
    "product",
    "series",
    "expires_on",
    "made_on",
    "packs",
    "unit_cost",
    "vat_percent",
    "retail_price",
    "supplier_rx",
)
EDITABLE_RECEIPT = (GoodsReceipt.Status.DRAFT, GoodsReceipt.Status.SUBMITTED)


def _lock_receipt(receipt: GoodsReceipt) -> GoodsReceipt:
    return (
        GoodsReceipt.objects.select_for_update()
        .select_related("company", "branch", "supplier")
        .get(pk=receipt.pk)
    )


def _editable(receipt: GoodsReceipt) -> None:
    if receipt.status not in EDITABLE_RECEIPT:
        raise DomainError(_("A posted or void receipt can't be changed."))


@transaction.atomic
def create_receipt(
    company,
    *,
    by: Membership,
    branch,
    supplier,
    supplier_invoice_date: date,
    supplier_invoice_number: str = "",
    currency: str | None = None,
    due_on: date | None = None,
    note: str = "",
    file=None,
    e_invoice_ref: str = "",
    lines=(),
) -> GoodsReceipt:
    """A draft delivery. `lines` are dicts of `add_line`'s fields."""
    _same_company(company.pk, branch, supplier)
    receipt = GoodsReceipt(
        company=company,
        branch=branch,
        supplier=supplier,
        supplier_invoice_date=supplier_invoice_date,
        supplier_invoice_number=_text(supplier_invoice_number, 40),
        currency=currency or company.base_currency,
        due_on=due_on,
        note=_text(note, 2000),
        e_invoice_ref=_text(e_invoice_ref, 64),
        received_by=by,
    )
    _check_invoice_number(receipt)
    if file is not None:
        receipt.file.save(file.name, file, save=False)
    receipt.save()
    for line in lines:
        add_line(receipt, by=by, **line)
    _audit(
        Action.RECEIPT_CREATED,
        company.pk,
        by,
        receipt,
        supplier=supplier.name,
        invoice=receipt.supplier_invoice_number,
    )
    _bump(company.pk, "inventory.to_post")
    return receipt


def _check_invoice_number(receipt: GoodsReceipt) -> None:
    if not receipt.supplier_invoice_number:
        return
    clash = (
        GoodsReceipt.objects.filter(
            company_id=receipt.company_id,
            supplier_id=receipt.supplier_id,
            supplier_invoice_number=receipt.supplier_invoice_number,
        )
        .exclude(status=GoodsReceipt.Status.VOID)
        .exclude(pk=receipt.pk)
    )
    if clash.exists():
        raise DomainError(
            _("Invoice %(number)s of this distributor is already in.")
            % {"number": receipt.supplier_invoice_number}
        )


RECEIPT_FIELDS = (
    "branch",
    "supplier",
    "supplier_invoice_number",
    "supplier_invoice_date",
    "currency",
    "due_on",
    "note",
    "e_invoice_ref",
)


@transaction.atomic
def update_receipt(receipt: GoodsReceipt, *, by: Membership, file=None, **fields) -> GoodsReceipt:
    unknown = set(fields) - set(RECEIPT_FIELDS)
    if unknown:
        raise ValueError(f"Unknown receipt fields: {sorted(unknown)}")
    receipt = _lock_receipt(receipt)
    _editable(receipt)
    _same_company(receipt.company_id, fields.get("branch"), fields.get("supplier"))
    for field, value in fields.items():
        if field in ("supplier_invoice_number", "note", "e_invoice_ref"):
            value = _text(value, {"supplier_invoice_number": 40, "note": 2000}.get(field, 64))
        setattr(receipt, field, value)
    _check_invoice_number(receipt)
    if file is not None:
        receipt.file.save(file.name, file, save=False)
    receipt.save()
    _refresh_receipt(receipt)
    _audit(Action.RECEIPT_CHANGED, receipt.company_id, by, receipt, fields=sorted(fields))
    _bump(receipt.company_id, "inventory.to_post")
    return receipt


def _line_values(receipt: GoodsReceipt, line: GoodsReceiptLine, fields: dict) -> None:
    """Fill a draft line. Its retail price is the pricing rules' proposal (capped for a
    prescription medicine) until someone types one; a typed price above the cap is lowered
    to it when the receipt is posted, with a warning."""
    for field, value in fields.items():
        if field == "series":
            value = _text(value, 40)
        setattr(line, field, value)
    product = line.product
    _same_company(receipt.company_id, product)
    if not line.series:
        raise DomainError(_("Give the series printed on the pack."))
    if line.expires_on is None:
        raise DomainError(_("Give the expiry date."))
    packs = Decimal(line.packs)
    if packs <= 0:
        raise DomainError(_("Give how many packs came."))
    if Decimal(line.unit_cost) < 0:
        raise DomainError(_("A cost can't be below zero."))
    line.packs = packs
    line.quantity = parts(packs * product.units_per_pack)
    if line.quantity != line.quantity.to_integral_value():
        raise DomainError(
            _("%(product)s has %(parts)s parts a pack: give packs that make whole parts.")
            % {"product": product.name, "parts": product.units_per_pack}
        )
    line.unit_cost = quantize(Decimal(line.unit_cost))
    line.total = quantize(packs * line.unit_cost)
    if line.vat_percent is None:
        line.vat_percent = product.vat_percent
    _check_licensed(receipt.branch, product)
    if line.retail_price is None or ("unit_cost" in fields and "retail_price" not in fields):
        settings = conf.get_settings(receipt.company)
        line.retail_price, _lowered = pricing.suggest_price(
            product, _in_base(receipt, line.unit_cost), settings
        )
    line.warnings = line_warnings(receipt, line)


@transaction.atomic
def add_line(receipt: GoodsReceipt, *, by: Membership, **fields) -> GoodsReceiptLine:
    unknown = set(fields) - set(LINE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown receipt line fields: {sorted(unknown)}")
    receipt = _lock_receipt(receipt)
    _editable(receipt)
    line = GoodsReceiptLine(receipt=receipt, order=receipt.lines.count())
    _line_values(receipt, line, {"made_on": None, "vat_percent": None, **fields})
    line.save()
    _refresh_receipt(receipt)
    _bump(receipt.company_id, "inventory.to_post")
    return line


@transaction.atomic
def update_line(line: GoodsReceiptLine, *, by: Membership, **fields) -> GoodsReceiptLine:
    unknown = set(fields) - set(LINE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown receipt line fields: {sorted(unknown)}")
    receipt = _lock_receipt(line.receipt)
    _editable(receipt)
    line = GoodsReceiptLine.objects.select_related("product").get(pk=line.pk)
    _line_values(receipt, line, fields)
    line.save()
    _refresh_receipt(receipt)
    _bump(receipt.company_id, "inventory.to_post")
    return line


@transaction.atomic
def remove_line(line: GoodsReceiptLine, *, by: Membership) -> None:
    receipt = _lock_receipt(line.receipt)
    _editable(receipt)
    line.delete()
    _refresh_receipt(receipt)


def _refresh_receipt(receipt: GoodsReceipt) -> None:
    lines = list(receipt.lines.all())
    receipt.total = quantize(sum((line.total for line in lines), ZERO))
    vat = ZERO
    for line in lines:
        if line.vat_percent:
            rate = Decimal(line.vat_percent)
            vat += line.total * rate / (100 + rate)
    receipt.vat_total = quantize(vat)
    receipt.save(update_fields=["total", "vat_total", "updated_at"])


def line_warnings(receipt: GoodsReceipt, line: GoodsReceiptLine) -> list[str]:
    """What the pharmacist should look at before posting (never blocks, §14.6.2)."""
    from apps.inventory import queries

    W = GoodsReceiptLine.Warning
    product = line.product
    company = receipt.company
    settings = conf.get_settings(company)
    today = engine.local_today(company)
    found: list[str] = []
    if line.expires_on is not None and (line.expires_on - today).days < settings.min_shelf_days:
        found.append(W.SHORT_SHELF_LIFE)
    cost = _in_base(receipt, line.unit_cost)
    last = Product.objects.filter(pk=product.pk).values_list("cost_price", flat=True).first()
    if last and cost > last * (1 + Decimal(settings.price_jump_percent) / 100):
        found.append(W.COST_JUMP)
    if open_recall_for(company, product, line.series) is not None:
        found.append(W.RECALLED_SERIES)
    if product.registration_until is not None and product.registration_until < today:
        found.append(W.REGISTRATION_EXPIRED)
    if line.supplier_rx and not product.rx_required:
        found.append(W.RX_FLAG_MISMATCH)
    maker = product.manufacturer
    if maker is not None and maker.country and maker.country.upper() != "UZ":
        profile = SupplierProfile.objects.filter(counterparty_id=receipt.supplier_id).first()
        if profile is None or not profile.official_dealer:
            found.append(W.NOT_OFFICIAL_DEALER)
    if product.control_class == Product.ControlClass.PSYCHOTROPIC:
        daily = queries.velocity(company, branch_ids=[receipt.branch_id], days=28).get(
            (receipt.branch_id, product.pk), ZERO
        )
        level = StockLevel.objects.filter(branch_id=receipt.branch_id, product=product).first()
        on_hand = (level.quantity if level else ZERO) + Decimal(line.quantity or 0)
        need = daily * 30 * settings.psychotropic_stock_months
        # Without sales lines there is no need to compare with (velocity 0): no warning.
        if daily > 0 and on_hand > need:
            found.append(W.OVER_MONTH_NEED)
    wanted = line.retail_price
    if product.rx_required:
        _price, lowered = pricing.suggest_price(product, cost, settings, wanted=wanted)
        if lowered and wanted is not None:
            found.append(W.OVER_PRICE_CAP)
    if not is_licensed_for(receipt.branch, product):
        found.append(W.NOT_LICENSED_BRANCH)
    return [str(code) for code in found]


def open_recall_for(company, product: Product, series: str) -> RecallNotice | None:
    """An open recall naming this series of the product (by the product, its INN or its
    name)."""
    series = (series or "").strip()
    if not series:
        return None
    match = Q(product=product)
    if product.inn:
        match |= Q(product__isnull=True, inn_or_name__iexact=product.inn)
    match |= Q(product__isnull=True, inn_or_name__iexact=product.name)
    return (
        RecallNotice.objects.for_company(company)
        .filter(status=RecallNotice.Status.OPEN, series__iexact=series)
        .filter(match)
        .order_by("-received_on", "-pk")
        .first()
    )


def _in_base(receipt: GoodsReceipt, amount) -> Decimal:
    """`amount` of the receipt's currency in the company's base currency, at the invoice day's
    rate (Finance's rates)."""
    amount = Decimal(amount)
    company = receipt.company
    if receipt.currency == company.base_currency:
        return quantize(amount)
    from apps.finance.rates import rate_for

    return quantize(
        amount * rate_for(company, receipt.currency, receipt.supplier_invoice_date).rate
    )


@transaction.atomic
def submit_receipt(receipt: GoodsReceipt, *, by: Membership) -> GoodsReceipt:
    """The pharmacist is done: someone with stock.manage posts it."""
    receipt = _lock_receipt(receipt)
    if receipt.status == GoodsReceipt.Status.SUBMITTED:
        return receipt
    if receipt.status != GoodsReceipt.Status.DRAFT:
        raise DomainError(_("Only a draft can be sent for posting."))
    if not receipt.lines.exists():
        raise DomainError(_("Add the lines of the invoice first."))
    receipt.status = GoodsReceipt.Status.SUBMITTED
    receipt.submitted_at = timezone.now()
    receipt.save(update_fields=["status", "submitted_at", "updated_at"])
    _audit(Action.RECEIPT_SUBMITTED, receipt.company_id, by, receipt)
    from apps.inventory import notify

    transaction.on_commit(partial(notify.receipt_waiting, receipt.pk))
    _bump(receipt.company_id, "inventory.to_post")
    return receipt


@transaction.atomic
def post_receipt(receipt: GoodsReceipt, *, by: Membership) -> GoodsReceipt:
    """Post a delivery, in one transaction: its number, one batch per line on stock (the
    product's shortfall at the branch settled first), the last cost and the retail prices, the
    warnings, and the payable through Finance (with the Finance module on). Posting twice
    changes nothing and opens no second payable."""
    from apps.finance.sources import Source

    receipt = _lock_receipt(receipt)
    if receipt.status == GoodsReceipt.Status.POSTED:
        return receipt
    if receipt.status not in EDITABLE_RECEIPT:
        raise DomainError(_("A void receipt can't be posted."))
    lines = list(receipt.lines.select_related("product__company", "product__manufacturer"))
    if not lines:
        raise DomainError(_("Add the lines of the invoice first."))
    if not receipt.supplier_invoice_number:
        raise DomainError(_("Give the distributor's invoice number."))
    company = receipt.company
    branch = receipt.branch
    settings = conf.get_settings(company)
    rules = list(PricingRule.objects.for_company(company).filter(is_active=True))
    for line in lines:
        _check_licensed(branch, line.product)
    number = _next_number(company, "next_receipt_number")
    receipt.number = f"KR-{_code(branch)}-{number:04d}"
    receipt.due_on = receipt.due_on or due_date(receipt.supplier, receipt.supplier_invoice_date)
    now = timezone.now()
    document = (RECEIPT, receipt.pk)
    levels = lock_levels((branch, line.product) for line in lines)
    jumps = []
    for line in lines:
        product = line.product
        line.warnings = line_warnings(receipt, line)
        cost = _in_base(receipt, line.unit_cost)
        price, lowered = pricing.suggest_price(
            product, cost, settings, wanted=line.retail_price, rules=rules
        )
        if (
            lowered
            and line.retail_price is not None
            and GoodsReceiptLine.Warning.OVER_PRICE_CAP not in line.warnings
        ):
            line.warnings.append(GoodsReceiptLine.Warning.OVER_PRICE_CAP)
        line.retail_price = price
        line.save(update_fields=["warnings", "retail_price"])
        recall = open_recall_for(company, product, line.series)
        batch = StockBatch.objects.create(
            company=company,
            product=product,
            series=line.series,
            expires_on=line.expires_on,
            made_on=line.made_on,
            supplier=receipt.supplier,
            unit_cost=cost,
            retail_price=price,
            receipt_line=line,
            status=StockBatch.Status.RECALLED if recall else StockBatch.Status.SELLABLE,
        )
        level = levels[(branch.pk, product.pk)]
        move(
            level=level,
            batch=batch,
            quantity=line.quantity,
            kind=Kind.RECEIPT,
            by=by,
            document=document,
            at=now,
        )
        _settle_shortfall(level, batch, by=by, document=document, at=now)
        if GoodsReceiptLine.Warning.COST_JUMP in line.warnings:
            jumps.append(
                {"product": product.name, "before": str(product.cost_price), "now": str(cost)}
            )
        Product.objects.filter(pk=product.pk).update(cost_price=cost)
        product.cost_price = cost
        if recall is not None:
            _add_found(recall, branch, batch, line.quantity)
    receipt.status = GoodsReceipt.Status.POSTED
    receipt.posted_by = by
    receipt.posted_at = now
    if company.has_feature("finance") and receipt.total > 0:
        from apps.finance import services as finance

        receipt.debt = finance.open_debt(
            company,
            by=by,
            direction="payable",
            kind="trade",
            amount=receipt.total,
            currency=receipt.currency,
            issued_on=receipt.supplier_invoice_date,
            counterparty=receipt.supplier,
            due_on=receipt.due_on,
            category="goods",
            branch=branch,
            description=_("Goods receipt %(number)s, invoice %(invoice)s")
            % {"number": receipt.number, "invoice": receipt.supplier_invoice_number},
            source=Source(RECEIPT, receipt.pk),
        )
    receipt.save()
    for line in lines:
        engine.refresh_sale_price(line.product)
    _audit(
        Action.RECEIPT_POSTED,
        company.pk,
        by,
        receipt,
        number=receipt.number,
        total=str(receipt.total),
        due_on=receipt.due_on.isoformat() if receipt.due_on else None,
        lines=len(lines),
    )
    if jumps:
        from apps.inventory import notify

        transaction.on_commit(partial(notify.cost_jump, receipt.pk, jumps))
    _bump(company.pk, "inventory.to_post", "inventory.low", "inventory.expiring")
    return receipt


@transaction.atomic
def void_receipt(receipt: GoodsReceipt, *, by: Membership, reason: str) -> GoodsReceipt:
    """A draft goes away; a posted delivery only while none of its batches moved since (sold,
    sent, written off, counted): its stock and its unpaid payable are taken back. A payable with
    a payment refuses: return the goods to the distributor instead."""
    reason = _text(reason, 300)
    if not reason:
        raise DomainError(_("Say why."))
    receipt = _lock_receipt(receipt)
    if receipt.status == GoodsReceipt.Status.VOID:
        return receipt
    company = receipt.company
    if receipt.status == GoodsReceipt.Status.POSTED:
        document = (RECEIPT, receipt.pk)
        batches = list(
            StockBatch.objects.filter(receipt_line__receipt=receipt).select_related("product")
        )
        later = StockMovement.objects.filter(batch__in=batches).exclude(
            document_type=RECEIPT, document_id=receipt.pk
        )
        if later.exists():
            raise DomainError(
                _(
                    "Some of these goods were already sold, moved or counted: the receipt can't "
                    "be voided. Return the goods to the distributor instead."
                )
            )
        if receipt.debt_id:
            from apps.finance import services as finance
            from apps.finance.models import Debt

            debt = Debt.objects.get(pk=receipt.debt_id)
            if debt.status != Debt.Status.CANCELLED:
                if debt.paid > 0:
                    raise DomainError(
                        _(
                            "The distributor was already paid for it: return the goods instead "
                            "of voiding the receipt."
                        )
                    )
                finance.cancel_debt(
                    debt,
                    by=by,
                    reason=_("Goods receipt %(number)s voided: %(reason)s")
                    % {"number": receipt.number, "reason": reason},
                )
        movements = list(
            StockMovement.objects.filter(document_type=RECEIPT, document_id=receipt.pk)
            .select_related("batch__product", "product")
            .order_by("pk")
        )
        levels = lock_levels((receipt.branch, movement.product) for movement in movements)
        for movement in reversed(movements):
            level = levels[(receipt.branch.pk, movement.product_id)]
            move(
                level=level,
                batch=movement.batch,
                quantity=-movement.quantity,
                kind=movement.kind,
                by=by,
                document=document,
                reason="void",
            )
        for product in {batch.product_id: batch.product for batch in batches}.values():
            last = (
                StockBatch.objects.filter(
                    product=product, receipt_line__receipt__status=GoodsReceipt.Status.POSTED
                )
                .exclude(receipt_line__receipt=receipt)
                .order_by("-created_at", "-pk")
                .first()
            )
            Product.objects.filter(pk=product.pk).update(
                cost_price=last.unit_cost if last else product.cost_price
            )
            engine.refresh_sale_price(product)
    receipt.status = GoodsReceipt.Status.VOID
    receipt.voided_at = timezone.now()
    receipt.voided_by = by
    receipt.void_reason = reason
    receipt.save()
    _audit(Action.RECEIPT_VOIDED, company.pk, by, receipt, reason=reason)
    _bump(company.pk, "inventory.to_post", "inventory.low")
    return receipt


# Batches and prices -------------------------------------------------------------------------


def _lock_batch(batch: StockBatch) -> StockBatch:
    return (
        StockBatch.objects.select_for_update().select_related("product__company").get(pk=batch.pk)
    )


def _status_event(batch: StockBatch, kind: str, *, by, reason: str) -> None:
    """A zero movement per branch holding the batch: it left (or came back to) sale there."""
    for stock in BatchStock.objects.filter(batch=batch, quantity__gt=0).select_related("branch"):
        level = engine.lock_level(stock.branch, batch.product)
        move(
            level=level,
            batch=batch,
            quantity=0,
            kind=kind,
            by=by,
            document=(BATCH, batch.pk),
            reason=reason,
        )


@transaction.atomic
def quarantine(batch: StockBatch, *, by: Membership, reason: str) -> StockBatch:
    """Take a series off sale in every branch (a suspected quality problem)."""
    batch = _lock_batch(batch)
    if batch.status == StockBatch.Status.RECALLED:
        raise DomainError(_("This series is recalled."))
    if batch.status != StockBatch.Status.QUARANTINE:
        batch.status = StockBatch.Status.QUARANTINE
        batch.save(update_fields=["status", "updated_at"])
        _status_event(batch, Kind.QUARANTINE, by=by, reason=_text(reason, 16))
        engine.refresh_sale_price(batch.product)
        _audit(
            Action.BATCH_QUARANTINED,
            batch.company_id,
            by,
            batch,
            series=batch.series,
            reason=_text(reason, 200),
        )
        _bump(batch.company_id)
    return batch


@transaction.atomic
def release(batch: StockBatch, *, by: Membership, reason: str) -> StockBatch:
    """Put a quarantined series back on sale (never a recalled one)."""
    batch = _lock_batch(batch)
    if batch.status == StockBatch.Status.RECALLED:
        raise DomainError(_("A recalled series stays off sale until it is written off."))
    if batch.status == StockBatch.Status.QUARANTINE:
        batch.status = StockBatch.Status.SELLABLE
        batch.save(update_fields=["status", "updated_at"])
        _status_event(batch, Kind.RELEASE, by=by, reason=_text(reason, 16))
        engine.refresh_sale_price(batch.product)
        _audit(
            Action.BATCH_RELEASED,
            batch.company_id,
            by,
            batch,
            series=batch.series,
            reason=_text(reason, 200),
        )
        _bump(batch.company_id)
    return batch


def batch_ceiling(batch: StockBatch) -> Decimal | None:
    settings = conf.get_settings(batch.product.company)
    return pricing.price_ceiling(batch.product, batch.unit_cost, settings)


@transaction.atomic
def set_price(batch: StockBatch, *, by: Membership, price, reason: str = "") -> StockBatch:
    """A batch's retail price per pack (a markdown of a batch close to expiry, a correction).
    With `cap_enforced`, a prescription batch can't be priced above its legal cap."""
    batch = _lock_batch(batch)
    price = quantize(Decimal(price))
    if price <= 0:
        raise DomainError(_("Give a price above zero."))
    product = batch.product
    settings = conf.get_settings(product.company)
    ceiling = pricing.price_ceiling(product, batch.unit_cost, settings)
    if ceiling is not None and price > ceiling and settings.cap_enforced:
        raise DomainError(
            _("%(price)s is above the legal maximum of %(cap)s for this prescription medicine.")
            % {
                "price": f"{price:,.0f}".replace(",", " "),
                "cap": f"{ceiling:,.0f}".replace(",", " "),
            }
        )
    before = batch.retail_price
    if before != price:
        batch.retail_price = price
        batch.save(update_fields=["retail_price", "updated_at"])
        engine.refresh_sale_price(product)
        _audit(
            Action.PRICE_CHANGED,
            batch.company_id,
            by,
            batch,
            series=batch.series,
            before=str(before),
            after=str(price),
            reason=_text(reason, 200),
        )
        _bump(batch.company_id)
    return batch


def set_markdown(batch: StockBatch, *, by: Membership, price) -> StockBatch:
    return set_price(batch, by=by, price=price, reason="markdown")


# Transfers -------------------------------------------------------------------------------------


def _lock_transfer(transfer: StockTransfer) -> StockTransfer:
    return (
        StockTransfer.objects.select_for_update()
        .select_related("company", "from_branch", "to_branch")
        .get(pk=transfer.pk)
    )


@transaction.atomic
def create_transfer(
    company, *, by: Membership, from_branch, to_branch, lines, note: str = ""
) -> StockTransfer:
    """A draft transfer. `lines`: dicts of product, quantity (parts) and optionally batch
    (else FEFO decides when it is sent)."""
    _same_company(company.pk, from_branch, to_branch)
    if from_branch.pk == to_branch.pk:
        raise DomainError(_("Pick two different pharmacies."))
    if not lines:
        raise DomainError(_("Add what to send."))
    transfer = StockTransfer.objects.create(
        company=company,
        from_branch=from_branch,
        to_branch=to_branch,
        note=_text(note, 2000),
        created_by=by,
    )
    for line in lines:
        product = line["product"]
        batch = line.get("batch")
        _same_company(company.pk, product, batch)
        if batch is not None and batch.product_id != product.pk:
            raise DomainError(_("That series is of another item."))
        _check_licensed(to_branch, product)
        quantity = parts(line["quantity"])
        if quantity <= 0:
            raise DomainError(_("Give a quantity above zero."))
        StockTransferLine.objects.create(
            transfer=transfer, product=product, batch=batch, quantity_sent=quantity
        )
    _audit(
        Action.TRANSFER_CREATED,
        company.pk,
        by,
        transfer,
        from_branch=from_branch.name,
        to_branch=to_branch.name,
    )
    _bump(company.pk)
    return transfer


@transaction.atomic
def send_transfer(transfer: StockTransfer, *, by: Membership) -> StockTransfer:
    """The goods leave: the named batches (or FEFO) are taken at the sending pharmacy and are
    on the way until received. An expired batch can't be sent."""
    transfer = _lock_transfer(transfer)
    if transfer.status == StockTransfer.Status.SENT:
        return transfer
    if transfer.status != StockTransfer.Status.DRAFT:
        raise DomainError(_("Only a draft can be sent."))
    company = transfer.company
    source = transfer.from_branch
    today = engine.local_today(company)
    lines = list(transfer.lines.select_related("product__company", "batch__product"))
    levels = lock_levels((source, line.product) for line in lines)
    document = (TRANSFER, transfer.pk)
    now = timezone.now()
    for line in lines:
        level = levels[(source.pk, line.product_id)]
        if line.batch_id:
            batch = line.batch
            if engine.is_expired(batch, today):
                raise DomainError(
                    _("Series %(series)s has expired: it can't be sent.") % {"series": batch.series}
                )
            move(
                level=level,
                batch=batch,
                quantity=-line.quantity_sent,
                kind=Kind.TRANSFER_OUT,
                by=by,
                document=document,
                at=now,
            )
            continue
        remaining = line.quantity_sent
        first = True
        stocks = engine.fefo_stocks(source, line.product, today)
        available = sum((stock.quantity for stock in stocks), ZERO)
        if available < remaining:
            raise DomainError(
                _("Only %(left)s parts of %(product)s are on sale at %(branch)s.")
                % {
                    "left": available.normalize(),
                    "product": line.product.name,
                    "branch": source.name,
                }
            )
        for stock in stocks:
            if remaining <= 0:
                break
            take = min(stock.quantity, remaining)
            move(
                level=level,
                batch=stock.batch,
                quantity=-take,
                kind=Kind.TRANSFER_OUT,
                by=by,
                document=document,
                at=now,
                stock=stock,
            )
            if first:
                line.batch, line.quantity_sent = stock.batch, take
                line.save(update_fields=["batch", "quantity_sent"])
                first = False
            else:
                StockTransferLine.objects.create(
                    transfer=transfer, product=line.product, batch=stock.batch, quantity_sent=take
                )
            remaining -= take
    number = _next_number(company, "next_transfer_number")
    transfer.number = f"TR-{_code(source)}-{number:04d}"
    transfer.status = StockTransfer.Status.SENT
    transfer.sent_by, transfer.sent_at = by, now
    transfer.save()
    for line in lines:
        engine.refresh_sale_price(line.product)
    _audit(Action.TRANSFER_SENT, company.pk, by, transfer, number=transfer.number)
    from apps.inventory import notify

    transaction.on_commit(partial(notify.transfer_incoming, transfer.pk))
    _bump(company.pk, "inventory.low")
    return transfer


@transaction.atomic
def receive_transfer(
    transfer: StockTransfer, *, by: Membership, received: dict[int, Decimal] | None = None
) -> StockTransfer:
    """The same batches arrive at the receiving pharmacy. `received` maps line ids to what
    arrived (everything as sent when missing). Less than sent makes the transfer disputed: both
    heads hear, and the missing parts stay on the way until a manager resolves it."""
    transfer = _lock_transfer(transfer)
    if transfer.status in (StockTransfer.Status.RECEIVED, StockTransfer.Status.DISPUTED):
        return transfer
    if transfer.status != StockTransfer.Status.SENT:
        raise DomainError(_("This transfer wasn't sent."))
    received = {int(key): parts(value) for key, value in (received or {}).items()}
    destination = transfer.to_branch
    lines = list(transfer.lines.select_related("product__company", "batch__product"))
    unknown = set(received) - {line.pk for line in lines}
    if unknown:
        raise DomainError(_("That line isn't on this transfer."))
    levels = lock_levels((destination, line.product) for line in lines)
    document = (TRANSFER, transfer.pk)
    now = timezone.now()
    short = False
    for line in lines:
        quantity = received.get(line.pk, line.quantity_sent)
        if quantity < 0 or quantity > line.quantity_sent:
            raise DomainError(_("Received can't be more than sent, or below zero."))
        line.quantity_received = quantity
        line.save(update_fields=["quantity_received"])
        short = short or quantity < line.quantity_sent
        if quantity > 0:
            level = levels[(destination.pk, line.product_id)]
            move(
                level=level,
                batch=line.batch,
                quantity=quantity,
                kind=Kind.TRANSFER_IN,
                by=by,
                document=document,
                at=now,
            )
            _settle_shortfall(level, line.batch, by=by, document=document, at=now)
    transfer.status = StockTransfer.Status.DISPUTED if short else StockTransfer.Status.RECEIVED
    transfer.received_by, transfer.received_at = by, now
    transfer.save()
    for line in lines:
        engine.refresh_sale_price(line.product)
    _audit(
        Action.TRANSFER_RECEIVED,
        transfer.company_id,
        by,
        transfer,
        number=transfer.number,
        disputed=short,
    )
    if short:
        from apps.inventory import notify

        transaction.on_commit(partial(notify.transfer_disputed, transfer.pk))
    _bump(transfer.company_id, "inventory.low")
    return transfer


@transaction.atomic
def resolve_transfer(
    transfer: StockTransfer, *, by: Membership, outcome: str, note: str = ""
) -> StockTransfer:
    """Settle what went missing on the way: lost (written off as a shortage at the sending
    pharmacy, at cost), found at the receiving pharmacy, or back at the sending one."""
    transfer = _lock_transfer(transfer)
    if transfer.status != StockTransfer.Status.DISPUTED:
        raise DomainError(_("Only a disputed transfer needs resolving."))
    if outcome not in StockTransfer.Resolution.values:
        raise DomainError(_("Pick what happened to the missing goods."))
    lines = [
        line
        for line in transfer.lines.select_related("product__company", "batch__product")
        if (line.quantity_received or ZERO) < line.quantity_sent
    ]
    document = (TRANSFER, transfer.pk)
    now = timezone.now()
    if outcome == StockTransfer.Resolution.SHORTAGE:
        writeoff = WriteOff.objects.create(
            company_id=transfer.company_id,
            branch=transfer.from_branch,
            reason=WriteOff.Reason.SHORTAGE,
            status=WriteOff.Status.APPROVED,
            note=_text(note, 2000)
            or _("Lost on the way: transfer %(number)s") % {"number": transfer.number},
            proposed_by=by,
            approved_by=by,
            approved_at=now,
            transfer=transfer,
        )
        total = ZERO
        for line in lines:
            missing = line.quantity_sent - (line.quantity_received or ZERO)
            value = engine.value_of(line.batch, missing)
            WriteOffLine.objects.create(
                writeoff=writeoff,
                batch=line.batch,
                quantity=missing,
                unit_cost=engine.part_cost(line.batch),
                value=value,
            )
            total += value
        number = _next_number(transfer.company, "next_writeoff_number")
        writeoff.number = f"AKT-{_code(transfer.from_branch)}-{number:04d}"
        writeoff.value = quantize(total)
        writeoff.save(update_fields=["number", "value", "updated_at"])
    else:
        branch = (
            transfer.to_branch
            if outcome == StockTransfer.Resolution.FOUND
            else transfer.from_branch
        )
        levels = lock_levels((branch, line.product) for line in lines)
        for line in lines:
            missing = line.quantity_sent - (line.quantity_received or ZERO)
            level = levels[(branch.pk, line.product_id)]
            move(
                level=level,
                batch=line.batch,
                quantity=missing,
                kind=Kind.TRANSFER_IN,
                by=by,
                document=document,
                reason=str(outcome),
                at=now,
            )
            if outcome == StockTransfer.Resolution.FOUND:
                line.quantity_received = line.quantity_sent
                line.save(update_fields=["quantity_received"])
    transfer.status = StockTransfer.Status.RECEIVED
    transfer.resolution = outcome
    transfer.resolved_by, transfer.resolved_at = by, now
    if note:
        transfer.note = "\n".join(part for part in (transfer.note, _text(note, 1000)) if part)
    transfer.save()
    _audit(Action.TRANSFER_RESOLVED, transfer.company_id, by, transfer, outcome=outcome, note=note)
    _bump(transfer.company_id, "inventory.low")
    return transfer


@transaction.atomic
def void_transfer(transfer: StockTransfer, *, by: Membership, reason: str) -> StockTransfer:
    """A draft is dropped; a transfer on the way is called back (its goods return to the
    sending pharmacy)."""
    reason = _text(reason, 300)
    if not reason:
        raise DomainError(_("Say why."))
    transfer = _lock_transfer(transfer)
    if transfer.status == StockTransfer.Status.VOID:
        return transfer
    if transfer.status not in (StockTransfer.Status.DRAFT, StockTransfer.Status.SENT):
        raise DomainError(_("A received transfer can't be voided."))
    if transfer.status == StockTransfer.Status.SENT:
        lines = list(transfer.lines.select_related("product__company", "batch__product"))
        levels = lock_levels((transfer.from_branch, line.product) for line in lines)
        for line in lines:
            move(
                level=levels[(transfer.from_branch.pk, line.product_id)],
                batch=line.batch,
                quantity=line.quantity_sent,
                kind=Kind.TRANSFER_IN,
                by=by,
                document=(TRANSFER, transfer.pk),
                reason="void",
            )
    transfer.status = StockTransfer.Status.VOID
    transfer.voided_at = timezone.now()
    transfer.void_reason = reason
    transfer.save()
    _audit(Action.TRANSFER_VOIDED, transfer.company_id, by, transfer, reason=reason)
    _bump(transfer.company_id)
    return transfer


# Write-offs ------------------------------------------------------------------------------------


def _lock_writeoff(writeoff: WriteOff) -> WriteOff:
    return (
        WriteOff.objects.select_for_update().select_related("company", "branch").get(pk=writeoff.pk)
    )


@transaction.atomic
def propose_writeoff(
    company,
    *,
    by: Membership,
    branch,
    reason: str,
    lines,
    note: str = "",
    files=(),
    recall=None,
) -> WriteOff:
    """Goods to take off stock, with the reason and photos. `lines`: dicts of batch and
    quantity (parts). Without `writeoff_approval` it is approved at once."""
    _same_company(company.pk, branch, recall)
    if reason not in WriteOff.Reason.values:
        raise DomainError(_("Pick the reason."))
    if not lines:
        raise DomainError(_("Add what to write off."))
    writeoff = WriteOff.objects.create(
        company=company,
        branch=branch,
        reason=reason,
        note=_text(note, 2000),
        proposed_by=by,
        recall=recall,
    )
    seen = set()
    for line in lines:
        batch = line["batch"]
        _same_company(company.pk, batch)
        quantity = parts(line["quantity"])
        if quantity <= 0:
            raise DomainError(_("Give a quantity above zero."))
        if batch.pk in seen:
            raise DomainError(_("Each series once, please."))
        seen.add(batch.pk)
        held = BatchStock.objects.filter(branch=branch, batch=batch).first()
        if held is None or held.quantity < quantity:
            raise DomainError(
                _("Only %(left)s of series %(series)s is here.")
                % {"left": (held.quantity if held else ZERO).normalize(), "series": batch.series}
            )
        WriteOffLine.objects.create(
            writeoff=writeoff,
            batch=batch,
            quantity=quantity,
            unit_cost=engine.part_cost(batch),
            value=engine.value_of(batch, quantity),
        )
    writeoff.value = quantize(sum((line.value for line in writeoff.lines.all()), ZERO))
    writeoff.save(update_fields=["value", "updated_at"])
    for upload, kind in files:
        _store_writeoff_file(writeoff, upload, kind=kind, by=by)
    _audit(
        Action.WRITEOFF_PROPOSED,
        company.pk,
        by,
        writeoff,
        branch=branch.name,
        reason=reason,
        lines=len(seen),
    )
    _bump(company.pk, "inventory.writeoffs")
    if not conf.get_settings(company).writeoff_approval:
        return approve_writeoff(writeoff, by=by)
    from apps.inventory import notify

    transaction.on_commit(partial(notify.writeoff_waiting, writeoff.pk))
    return writeoff


def _store_writeoff_file(writeoff: WriteOff, upload, *, kind: str, by) -> WriteOffFile:
    if kind not in WriteOffFile.Kind.values:
        raise DomainError(_("Pick what the file is."))
    row = WriteOffFile(writeoff=writeoff, kind=kind, uploaded_by=by)
    row.file.save(upload.name, upload, save=False)
    row.save()
    return row


@transaction.atomic
def add_writeoff_file(writeoff: WriteOff, *, by: Membership, upload, kind: str) -> WriteOffFile:
    writeoff = _lock_writeoff(writeoff)
    if writeoff.status == WriteOff.Status.VOID:
        raise DomainError(_("This write-off is void."))
    row = _store_writeoff_file(writeoff, upload, kind=kind, by=by)
    _audit(Action.WRITEOFF_FILE, writeoff.company_id, by, writeoff, kind=kind)
    return row


@transaction.atomic
def approve_writeoff(writeoff: WriteOff, *, by: Membership) -> WriteOff:
    """Take the goods off stock at their batches' cost and freeze the value. Unfit goods
    (expired, damaged, quality, recall) get a destruction date. No ledger row: the cost was
    booked as a purchase when they arrived."""
    writeoff = _lock_writeoff(writeoff)
    if writeoff.status in (WriteOff.Status.APPROVED, WriteOff.Status.DESTROYED):
        return writeoff
    if writeoff.status != WriteOff.Status.PROPOSED:
        raise DomainError(_("This write-off is void."))
    company = writeoff.company
    branch = writeoff.branch
    lines = list(writeoff.lines.select_related("batch__product__company"))
    levels = lock_levels((branch, line.batch.product) for line in lines)
    document = (WRITEOFF, writeoff.pk)
    now = timezone.now()
    total = ZERO
    for line in lines:
        batch = line.batch
        move(
            level=levels[(branch.pk, batch.product_id)],
            batch=batch,
            quantity=-line.quantity,
            kind=Kind.WRITEOFF,
            by=by,
            document=document,
            reason=writeoff.reason,
            at=now,
        )
        line.unit_cost = engine.part_cost(batch)
        line.value = engine.value_of(batch, line.quantity)
        line.save(update_fields=["unit_cost", "value"])
        total += line.value
    number = _next_number(company, "next_writeoff_number")
    writeoff.number = f"AKT-{_code(branch)}-{number:04d}"
    writeoff.status = WriteOff.Status.APPROVED
    writeoff.approved_by, writeoff.approved_at = by, now
    writeoff.value = quantize(total)
    if writeoff.needs_destruction:
        days = conf.get_settings(company).destroy_within_days
        writeoff.destroy_by = engine.local_today(company, now) + timedelta(days=days)
    writeoff.save()
    for product in {line.batch.product_id: line.batch.product for line in lines}.values():
        engine.refresh_sale_price(product)
    _audit(
        Action.WRITEOFF_APPROVED,
        company.pk,
        by,
        writeoff,
        number=writeoff.number,
        value=str(writeoff.value),
        required_perm="finance.view",
    )
    _close_recalls_of(writeoff, by=by)
    _bump(company.pk, "inventory.writeoffs", "inventory.low", "inventory.expiring")
    return writeoff


def _close_recalls_of(writeoff: WriteOff, *, by) -> None:
    recall_ids = set()
    if writeoff.recall_id:
        recall_ids.add(writeoff.recall_id)
    batch_ids = [line.batch_id for line in writeoff.lines.all()]
    for recall in RecallNotice.objects.filter(
        company_id=writeoff.company_id, status=RecallNotice.Status.OPEN
    ):
        if any(row.get("batch_id") in batch_ids for row in recall.found):
            recall_ids.add(recall.pk)
    for recall in RecallNotice.objects.filter(pk__in=recall_ids, status=RecallNotice.Status.OPEN):
        if recall_left(recall) <= 0:
            _close(recall, by=by)


@transaction.atomic
def mark_destroyed(
    writeoff: WriteOff,
    *,
    by: Membership,
    method: str,
    place: str,
    destroyed_at: datetime,
    responsible: str,
    order_number: str,
    commission: list[dict],
    sent_to: list[str] = (),
    language: str | None = None,
) -> WriteOff:
    """Record the destruction of unfit goods (§14.4 row 30): method, place, date and time, the
    person named by the owner's order and its number, a commission of at least
    `destroy_commission_min` people, and at least one photo or video already attached. The act
    PDF is made in the company's language."""
    writeoff = _lock_writeoff(writeoff)
    if writeoff.status == WriteOff.Status.DESTROYED:
        return writeoff
    if writeoff.status != WriteOff.Status.APPROVED:
        raise DomainError(_("Approve the write-off first."))
    if not writeoff.needs_destruction:
        raise DomainError(_("This write-off has no destruction step."))
    settings = conf.get_settings(writeoff.company)
    if method not in WriteOff.Method.values:
        raise DomainError(_("Pick how the goods were destroyed."))
    members = [
        {
            "name": _text(row.get("name"), 150),
            "organisation": _text(row.get("organisation"), 150),
            "role": _text(row.get("role"), 100),
        }
        for row in commission or []
        if _text(row.get("name"), 150)
    ]
    if len(members) < settings.destroy_commission_min:
        raise DomainError(
            _("The commission needs at least %(count)s members.")
            % {"count": settings.destroy_commission_min}
        )
    if not _text(place, 200) or not _text(responsible, 150) or not _text(order_number, 40):
        raise DomainError(_("Give the place, the responsible person and the order number."))
    if not writeoff.files.filter(
        kind__in=(WriteOffFile.Kind.PHOTO, WriteOffFile.Kind.VIDEO)
    ).exists():
        raise DomainError(_("Add at least one photo of the destruction."))
    writeoff.method = method
    writeoff.place = _text(place, 200)
    writeoff.destroyed_at = destroyed_at
    writeoff.responsible = _text(responsible, 150)
    writeoff.order_number = _text(order_number, 40)
    writeoff.commission = members
    writeoff.sent_to = [_text(name, 150) for name in sent_to if _text(name, 150)]
    writeoff.status = WriteOff.Status.DESTROYED
    writeoff.destroyed_by = by
    writeoff.save()
    from django.core.files.base import ContentFile

    from apps.inventory import journals

    data = journals.act_pdf(writeoff, language=language or writeoff.company.default_language)
    writeoff.act_pdf.save(f"{writeoff.pk}.pdf", ContentFile(data), save=True)
    _audit(
        Action.WRITEOFF_DESTROYED,
        writeoff.company_id,
        by,
        writeoff,
        number=writeoff.number,
        method=method,
        commission=len(members),
    )
    _bump(writeoff.company_id, "inventory.writeoffs")
    return writeoff


@transaction.atomic
def void_writeoff(writeoff: WriteOff, *, by: Membership, reason: str) -> WriteOff:
    """Only a proposal can be dropped; approved goods already left the stock."""
    reason = _text(reason, 300)
    if not reason:
        raise DomainError(_("Say why."))
    writeoff = _lock_writeoff(writeoff)
    if writeoff.status == WriteOff.Status.VOID:
        return writeoff
    if writeoff.status != WriteOff.Status.PROPOSED:
        raise DomainError(_("An approved write-off can't be voided."))
    writeoff.status = WriteOff.Status.VOID
    writeoff.voided_at = timezone.now()
    writeoff.void_reason = reason
    writeoff.save()
    _audit(Action.WRITEOFF_VOIDED, writeoff.company_id, by, writeoff, reason=reason)
    _bump(writeoff.company_id, "inventory.writeoffs")
    return writeoff


# Counts ----------------------------------------------------------------------------------------


def _lock_count(count: StockCount) -> StockCount:
    return (
        StockCount.objects.select_for_update().select_related("company", "branch").get(pk=count.pk)
    )


@transaction.atomic
def record_counted(count: StockCount, *, by: Membership, counted: dict[int, Decimal]) -> StockCount:
    """What the counter found, by line id (blind: they never see what was expected)."""
    count = _lock_count(count)
    if count.status != StockCount.Status.OPEN:
        raise DomainError(_("This count is closed."))
    lines = {line.pk: line for line in count.lines.all()}
    for line_id, value in counted.items():
        line = lines.get(int(line_id))
        if line is None:
            raise DomainError(_("That line isn't on this count."))
        if value is None:
            line.counted, line.counted_by = None, None
        else:
            value = parts(value)
            if value < 0:
                raise DomainError(_("A count can't be below zero."))
            line.counted, line.counted_by = value, by
        line.save(update_fields=["counted", "counted_by"])
    return count


@transaction.atomic
def add_found(
    count: StockCount,
    *,
    by: Membership,
    product: Product,
    series: str,
    expires_on: date,
    counted,
) -> StockCountLine:
    """Goods on the shelf the system didn't know: their own line, counted."""
    count = _lock_count(count)
    if count.status != StockCount.Status.OPEN:
        raise DomainError(_("This count is closed."))
    _same_company(count.company_id, product)
    series = _text(series, 40)
    if not series or expires_on is None:
        raise DomainError(_("Give the series and the expiry date printed on the pack."))
    counted = parts(counted)
    if counted <= 0:
        raise DomainError(_("Give a quantity above zero."))
    existing = count.lines.filter(product=product, batch__series=series).first()
    if existing is not None:
        existing.counted, existing.counted_by = counted, by
        existing.save(update_fields=["counted", "counted_by"])
        return existing
    return StockCountLine.objects.create(
        count=count,
        product=product,
        series=series,
        expires_on=expires_on,
        expected=ZERO,
        counted=counted,
        counted_by=by,
        order=count.lines.count(),
    )


@transaction.atomic
def submit_count(count: StockCount, *, by: Membership) -> StockCount:
    count = _lock_count(count)
    if count.status == StockCount.Status.SUBMITTED:
        return count
    if count.status != StockCount.Status.OPEN:
        raise DomainError(_("This count is closed."))
    if not count.lines.filter(counted__isnull=False).exists():
        raise DomainError(_("Count at least one line first."))
    count.status = StockCount.Status.SUBMITTED
    count.submitted_by, count.submitted_at = by, timezone.now()
    count.save()
    _audit(Action.COUNT_SUBMITTED, count.company_id, by, count)
    _bump(count.company_id)
    return count


@transaction.atomic
def apply_count(count: StockCount, *, by: Membership) -> StockCount:
    """Book the differences of the counted lines (uncounted lines change nothing) as count
    adjustments at each batch's cost; goods found that the system didn't know become a batch
    of their own. A shortage above `count_tolerance` at cost tells the owners."""
    count = _lock_count(count)
    if count.status == StockCount.Status.APPLIED:
        return count
    if count.status not in (StockCount.Status.OPEN, StockCount.Status.SUBMITTED):
        raise DomainError(_("This count is closed."))
    lines = list(
        count.lines.filter(counted__isnull=False).select_related(
            "product__company", "batch__product"
        )
    )
    branch = count.branch
    levels = lock_levels((branch, line.product) for line in lines)
    document = (COUNT, count.pk)
    now = timezone.now()
    total = ZERO
    for line in lines:
        level = levels[(branch.pk, line.product_id)]
        batch = line.batch
        if batch is None:
            product = line.product
            batch = StockBatch.objects.create(
                company_id=count.company_id,
                product=product,
                series=line.series,
                expires_on=line.expires_on,
                unit_cost=product.cost_price or ZERO,
                retail_price=product.sale_price,
            )
            line.batch = batch
        stock = engine.lock_stock(branch, batch)
        difference = line.counted - line.expected
        if stock.quantity + difference < 0:
            difference = -stock.quantity  # sold meanwhile: never below zero
        line.difference = difference
        line.save(update_fields=["batch", "difference"])
        if difference:
            move(
                level=level,
                batch=batch,
                quantity=difference,
                kind=Kind.COUNT_ADJUSTMENT,
                by=by,
                document=document,
                reason=str(count.kind),
                at=now,
                stock=stock,
            )
            total += engine.value_of(batch, difference)
    count.status = StockCount.Status.APPLIED
    count.applied_by, count.applied_at = by, now
    count.value_difference = quantize(total)
    count.save()
    for product in {line.product_id: line.product for line in lines}.values():
        engine.refresh_sale_price(product)
    _audit(
        Action.COUNT_APPLIED,
        count.company_id,
        by,
        count,
        value_difference=str(count.value_difference),
        required_perm="finance.view",
    )
    tolerance = conf.get_settings(count.company).count_tolerance
    if count.value_difference < 0 and -count.value_difference > tolerance:
        from apps.inventory import notify

        transaction.on_commit(partial(notify.count_shortage, count.pk))
    _bump(count.company_id, "inventory.low")
    return count


# Recalls ---------------------------------------------------------------------------------------


def _matching_batches(company, *, product, inn_or_name: str, series: str):
    rows = StockBatch.objects.for_company(company).filter(series__iexact=series.strip())
    if product is not None:
        return rows.filter(product=product)
    name = (inn_or_name or "").strip()
    if not name:
        return rows
    return rows.filter(
        Q(product__inn__iexact=normalize_inn(name))
        | Q(product__name__iexact=name)
        | Q(product__trade_name__iexact=name)
        | Q(product__name__istartswith=f"{name} ")
    )


def _add_found(recall: RecallNotice, branch, batch: StockBatch, quantity) -> None:
    found = list(recall.found or [])
    found.append(
        {
            "branch_id": branch.pk,
            "branch": branch.name,
            "batch_id": batch.pk,
            "product_id": batch.product_id,
            "product": batch.product.name,
            "series": batch.series,
            "quantity": str(parts(quantity)),
            "task_id": None,
        }
    )
    RecallNotice.objects.filter(pk=recall.pk).update(found=found)
    recall.found = found


@transaction.atomic
def register_recall(
    company,
    *,
    by: Membership | None,
    series: str,
    reason: str,
    source: str,
    received_on: date,
    product=None,
    inn_or_name: str = "",
    file=None,
) -> RecallNotice:
    """A rejected or recalled series: every matching batch in every branch is set `recalled`
    (off sale), what was found is recorded, and each branch holding it gets one task "Remove
    series X from sale"."""
    from apps.inventory import notify

    _same_company(company.pk, product)
    series = _text(series, 40)
    if not series:
        raise DomainError(_("Give the series."))
    if product is None and not _text(inn_or_name, 200):
        raise DomainError(_("Name the medicine: pick it, or give its INN or name."))
    recall = RecallNotice(
        company=company,
        product=product,
        inn_or_name=_text(inn_or_name, 200) or (product.inn if product else ""),
        series=series,
        reason=_text(reason, 200),
        source=_text(source, 200),
        received_on=received_on,
        created_by=by,
    )
    if file is not None:
        recall.file.save(file.name, file, save=False)
    recall.save()
    batches = list(
        _matching_batches(
            company, product=product, inn_or_name=recall.inn_or_name, series=series
        ).select_related("product")
    )
    found = []
    by_branch: dict[int, list[dict]] = defaultdict(list)
    for batch in batches:
        locked = _lock_batch(batch)
        if locked.status != StockBatch.Status.RECALLED:
            locked.status = StockBatch.Status.RECALLED
            locked.save(update_fields=["status", "updated_at"])
        for stock in BatchStock.objects.filter(batch=batch, quantity__gt=0).select_related(
            "branch"
        ):
            row = {
                "branch_id": stock.branch_id,
                "branch": stock.branch.name,
                "batch_id": batch.pk,
                "product_id": batch.product_id,
                "product": batch.product.name,
                "series": batch.series,
                "quantity": str(stock.quantity),
                "task_id": None,
            }
            found.append(row)
            by_branch[stock.branch_id].append(row)
        engine.refresh_sale_price(batch.product)
    for branch_id, rows in by_branch.items():
        branch = Branch.objects.get(pk=branch_id)
        task = _recall_task(recall, branch, rows)
        for row in rows:
            row["task_id"] = task.pk if task is not None else None
    recall.found = found
    recall.save(update_fields=["found", "updated_at"])
    _audit(
        Action.RECALL_REGISTERED,
        company.pk,
        by,
        recall,
        series=series,
        found=len(found),
    )
    transaction.on_commit(partial(notify.recall, recall.pk))
    _bump(company.pk, "inventory.recalls")
    return recall


def assignee_for(branch) -> Membership | None:
    """Who gets the system's stock tasks for a branch: its head (`Branch.manager`), else the
    first active stock.manage holder whose home branch it is, else the first owner. Only
    someone approved and onboarded."""
    from apps.members.permissions import Perm
    from apps.members.queries import members_with_perm

    def ready(person):
        return (
            person is not None
            and person.status == Membership.Status.APPROVED
            and person.onboarded_at is not None
        )

    if branch.manager_id and ready(branch.manager):
        return branch.manager
    holders = (
        members_with_perm(branch.company, Perm.STOCK_MANAGE)
        .filter(home_branch=branch, onboarded_at__isnull=False)
        .order_by("pk")
    )
    for person in holders:
        if not person.role.is_owner:
            return person
    owner = (
        Membership.objects.for_company(branch.company)
        .filter(status=Membership.Status.APPROVED, role__is_owner=True, onboarded_at__isnull=False)
        .order_by("pk")
        .first()
    )
    return owner


def _recall_task(recall: RecallNotice, branch, rows: list[dict]):
    from apps.tasks.services import create_system_task

    assignee = assignee_for(branch)
    if assignee is None:
        return None
    first = rows[0]
    title = _("Remove series %(series)s of %(product)s from sale") % {
        "series": recall.series,
        "product": first["product"],
    }
    description = _(
        "Recall: %(reason)s (%(source)s). Put every pack of this series in the quarantine "
        "zone and propose a write-off."
    ) % {"reason": recall.reason, "source": recall.source}
    checklist = [
        _("%(product)s, series %(series)s: %(quantity)s parts")
        % {"product": row["product"], "series": row["series"], "quantity": row["quantity"]}
        for row in rows
    ]
    due = timezone.now() + timedelta(hours=4)
    return create_system_task(
        branch.company,
        assignee=assignee,
        title=title[:200],
        due_at=due,
        description=description,
        checklist=checklist,
    )


def recall_left(recall: RecallNotice) -> Decimal:
    """Parts of the found batches still on stock somewhere."""
    batch_ids = {row.get("batch_id") for row in recall.found or [] if row.get("batch_id")}
    if not batch_ids:
        return ZERO
    return (
        BatchStock.objects.filter(batch_id__in=batch_ids).aggregate(total=Sum("quantity"))["total"]
        or ZERO
    )


def _close(recall: RecallNotice, *, by) -> None:
    recall.status = RecallNotice.Status.CLOSED
    recall.closed_by = by
    recall.closed_at = timezone.now()
    recall.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
    _audit(Action.RECALL_CLOSED, recall.company_id, by, recall, series=recall.series)
    _bump(recall.company_id, "inventory.recalls")


@transaction.atomic
def close_recall(recall: RecallNotice, *, by: Membership) -> RecallNotice:
    """Close it once every found part was written off."""
    recall = RecallNotice.objects.select_for_update().get(pk=recall.pk)
    if recall.status == RecallNotice.Status.CLOSED:
        return recall
    left = recall_left(recall)
    if left > 0:
        raise DomainError(
            _("%(left)s parts of this series are still on stock: write them off first.")
            % {"left": left.normalize()}
        )
    _close(recall, by=by)
    return recall


# Pricing rules ---------------------------------------------------------------------------------


@transaction.atomic
def save_pricing_rule(company, *, by: Membership, rule=None, **fields) -> PricingRule:
    row = rule or PricingRule(company=company)
    _same_company(company.pk, fields.get("category"))
    for field in ("category", "cost_from", "cost_to", "markup_percent", "order", "is_active"):
        if field in fields:
            setattr(row, field, fields[field])
    if row.markup_percent is None or Decimal(row.markup_percent) < 0:
        raise DomainError(_("Give the markup in percent."))
    if row.cost_from is not None and row.cost_to is not None and row.cost_to < row.cost_from:
        raise DomainError(_("The band's upper cost is below its lower cost."))
    row.save()
    _audit(
        Action.PRICING_RULE_SAVED,
        company.pk,
        by,
        row,
        markup_percent=str(row.markup_percent),
        category=row.category.name if row.category else None,
    )
    return row


@transaction.atomic
def delete_pricing_rule(rule: PricingRule, *, by: Membership) -> None:
    _audit(Action.PRICING_RULE_DELETED, rule.company_id, by, rule)
    rule.delete()


def suggest_price(product: Product, unit_cost) -> tuple[Decimal, bool]:
    settings = conf.get_settings(product.company)
    return pricing.suggest_price(product, unit_cost, settings)


# Defektura -------------------------------------------------------------------------------------


@transaction.atomic
def add_request(
    branch,
    *,
    by: Membership | None,
    product=None,
    name: str = "",
    packs=1,
    customer_phone: str = "",
    source: str = MissingRequest.Source.COUNTER,
) -> MissingRequest:
    """Something a customer asked for that the pharmacy couldn't give (defektura)."""
    _same_company(branch.company_id, product)
    name = _text(name, 200)
    if product is None and not name:
        raise DomainError(_("Pick the item or write its name."))
    packs = Decimal(packs or 1)
    if packs <= 0:
        raise DomainError(_("Give a quantity above zero."))
    phone = "".join(ch for ch in (customer_phone or "") if ch.isdigit() or ch == "+")[:16]
    row = MissingRequest.objects.create(
        company_id=branch.company_id,
        branch=branch,
        product=product,
        name=name or (product.name if product else ""),
        packs=packs,
        customer_phone=phone,
        source=source,
        requested_by=by,
    )
    _audit(Action.REQUEST_SAVED, branch.company_id, by, row, name=row.name, status=row.status)
    _bump(branch.company_id, "inventory.defektura")
    return row


@transaction.atomic
def set_request_status(row: MissingRequest, *, by: Membership, status: str) -> MissingRequest:
    if status not in MissingRequest.Status.values:
        raise DomainError(_("Pick a status."))
    if row.status != status:
        MissingRequest.objects.filter(pk=row.pk).update(status=status, updated_at=timezone.now())
        row.status = status
        _audit(Action.REQUEST_SAVED, row.company_id, by, row, name=row.name, status=status)
        _bump(row.company_id, "inventory.defektura")
    return row


# Branch helpers --------------------------------------------------------------------------------


def pharmacy_branches(company):
    return company.branches.filter(is_active=True, kind=BranchKind.PHARMACY).order_by("order", "pk")
