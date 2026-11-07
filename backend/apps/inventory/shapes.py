"""What the stock endpoints answer, as plain dicts (the serializers in `serializers.py`
describe them). `cost=False` leaves every cost field out (the field rule of §5: cost prices,
batch costs and values at cost need finance.view)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.files import signed_url
from apps.inventory import engine, pricing
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    MissingRequest,
    Product,
    RecallNotice,
    RxRecord,
    StockCount,
    StockCountLine,
    StockLevel,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    WriteOff,
    WriteOffLine,
)
from apps.members.queries import branch_ref, person_ref

ZERO = Decimal(0)


def ref(item) -> dict | None:
    if item is None:
        return None
    return {"id": item.pk, "name": str(getattr(item, "name", None) or item)}


def _file_url(field, *, user, company_id: int, check: str) -> str | None:
    if not field:
        return None
    return signed_url(field, user=user, company_id=company_id, check=check)


def product_out(
    product: Product,
    *,
    cost: bool,
    settings,
    quantity: Decimal | None = None,
    nearest: date | None = None,
) -> dict:
    data = {
        "id": product.pk,
        "name": product.name,
        "trade_name": product.trade_name,
        "inn": product.inn,
        "kind": product.kind,
        "dosage_form": product.dosage_form,
        "strength": product.strength,
        "units_per_pack": product.units_per_pack,
        "part_label": product.part_label,
        "manufacturer": ref(product.manufacturer) if product.manufacturer_id else None,
        "category": ref(product.category) if product.category_id else None,
        "rx_required": product.rx_required,
        "e_rx_group": product.e_rx_group,
        "control_class": product.control_class,
        "restricted_channel": product.restricted_channel,
        "storage": product.storage,
        "light_sensitive": product.light_sensitive,
        "barcode": product.barcode,
        "sku": product.sku,
        "mxik_code": product.mxik_code,
        "package_code": product.package_code,
        "registration_number": product.registration_number,
        "registration_until": product.registration_until,
        "marking_required": product.marking_required,
        "vat_percent": str(product.vat_percent) if product.vat_percent is not None else None,
        "socially_significant": product.socially_significant,
        "mandatory_list": product.mandatory_list,
        "reference_price": product.reference_price,
        "reference_price_on": product.reference_price_on,
        "sale_price": product.sale_price,
        "part_price": product.part_price,
        "effective_part_price": pricing.part_price(product, settings=settings),
        "track_stock": product.track_stock,
        "is_active": product.is_active,
        "quantity": quantity if product.track_stock else None,
        "nearest_expiry": nearest,
    }
    if cost:
        data["cost_price"] = product.cost_price
    return data


def level_out(level: StockLevel, *, cost: bool, sellable: Decimal, nearest, value) -> dict:
    product = level.product
    data = {
        "id": level.pk,
        "branch": branch_ref(level.branch),
        "product": ref(product),
        "inn": product.inn,
        "rx_required": product.rx_required,
        "control_class": product.control_class,
        "storage": product.storage,
        "mandatory_list": product.mandatory_list,
        "units_per_pack": product.units_per_pack,
        "part_label": product.part_label,
        "quantity": level.quantity,
        "sellable": sellable,
        "shortfall": level.shortfall,
        "min_qty": level.min_qty,
        "max_qty": level.max_qty,
        "low": level.min_qty is not None and level.quantity < level.min_qty,
        "nearest_expiry": nearest,
        "sale_price": product.sale_price,
    }
    if cost:
        data["value"] = value
    return data


def batch_out(stock, *, cost: bool, today: date, settings) -> dict:
    batch = stock.batch
    product = batch.product
    data = {
        "id": stock.pk,
        "batch_id": batch.pk,
        "branch": branch_ref(stock.branch),
        "product": ref(product),
        "series": batch.series,
        "expires_on": batch.expires_on,
        "made_on": batch.made_on,
        "days_left": (batch.expires_on - today).days,
        "expired": engine.is_expired(batch, today),
        "status": batch.status,
        "supplier": ref(batch.supplier) if batch.supplier_id else None,
        "quantity": stock.quantity,
        "retail_price": batch.retail_price,
        "part_price": pricing.part_price(product, batch, settings=settings),
        "price_cap": pricing.price_ceiling(product, batch.unit_cost, settings),
        "retail_value": engine.retail_value_of(batch, stock.quantity),
        "receipt_id": batch.receipt_line.receipt_id if batch.receipt_line_id else None,
    }
    if cost:
        data["unit_cost"] = batch.unit_cost
        data["value"] = engine.value_of(batch, stock.quantity)
    return data


def movement_out(movement: StockMovement, *, cost: bool) -> dict:
    data = {
        "id": movement.pk,
        "at": movement.at,
        "branch": branch_ref(movement.branch),
        "product": ref(movement.product),
        "series": movement.batch.series if movement.batch_id else None,
        "kind": movement.kind,
        "quantity": movement.quantity,
        "document_type": movement.document_type,
        "document_id": movement.document_id,
        "reason": movement.reason,
        "by": person_ref(movement.created_by),
    }
    if cost:
        data["unit_cost"] = movement.unit_cost
    return data


def receipt_out(receipt: GoodsReceipt, *, cost: bool, user, lines=None) -> dict:
    if lines is None:
        lines = list(receipt.lines.all())
    warnings = sorted({code for line in lines for code in line.warnings})
    data = {
        "id": receipt.pk,
        "number": receipt.number,
        "status": receipt.status,
        "branch": branch_ref(receipt.branch),
        "supplier": ref(receipt.supplier),
        "supplier_invoice_number": receipt.supplier_invoice_number,
        "supplier_invoice_date": receipt.supplier_invoice_date,
        "currency": receipt.currency,
        "due_on": receipt.due_on,
        "note": receipt.note,
        "e_invoice_ref": receipt.e_invoice_ref,
        "lines_count": len(lines),
        "warnings": warnings,
        "received_by": person_ref(receipt.received_by),
        "posted_by": person_ref(receipt.posted_by),
        "submitted_at": receipt.submitted_at,
        "posted_at": receipt.posted_at,
        "created_at": receipt.created_at,
        "file_url": _file_url(
            receipt.file,
            user=user,
            company_id=receipt.company_id,
            check=f"inventory.receipt_file:{receipt.pk}",
        ),
        "void_reason": receipt.void_reason,
    }
    if cost:
        debt = receipt.debt if receipt.debt_id else None
        data.update(
            total=receipt.total,
            vat_total=receipt.vat_total,
            debt_id=receipt.debt_id,
            debt_status=debt.status if debt is not None else None,
            debt_paid=debt.paid if debt is not None else None,
        )
    return data


def receipt_line_out(line: GoodsReceiptLine, *, cost: bool, settings) -> dict:
    product = line.product
    data = {
        "id": line.pk,
        "product": ref(product),
        "units_per_pack": product.units_per_pack,
        "rx_required": product.rx_required,
        "control_class": product.control_class,
        "series": line.series,
        "expires_on": line.expires_on,
        "made_on": line.made_on,
        "packs": line.packs,
        "quantity": line.quantity,
        "vat_percent": str(line.vat_percent) if line.vat_percent is not None else None,
        "retail_price": line.retail_price,
        "price_cap": pricing.price_ceiling(product, line.unit_cost, settings),
        "supplier_rx": line.supplier_rx,
        "warnings": list(line.warnings),
        "batch_id": getattr(getattr(line, "batch", None), "pk", None),
    }
    if cost:
        data["unit_cost"] = line.unit_cost
        data["total"] = line.total
    return data


def transfer_out(transfer: StockTransfer, *, lines_count: int | None = None) -> dict:
    return {
        "id": transfer.pk,
        "number": transfer.number,
        "status": transfer.status,
        "from_branch": branch_ref(transfer.from_branch),
        "to_branch": branch_ref(transfer.to_branch),
        "note": transfer.note,
        "lines_count": transfer.lines.count() if lines_count is None else lines_count,
        "created_at": transfer.created_at,
        "sent_at": transfer.sent_at,
        "sent_by": person_ref(transfer.sent_by),
        "received_at": transfer.received_at,
        "received_by": person_ref(transfer.received_by),
        "resolution": transfer.resolution,
        "resolved_at": transfer.resolved_at,
        "void_reason": transfer.void_reason,
    }


def transfer_line_out(line: StockTransferLine) -> dict:
    batch = line.batch
    return {
        "id": line.pk,
        "product": ref(line.product),
        "units_per_pack": line.product.units_per_pack,
        "batch_id": line.batch_id,
        "series": batch.series if batch else None,
        "expires_on": batch.expires_on if batch else None,
        "quantity_sent": line.quantity_sent,
        "quantity_received": line.quantity_received,
    }


def writeoff_out(writeoff: WriteOff, *, cost: bool, user, lines_count: int | None = None) -> dict:
    data = {
        "id": writeoff.pk,
        "number": writeoff.number,
        "status": writeoff.status,
        "reason": writeoff.reason,
        "branch": branch_ref(writeoff.branch),
        "note": writeoff.note,
        "lines_count": writeoff.lines.count() if lines_count is None else lines_count,
        "needs_destruction": writeoff.needs_destruction,
        "proposed_by": person_ref(writeoff.proposed_by),
        "approved_by": person_ref(writeoff.approved_by),
        "approved_at": writeoff.approved_at,
        "created_at": writeoff.created_at,
        "destroy_by": writeoff.destroy_by,
        "responsible": writeoff.responsible,
        "order_number": writeoff.order_number,
        "commission": writeoff.commission or [],
        "method": writeoff.method,
        "place": writeoff.place,
        "destroyed_at": writeoff.destroyed_at,
        "sent_to": writeoff.sent_to or [],
        "act_url": _file_url(
            writeoff.act_pdf,
            user=user,
            company_id=writeoff.company_id,
            check=f"inventory.writeoff_act:{writeoff.pk}",
        ),
        "recall_id": writeoff.recall_id,
        "transfer_id": writeoff.transfer_id,
        "void_reason": writeoff.void_reason,
    }
    if cost:
        data["value"] = writeoff.value
    return data


def writeoff_line_out(line: WriteOffLine, *, cost: bool) -> dict:
    batch = line.batch
    data = {
        "id": line.pk,
        "batch_id": batch.pk,
        "product": ref(batch.product),
        "units_per_pack": batch.product.units_per_pack,
        "series": batch.series,
        "expires_on": batch.expires_on,
        "quantity": line.quantity,
    }
    if cost:
        data["unit_cost"] = line.unit_cost
        data["value"] = line.value
    return data


def writeoff_file_out(row, *, user, company_id: int) -> dict:
    return {
        "id": row.pk,
        "kind": row.kind,
        "url": signed_url(
            row.file, user=user, company_id=company_id, check=f"inventory.writeoff_file:{row.pk}"
        ),
        "at": row.at,
    }


def count_out(count: StockCount, *, cost: bool, counted: int | None = None) -> dict:
    lines_count = getattr(count, "line_count", None)
    data = {
        "id": count.pk,
        "kind": count.kind,
        "status": count.status,
        "branch": branch_ref(count.branch),
        "category": ref(count.category) if count.category_id else None,
        "lines_count": count.lines.count() if lines_count is None else lines_count,
        "counted_count": count.lines.filter(counted__isnull=False).count()
        if counted is None
        else counted,
        "started_by": person_ref(count.started_by),
        "created_at": count.created_at,
        "submitted_at": count.submitted_at,
        "applied_at": count.applied_at,
    }
    if cost:
        data["value_difference"] = count.value_difference
    return data


def count_line_out(line: StockCountLine, *, blind: bool, cost: bool) -> dict:
    """A line as the counter sees it (`blind`: never the expected quantity), or once counted
    as the manager reviews it."""
    batch = line.batch
    data = {
        "id": line.pk,
        "product": ref(line.product),
        "units_per_pack": line.product.units_per_pack,
        "part_label": line.product.part_label,
        "batch_id": line.batch_id,
        "series": batch.series if batch else line.series,
        "expires_on": batch.expires_on if batch else line.expires_on,
        "counted": line.counted,
    }
    if not blind:
        data["expected"] = line.expected
        data["difference"] = (
            line.difference
            if line.difference is not None
            else (line.counted - line.expected if line.counted is not None else None)
        )
        if cost and batch is not None and data["difference"] is not None:
            data["value_difference"] = engine.value_of(batch, data["difference"])
    return data


def recall_out(recall: RecallNotice, *, branch_ids, user, left_by_batch: dict) -> dict:
    rows = [
        {**row, "left": left_by_batch.get((row.get("branch_id"), row.get("batch_id")), ZERO)}
        for row in recall.found or []
        if branch_ids is None or row.get("branch_id") in branch_ids
    ]
    return {
        "id": recall.pk,
        "product": ref(recall.product) if recall.product_id else None,
        "inn_or_name": recall.inn_or_name,
        "series": recall.series,
        "reason": recall.reason,
        "source": recall.source,
        "received_on": recall.received_on,
        "status": recall.status,
        "found": rows,
        "left": sum((row["left"] for row in rows), ZERO),
        "file_url": _file_url(
            recall.file,
            user=user,
            company_id=recall.company_id,
            check=f"inventory.recall_file:{recall.pk}",
        ),
        "closed_at": recall.closed_at,
        "created_at": recall.created_at,
    }


def rx_out(record: RxRecord, *, settings) -> dict:
    from apps.inventory import prescriptions

    flags = []
    if prescriptions.needs_e_prescription(record):
        flags.append("no_e_prescription")
    if prescriptions.expired_validity(record, settings):
        flags.append("past_validity")
    return {
        "id": record.pk,
        "branch": branch_ref(record.branch),
        "product": ref(record.product),
        "series": record.batch.series if record.batch_id else None,
        "quantity": record.quantity,
        "prescription_number": record.prescription_number,
        "prescribed_on": record.prescribed_on,
        "prescriber": record.prescriber,
        "facility": record.facility,
        "rx_kind": record.rx_kind,
        "status": record.status,
        "invalid_reason": record.invalid_reason,
        "facility_notified_at": record.facility_notified_at,
        "e_prescription_id": record.e_prescription_id,
        "keep_until": record.keep_until,
        "recorded_at": record.recorded_at,
        "recorded_by": person_ref(record.recorded_by),
        "flags": flags,
    }


def request_out(row: MissingRequest) -> dict:
    return {
        "id": row.pk,
        "branch_ref": branch_ref(row.branch),
        "product_ref": ref(row.product) if row.product_id else None,
        "name": row.name,
        "packs": row.packs,
        "source": row.source,
        "status": row.status,
        "customer_phone": row.customer_phone,
        "requested_at": row.requested_at,
        "requested_by": person_ref(row.requested_by),
    }
