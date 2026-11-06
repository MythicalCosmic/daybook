"""The controlled-substance register (subject-quantitative accounting, §14.4 rows 22-23).

At each branch licensed for narcotics and psychotropics (`Branch.controlled_licence`), for
every product with `control_class != none`, the month is computed from the stock movements,
never typed twice:

    opening   what was on hand when the month began
    received  deliveries and transfers in
    issued    sales (net of refunds) and transfers out
    written_off
    adjusted  count adjustments and opening stock entered during the month
    closing = opening + received - issued - written_off + adjusted

"Close the month" stores a `ControlledPeriod` per product with the counted balance; a
difference is critical (report it within `controlled_report_days`) and is repeated daily until
`reported_on` is filled. The paper books stay the legal record: the printed pages are laid out
like them so the pharmacist copies or attaches them.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.inventory import conf, engine
from apps.inventory.audit_actions import InventoryAction as Action
from apps.inventory.models import ControlledPeriod, Product, RxRecord, StockMovement

ZERO = Decimal(0)
Kind = StockMovement.Kind
RECEIVED = (Kind.RECEIPT, Kind.TRANSFER_IN)
ISSUED = (Kind.SALE, Kind.REFUND, Kind.TRANSFER_OUT)
WRITTEN_OFF = (Kind.WRITEOFF,)
ADJUSTED = (Kind.COUNT_ADJUSTMENT, Kind.OPENING)


def month_start(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


def previous_month(day: date) -> date:
    return (month_start(day) - timedelta(days=1)).replace(day=1)


def _bounds(company, month: date) -> tuple[datetime, datetime]:
    zone = engine.zone_of(company)
    start = datetime.combine(month_start(month), time.min, tzinfo=zone)
    end = datetime.combine(next_month(month), time.min, tzinfo=zone)
    return start, end


def controlled_products(company, product=None):
    rows = Product.objects.for_company(company).exclude(control_class=Product.ControlClass.NONE)
    if product is not None:
        rows = rows.filter(pk=product.pk)
    return rows.order_by("control_class", "name", "pk")


def rows(branch, month: date, *, product=None) -> list[dict]:
    """The register of `month` at `branch`: one row per controlled product with anything on
    hand or moving, with the closed period's count when the month is closed."""
    if not branch.controlled_licence:
        return []
    company = branch.company
    month = month_start(month)
    start, end = _bounds(company, month)
    products = list(controlled_products(company, product))
    if not products:
        return []
    ids = [row.pk for row in products]
    base = StockMovement.objects.filter(branch=branch, product_id__in=ids)
    opening = {
        row["product_id"]: row["total"] or ZERO
        for row in base.filter(at__lt=start).values("product_id").annotate(total=Sum("quantity"))
    }
    during: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for row in (
        base.filter(at__gte=start, at__lt=end)
        .values("product_id", "kind")
        .annotate(total=Sum("quantity"))
    ):
        during[row["product_id"]][row["kind"]] += row["total"] or ZERO
    periods = {
        period.product_id: period
        for period in ControlledPeriod.objects.filter(
            branch=branch, month=month, product_id__in=ids
        )
    }
    settings = conf.get_settings(company)
    unrecorded = _issues_without_rx(branch, start, end, ids) if settings.rx_log else {}
    found = []
    for item in products:
        moved = during.get(item.pk, {})
        received = sum((moved.get(kind, ZERO) for kind in RECEIVED), ZERO)
        issued = -sum((moved.get(kind, ZERO) for kind in ISSUED), ZERO)
        written_off = -sum((moved.get(kind, ZERO) for kind in WRITTEN_OFF), ZERO)
        adjusted = sum((moved.get(kind, ZERO) for kind in ADJUSTED), ZERO)
        first = opening.get(item.pk, ZERO)
        closing = first + received - issued - written_off + adjusted
        period = periods.get(item.pk)
        if not any((first, received, issued, written_off, adjusted, closing)) and period is None:
            continue
        found.append(
            {
                "id": item.pk,
                "product_id": item.pk,
                "product": item.name,
                "inn": item.inn,
                "control_class": item.control_class,
                "units_per_pack": item.units_per_pack,
                "opening": first,
                "received": received,
                "issued": issued,
                "written_off": written_off,
                "adjusted": adjusted,
                "closing": closing,
                "unrecorded_issues": unrecorded.get(item.pk, 0),
                "period_id": period.pk if period else None,
                "counted": period.counted if period else None,
                "difference": period.difference if period else None,
                "closed_at": period.closed_at if period else None,
                "reported_on": period.reported_on if period else None,
            }
        )
    return found


