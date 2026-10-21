"""Derived cash figures (docs/PLAN-OWNER.md §3.8): never stored as balances, always computed.

    expected cash = opening float + cash sales - cash refunds + Σ incoming movements - Σ outgoing
    till now      = an open shift's running expected, else the till's ledger balance minus the
                    handovers that left it but aren't booked yet (pending or declined)
    cash in branch = Σ its tills now + its safe's balance
    in transit     = handovers nobody confirmed yet

A declined handover still counts as cash that left the till (the cashier says it did) until a
manager voids it, which brings it back into the till's expected cash.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum

from apps.finance.models import MoneyAccount
from apps.sales.models import CashMovement, CashShift, PaymentMethod, Register, Sale, SalePayment

ZERO = Decimal(0)


def payments_of(shift: CashShift) -> list:
    """A shift's payment lines with their methods: from the prefetch when the caller made one
    (lists), else in one query."""
    if "payments" in getattr(shift, "_prefetched_objects_cache", {}):
        return list(shift.payments.all())
    return list(shift.payments.select_related("method"))


def movement_total(shift: CashShift) -> Decimal:
    """Σ of the shift's live movements, + for cash in, - for cash out."""
    total = ZERO
    for kind, amount in (
        CashMovement.objects.filter(shift=shift, voided_at__isnull=True)
        .values_list("kind", "amount")
        .iterator()
    ):
        total += amount if kind in CashMovement.INCOMING else -amount
    return total


def movement_totals_by_kind(shift: CashShift) -> dict[str, Decimal]:
    rows = (
        CashMovement.objects.filter(shift=shift, voided_at__isnull=True)
        .values("kind")
        .annotate(total=Sum("amount"))
    )
    return {row["kind"]: row["total"] for row in rows}


def cash_net_of_lines(lines) -> Decimal:
    """Cash sales minus cash refunds of payment lines (objects with method, sales, refunds)."""
    return sum(
        (
            line.sales - line.refunds
            for line in lines
            if line.method.kind == PaymentMethod.Kind.CASH
        ),
        ZERO,
    )


def receipts_by_method(shift: CashShift) -> dict[int, dict]:
    """Recorded single receipts of a shift per method: {method id: {sales, refunds, receipts}}."""
    found: dict[int, dict] = defaultdict(lambda: {"sales": ZERO, "refunds": ZERO, "receipts": 0})
    rows = (
        SalePayment.objects.filter(sale__shift=shift, sale__voided_at__isnull=True)
        .values("method_id", "sale__kind")
        .annotate(total=Sum("amount"))
    )
    for row in rows:
        bucket = found[row["method_id"]]
        if row["sale__kind"] == Sale.Kind.REFUND:
            bucket["refunds"] += row["total"]
        else:
            bucket["sales"] += row["total"]
    counts = (
        Sale.objects.filter(shift=shift, voided_at__isnull=True, kind=Sale.Kind.SALE)
        .values("payments__method_id")
        .annotate(n=Count("id", distinct=True))
    )
    for row in counts:
        if row["payments__method_id"] is not None:
            found[row["payments__method_id"]]["receipts"] += row["n"] or 0
    return dict(found)


def receipts_cash_net(shift: CashShift) -> Decimal:
    rows = (
        SalePayment.objects.filter(
            sale__shift=shift, sale__voided_at__isnull=True, method__kind=PaymentMethod.Kind.CASH
        )
        .values("sale__kind")
        .annotate(total=Sum("amount"))
    )
    total = ZERO
    for row in rows:
        total += -row["total"] if row["sale__kind"] == Sale.Kind.REFUND else row["total"]
    return total


def expected_cash(shift: CashShift) -> Decimal:
    """What should be in the till: at close from the typed payments, while open from what is
    known so far (recorded receipts in receipts mode; shift totals arrive only at close)."""
    if shift.status == CashShift.Status.OPEN:
        cash = receipts_cash_net(shift)
    else:
        cash = cash_net_of_lines(payments_of(shift))
    return shift.opening_float + cash + movement_total(shift)


def unbooked_handovers(register: Register) -> Decimal:
    """Handovers that left the till but aren't in the ledger yet (pending or declined)."""
    return (
        CashMovement.objects.filter(
            register=register,
            kind=CashMovement.Kind.HANDOVER,
            voided_at__isnull=True,
            transfer__isnull=True,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )


def till_physical(register: Register) -> Decimal:
    """The cash a till without an open shift should hold."""
    balance = (
        MoneyAccount.objects.filter(pk=register.cash_account_id)
        .values_list("balance", flat=True)
        .first()
        or ZERO
    )
    return balance - unbooked_handovers(register)


def till_now(register: Register, open_shift: CashShift | None = None) -> Decimal:
    """What a till holds now. An open till never reads below zero: in shift-totals mode its
    sales arrive only at close, so float minus payouts and handovers is a floor, not a count."""
    if open_shift is not None:
        return max(expected_cash(open_shift), ZERO)
    return till_physical(register)


def tills_now(registers, open_shifts: dict[int, CashShift]) -> dict[int, Decimal]:
    """`till_now` for many tills at once, in four queries whatever their number (lists, branch
    cards and "where is my cash" call this instead of `till_now` per till)."""
    registers = list(registers)
    if not registers:
        return {}
    shifts = [open_shifts[r.pk] for r in registers if r.pk in open_shifts]
    shift_ids = [shift.pk for shift in shifts]
    idle = [r for r in registers if r.pk not in open_shifts]

    balances = dict(
        MoneyAccount.objects.filter(pk__in=[r.cash_account_id for r in idle]).values_list(
            "pk", "balance"
        )
    )
    unbooked = dict(
        CashMovement.objects.filter(
            register__in=idle,
            kind=CashMovement.Kind.HANDOVER,
            voided_at__isnull=True,
            transfer__isnull=True,
        )
        .values("register_id")
        .annotate(total=Sum("amount"))
        .values_list("register_id", "total")
    )
    moved: dict[int, Decimal] = defaultdict(lambda: ZERO)
    received: dict[int, Decimal] = defaultdict(lambda: ZERO)
    if shift_ids:
        for shift_id, kind, total in (
            CashMovement.objects.filter(shift_id__in=shift_ids, voided_at__isnull=True)
            .values("shift_id", "kind")
            .annotate(total=Sum("amount"))
            .values_list("shift_id", "kind", "total")
        ):
            moved[shift_id] += total if kind in CashMovement.INCOMING else -total
        for shift_id, kind, total in (
            SalePayment.objects.filter(
                sale__shift_id__in=shift_ids,
                sale__voided_at__isnull=True,
                method__kind=PaymentMethod.Kind.CASH,
            )
            .values("sale__shift_id", "sale__kind")
            .annotate(total=Sum("amount"))
            .values_list("sale__shift_id", "sale__kind", "total")
        ):
            received[shift_id] += -total if kind == Sale.Kind.REFUND else total

    found: dict[int, Decimal] = {}
    for register in registers:
        shift = open_shifts.get(register.pk)
        if shift is not None:
            expected = shift.opening_float + received[shift.pk] + moved[shift.pk]
            found[register.pk] = max(expected, ZERO)
        else:
            balance = balances.get(register.cash_account_id) or ZERO
            found[register.pk] = balance - (unbooked.get(register.pk) or ZERO)
    return found


def in_transit_filter() -> Q:
    return Q(
        kind=CashMovement.Kind.HANDOVER,
        voided_at__isnull=True,
        confirmed_at__isnull=True,
        declined_at__isnull=True,
    )
