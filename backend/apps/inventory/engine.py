"""The stock primitives every service uses: row locks, movements, FEFO order and values.

Every change of stock is one `move()`: it writes the `StockMovement` and keeps `BatchStock`
(what a branch holds of a batch) and `StockLevel` (what it holds of a product, less a
shortfall) in step. Callers lock the product's level first (`lock_levels`, sorted, so two
documents touching the same products never deadlock), which serializes every change of one
product at one branch: two sales of the last five parts run one after the other, and the second
sees what the first left.

Quantities are parts (the smallest piece the pharmacy sells); a batch's `unit_cost` is per
pack, so its part cost is `unit_cost / units_per_pack`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.inventory.models import BatchStock, StockBatch, StockLevel, StockMovement

ZERO = Decimal(0)
PART = Decimal("0.001")


def zone_of(company) -> ZoneInfo:
    return ZoneInfo(company.timezone)


def local_now(company, at: datetime | None = None) -> datetime:
    return timezone.localtime(at or timezone.now(), zone_of(company))


def local_today(company, at: datetime | None = None) -> date:
    return local_now(company, at).date()


def parts(value) -> Decimal:
    """A quantity of parts as a Decimal with three places."""
    return Decimal(str(value)).quantize(PART, rounding=ROUND_HALF_UP)


def part_cost(batch: StockBatch) -> Decimal:
    """What one part of the batch cost, to the tiyin."""
    return quantize(batch.unit_cost / max(batch.product.units_per_pack, 1))


def value_of(batch: StockBatch, quantity) -> Decimal:
    """`quantity` parts of the batch at its cost (exact for whole packs)."""
    return quantize(Decimal(quantity) * batch.unit_cost / max(batch.product.units_per_pack, 1))


def retail_value_of(batch: StockBatch, quantity) -> Decimal:
    return quantize(Decimal(quantity) * batch.retail_price / max(batch.product.units_per_pack, 1))


def is_expired(batch: StockBatch, today: date) -> bool:
    """The printed expiry day is the last day the medicine may be sold."""
    return batch.expires_on < today


def is_sellable(batch: StockBatch, today: date) -> bool:
    return batch.status == StockBatch.Status.SELLABLE and not is_expired(batch, today)


# Locks ------------------------------------------------------------------------------------------


def _locked_row(model, **key):
    row = model.objects.select_for_update().filter(**key).first()
    if row is not None:
        return row
    try:
        with transaction.atomic():
            model.objects.create(**key)
    except IntegrityError:
        pass  # someone made it a moment ago: wait for their lock below
    return model.objects.select_for_update().get(**key)


def lock_level(branch, product) -> StockLevel:
    """The (branch, product) level row, made when missing, under `select_for_update`."""
    level = _locked_row(StockLevel, branch=branch, product=product)
    level.branch, level.product = branch, product
    return level


def lock_levels(pairs) -> dict[tuple[int, int], StockLevel]:
    """Lock several levels in one fixed order (branch id, product id), so documents that touch
    the same products never wait on each other in a circle."""
    found: dict[tuple[int, int], StockLevel] = {}
    unique = {(branch.pk, product.pk): (branch, product) for branch, product in pairs}
    for key in sorted(unique):
        branch, product = unique[key]
        found[key] = lock_level(branch, product)
    return found


def lock_stock(branch, batch) -> BatchStock:
    stock = _locked_row(BatchStock, branch=branch, batch=batch)
    stock.branch, stock.batch = branch, batch
    return stock


# Moving -----------------------------------------------------------------------------------------


def move(
    *,
    level: StockLevel,
    batch: StockBatch | None,
    quantity,
    kind: str,
    by,
    document: tuple[str, int] | None,
    reason: str = "",
    at: datetime | None = None,
    stock: BatchStock | None = None,
) -> StockMovement:
    """Book `quantity` parts (signed) of `batch` at the level's branch. Without a batch the
    movement is a shortfall (negative) or its settlement (positive). The caller holds the
    level's lock; a batch's stock never goes below zero, nor does a shortfall."""
    quantity = parts(quantity)
    if batch is not None:
        stock = stock if stock is not None else lock_stock(level.branch, batch)
        if stock.quantity + quantity < 0:
            raise DomainError(
                _("Only %(left)s of series %(series)s is here.")
                % {"left": stock.quantity.normalize(), "series": batch.series}
            )
        if quantity:
            stock.quantity += quantity
            stock.save(update_fields=["quantity"])
    else:
        if level.shortfall - quantity < 0:
            raise ValueError("A shortfall can't be settled beyond what is owed.")
        level.shortfall -= quantity
    level.quantity += quantity
    _flag_low(level)
    level.save(update_fields=["quantity", "shortfall", "low_since", "updated_at"])
    document_type, document_id = document if document else ("", None)
    return StockMovement.objects.create(
        company_id=level.product.company_id,
        branch_id=level.branch_id,
        product_id=level.product_id,
        batch=batch,
        kind=kind,
        quantity=quantity,
        unit_cost=part_cost(batch) if batch is not None else None,
        document_type=document_type[:32],
        document_id=document_id,
        reason=(reason or "")[:16],
        created_by=by,
        at=at or timezone.now(),
    )


def _flag_low(level: StockLevel) -> None:
    if level.min_qty is None or level.quantity >= level.min_qty:
        level.low_since = None
    elif level.low_since is None:
        level.low_since = timezone.now()


# FEFO -------------------------------------------------------------------------------------------


def fefo_stocks(branch, product, today: date, *, sellable_only: bool = True):
    """The branch's stock of `product` with parts on hand, earliest expiry first, then the
    order the batches arrived in, locked."""
    rows = (
        BatchStock.objects.select_for_update(of=("self",))
        .filter(branch=branch, batch__product=product, quantity__gt=0)
        .select_related("batch", "batch__product")
        .order_by("batch__expires_on", "batch__created_at", "batch_id")
    )
    if sellable_only:
        rows = rows.filter(batch__status=StockBatch.Status.SELLABLE, batch__expires_on__gte=today)
    return list(rows)


def refresh_sale_price(product) -> None:
    """`Product.sale_price` caches the price of the batch FEFO sells next anywhere (the
    earliest-expiring sellable one with stock); an item without such a batch keeps its list
    price."""
    from apps.inventory.models import Product

    today = local_today(product.company)
    stock = (
        BatchStock.objects.filter(
            batch__product=product,
            quantity__gt=0,
            batch__status=StockBatch.Status.SELLABLE,
            batch__expires_on__gte=today,
        )
        .select_related("batch")
        .order_by("batch__expires_on", "batch__created_at", "batch_id")
        .first()
    )
    if stock is None or stock.batch.retail_price == product.sale_price:
        return
    product.sale_price = stock.batch.retail_price
    Product.objects.filter(pk=product.pk).update(sale_price=product.sale_price)