def _issues_without_rx(branch, start: datetime, end: datetime, ids) -> dict[int, int]:
    """Sales of controlled products with no prescription log entry within 24 hours."""
    sales = StockMovement.objects.filter(
        branch=branch, product_id__in=ids, kind=Kind.SALE, at__gte=start, at__lt=end
    ).values("product_id", "at", "document_type", "document_id")
    records = list(
        RxRecord.objects.filter(
            branch=branch,
            product_id__in=ids,
            recorded_at__gte=start - timedelta(days=1),
            recorded_at__lt=end + timedelta(days=1),
        ).values("product_id", "recorded_at", "document_type", "document_id")
    )
    missing: dict[int, int] = defaultdict(int)
    for sale in sales:
        matched = any(
            record["product_id"] == sale["product_id"]
            and abs(record["recorded_at"] - sale["at"]) <= timedelta(hours=24)
            for record in records
        )
        if not matched:
            missing[sale["product_id"]] += 1
    return dict(missing)


@transaction.atomic
def close_month(
    branch, month: date, *, by, counted: dict[int, Decimal] | None = None, note: str = ""
) -> list[ControlledPeriod]:
    """Store the month with the counted balance of each product (the register's closing when
    not given). A month can be closed again until a difference was reported."""
    from apps.inventory import notify
    from apps.inventory.services import _audit, _bump

    if not branch.controlled_licence:
        raise DomainError(
            _("%(branch)s isn't licensed for controlled substances.") % {"branch": branch.name}
        )
    company = branch.company
    month = month_start(month)
    today = engine.local_today(company)
    if month >= month_start(today):
        raise DomainError(_("A month is closed once it is over."))
    counted = {int(key): Decimal(str(value)) for key, value in (counted or {}).items()}
    lines = rows(branch, month)
    known = {row["product_id"] for row in lines}
    if set(counted) - known:
        raise DomainError(_("That item isn't in this month's register."))
    now = timezone.now()
    periods = []
    mismatched = []
    for row in lines:
        period = (
            ControlledPeriod.objects.select_for_update()
            .filter(branch=branch, product_id=row["product_id"], month=month)
            .first()
        )
        if period is not None and period.reported_on is not None:
            raise DomainError(_("This month's difference was already reported: it can't change."))
        value = counted.get(row["product_id"], row["closing"])
        if value < 0:
            raise DomainError(_("A count can't be below zero."))
        fields = {
            "opening": row["opening"],
            "received": row["received"],
            "issued": row["issued"],
            "written_off": row["written_off"],
            "closing": row["closing"],
            "counted": value,
            "difference": value - row["closing"],
            "note": (note or "").strip()[:2000],
            "closed_by": by,
            "closed_at": now,
        }
        if period is None:
            period = ControlledPeriod.objects.create(
                company=company, branch=branch, product_id=row["product_id"], month=month, **fields
            )
        else:
            for field, field_value in fields.items():
                setattr(period, field, field_value)
            period.save()
        periods.append(period)
        if period.difference:
            mismatched.append(period)
    _audit(
        Action.MONTH_CLOSED,
        company.pk,
        by,
        branch,
        month=month.isoformat(),
        products=len(periods),
        differences=len(mismatched),
    )
    if mismatched:
        days = conf.get_settings(company).controlled_report_days

        def send():
            for period in mismatched:
                notify.controlled_mismatch(period, today, days)

        transaction.on_commit(send)
    _bump(company.pk, "inventory.controlled")
    return periods


@transaction.atomic
def mark_reported(period: ControlledPeriod, *, by, reported_on: date) -> ControlledPeriod:
    from apps.inventory.services import _audit, _bump

    period = ControlledPeriod.objects.select_for_update().get(pk=period.pk)
    if not period.difference:
        raise DomainError(_("This month has no difference to report."))
    period.reported_on = reported_on
    period.save(update_fields=["reported_on", "updated_at"])
    _audit(
        Action.DIFFERENCE_REPORTED,
        period.company_id,
        by,
        period,
        product=period.product.name,
        reported_on=reported_on.isoformat(),
    )
    _bump(period.company_id, "inventory.controlled")
    return period


def unreported(company) -> list[ControlledPeriod]:
    return list(
        ControlledPeriod.objects.for_company(company)
        .filter(reported_on__isnull=True, closed_at__isnull=False)
        .exclude(difference=0)
        .select_related("branch", "product", "company")
    )


def is_closed(branch, month: date) -> bool:
    """Whether the month was closed at the branch (or had nothing to close)."""
    month = month_start(month)
    if ControlledPeriod.objects.filter(
        branch=branch, month=month, closed_at__isnull=False
    ).exists():
        return True
    return not rows(branch, month)
