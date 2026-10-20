"""`DailySales`: one row per branch and business day, rebuilt from shifts and receipts.

Idempotent: `rebuild_day` recomputes the row from scratch (and removes it when nothing is left),
so running it twice, or after a correction or a void, always leaves the right totals. Closed,
verified and disputed shifts count; open ones don't yet. Receipts outside any shift count on
their own; receipts inside a shift are already in its totals.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.companies.models import Branch
from apps.sales.models import CashShift, DailySales, Sale, SalePayment, ShiftPayment

ZERO = Decimal(0)
CENT = Decimal("0.01")


def avg(net: Decimal, receipts: int) -> Decimal:
    if not receipts:
        return ZERO
    return (net / receipts).quantize(CENT, rounding=ROUND_HALF_UP)


@transaction.atomic
def rebuild_day(branch_id: int, day: date) -> DailySales | None:
    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        return None
    shifts = CashShift.objects.filter(branch_id=branch_id, business_day=day).exclude(
        status=CashShift.Status.OPEN
    )
    by_method: dict[str, dict] = defaultdict(
        lambda: {"name": "", "kind": "", "sales": ZERO, "refunds": ZERO}
    )
    for row in (
        ShiftPayment.objects.filter(shift__in=shifts)
        .values("method_id", "method__name", "method__kind")
        .annotate(sales=Sum("sales"), refunds=Sum("refunds"))
    ):
        bucket = by_method[str(row["method_id"])]
        bucket["name"], bucket["kind"] = row["method__name"], row["method__kind"]
        bucket["sales"] += row["sales"] or ZERO
        bucket["refunds"] += row["refunds"] or ZERO
    shift_totals = shifts.aggregate(
        n=Count("pk"),
        receipts=Sum("receipts"),
        difference=Sum("difference"),
    )

    loose = Sale.objects.filter(
        branch_id=branch_id, business_day=day, shift__isnull=True, voided_at__isnull=True
    )
    for row in (
        SalePayment.objects.filter(sale__in=loose)
        .values("method_id", "method__name", "method__kind", "sale__kind")
        .annotate(total=Sum("amount"))
    ):
        bucket = by_method[str(row["method_id"])]
        bucket["name"], bucket["kind"] = row["method__name"], row["method__kind"]
        if row["sale__kind"] == Sale.Kind.REFUND:
            bucket["refunds"] += row["total"]
        else:
            bucket["sales"] += row["total"]
    loose_receipts = loose.filter(kind=Sale.Kind.SALE).count()

    if not shift_totals["n"] and not loose.exists():
        DailySales.objects.filter(branch_id=branch_id, day=day).delete()
        return None

    sales = sum((bucket["sales"] for bucket in by_method.values()), ZERO)
    refunds = sum((bucket["refunds"] for bucket in by_method.values()), ZERO)
    net = sales - refunds
    receipts = (shift_totals["receipts"] or 0) + loose_receipts
    methods = {
        key: {
            "name": bucket["name"],
            "kind": bucket["kind"],
            "sales": str(bucket["sales"]),
            "refunds": str(bucket["refunds"]),
            "net": str(bucket["sales"] - bucket["refunds"]),
        }
        for key, bucket in sorted(by_method.items(), key=lambda item: int(item[0]))
    }
    row, _created = DailySales.objects.update_or_create(
        branch_id=branch_id,
        day=day,
        defaults={
            "company_id": branch.company_id,
            "sales": sales,
            "refunds": refunds,
            "net": net,
            "receipts": receipts,
            "avg_check": avg(net, receipts),
            "by_method": methods,
            "shifts": shift_totals["n"] or 0,
            "cash_difference": shift_totals["difference"] or ZERO,
            "computed_at": timezone.now(),
        },
    )
    return row


def rebuild_range(company, start: date, end: date) -> int:
    """Every branch-day of `company` with shifts or receipts between the two days."""
    pairs = set(
        CashShift.objects.filter(company=company, business_day__range=(start, end))
        .exclude(status=CashShift.Status.OPEN)
        .values_list("branch_id", "business_day")
    )
    pairs |= set(
        Sale.objects.filter(
            Q(company=company) & Q(business_day__range=(start, end)) & Q(shift__isnull=True)
        ).values_list("branch_id", "business_day")
    )
    pairs |= set(
        DailySales.objects.filter(company=company, day__range=(start, end)).values_list(
            "branch_id", "day"
        )
    )
    for branch_id, day in sorted(pairs, key=lambda pair: (pair[1], pair[0])):
        rebuild_day(branch_id, day)
    return len(pairs)
