"""The prescription log (§14.4 rows 10-12, §14.6.2): one `RxRecord` per dispensed (or refused,
`status="invalid"`) prescription of a prescription-only medicine. Never a patient's name, ID or
PINFL. `keep_until` follows `StockSettings.rx_keep_months` by the prescription's kind."""

from __future__ import annotations

import calendar
from datetime import date

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.inventory import conf, engine
from apps.inventory.audit_actions import InventoryAction as Action
from apps.inventory.models import RxRecord, StockBatch

FIELDS = (
    "batch",
    "prescription_number",
    "prescribed_on",
    "prescriber",
    "facility",
    "rx_kind",
    "status",
    "invalid_reason",
    "e_prescription_id",
    "photo",
    "recorded_at",
)
LIMITS = {
    "prescription_number": 40,
    "prescriber": 120,
    "facility": 120,
    "invalid_reason": 200,
    "e_prescription_id": 64,
}


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def record(*, by, branch, product, quantity, document=None, **fields) -> RxRecord | None:
    from apps.inventory.services import _audit, _bump

    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError(f"Unknown prescription fields: {sorted(unknown)}")
    if product.company_id != branch.company_id:
        raise DomainError(_("That belongs to another company."))
    settings = conf.get_settings(branch.company)
    if not settings.rx_log or not product.rx_required:
        return None
    quantity = engine.parts(quantity or 1)
    if quantity <= 0:
        raise DomainError(_("Give a quantity above zero."))
    for field, limit in LIMITS.items():
        if field in fields:
            fields[field] = (fields[field] or "").strip()[:limit]
    batch = fields.get("batch")
    if batch is not None and (not isinstance(batch, StockBatch) or batch.product_id != product.pk):
        raise DomainError(_("That series is of another item."))
    rx_kind = fields.get("rx_kind") or RxRecord.RxKind.REGULAR
    if rx_kind not in RxRecord.RxKind.values:
        raise DomainError(_("Pick the kind of prescription."))
    status = fields.get("status") or RxRecord.Status.DISPENSED
    if status not in RxRecord.Status.values:
        raise DomainError(_("Pick whether it was dispensed or refused."))
    if status == RxRecord.Status.INVALID and not fields.get("invalid_reason"):
        raise DomainError(_("Say what was wrong with the prescription."))
    recorded_at = fields.pop("recorded_at", None) or timezone.now()
    day = engine.local_today(branch.company, recorded_at)
    keep_until = add_months(day, settings.keep_months(rx_kind))
    document_type, document_id = document if document else ("", None)
    found = None
    if document_type and document_id is not None:
        found = RxRecord.objects.filter(
            company_id=branch.company_id, document_type=document_type, document_id=document_id
        ).first()
    values = {
        **fields,
        "rx_kind": rx_kind,
        "status": status,
        "quantity": quantity,
        "keep_until": keep_until,
    }
    photo = values.pop("photo", None)
    if found is None:
        found = RxRecord(
            company_id=branch.company_id,
            branch=branch,
            product=product,
            document_type=document_type[:32],
            document_id=document_id,
            recorded_by=by,
            recorded_at=recorded_at,
            **values,
        )
        action = Action.RX_RECORDED
    else:
        for field, value in values.items():
            setattr(found, field, value)
        action = Action.RX_CHANGED
    if photo is not None:
        found.photo.save(photo.name, photo, save=False)
    found.save()
    _audit(
        action,
        branch.company_id,
        by,
        found,
        product=product.name,
        rx_kind=rx_kind,
        status=status,
    )
    _bump(branch.company_id)
    return found


def expired_validity(record: RxRecord, settings) -> bool:
    """A narcotic or psychotropic prescription dispensed after it stopped being valid."""
    if record.prescribed_on is None:
        return False
    day = record.recorded_at.date()
    if record.rx_kind == RxRecord.RxKind.NARCOTIC:
        return (day - record.prescribed_on).days > settings.narcotic_rx_valid_days
    if record.rx_kind == RxRecord.RxKind.PSYCHOTROPIC:
        return day > add_months(record.prescribed_on, settings.psychotropic_rx_valid_months)
    return False


def needs_e_prescription(record: RxRecord) -> bool:
    """An e-prescription group medicine dispensed at an e-prescription branch without one."""
    return (
        record.product.e_rx_group
        and record.branch.e_prescription_area
        and not record.e_prescription_id
        and record.status == RxRecord.Status.DISPENSED
    )


def past_keeping(company, today: date):
    return RxRecord.objects.for_company(company).filter(keep_until__lt=today)


def clear_past_keeping(company, today: date) -> int:
    """After the keeping time: the photo goes and the prescriber is blanked (the counts stay for
    analytics)."""
    cleared = 0
    for row in past_keeping(company, today).exclude(photo="", prescriber=""):
        if row.photo:
            row.photo.delete(save=False)
        row.prescriber = ""
        row.save(update_fields=["photo", "prescriber", "updated_at"])
        cleared += 1
    return cleared
