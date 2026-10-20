"""Ledger bookings of sales and cash, through the W0 finance contract (docs/PLAN-OWNER.md §3.8).

Finance never imports sales: everything here calls `apps.finance.services` with an idempotency
`Source`. Shift bookings use `Source("sales.cashshift", shift.id, key)` and
`occurred_on = shift.business_day`:

- per payment method that isn't credit (nasiya is booked per credit sale by package J):
  ``m<method id>`` income (category `sales`) on the method's account, or the till's cash account
  for cash; ``r<method id>`` refunds as contra income (category `refunds`); ``f<method id>`` the
  provider's fee as a `bank_fees` expense on the method's account;
- ``diff``: a shortage as a `cash_shortage` expense, a surplus as `cash_surplus` income;
- ``float``: at opening, the difference between the counted float and what the till should have
  held (or, for a till's very first shift, its opening balance).

`rebook_shift` compares what a shift should have booked with what is live in the ledger, voids
what no longer matches (finance frees the source on void) and books the rest, so a correction
leaves exactly the rows of the corrected shift. Cash movements book once each under
`Source("sales.cashmovement", movement.id)`: a payout as an expense, every other kind as a
transfer (a handover only once its receiver confirms).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _

from apps.core.money import quantize
from apps.finance import services as finance
from apps.finance.models import LIVE_STATUSES, MoneyAccount, Transaction
from apps.finance.sources import Source
from apps.members.models import Membership
from apps.sales.models import CashMovement, CashShift, PaymentMethod, Register, Sale

SHIFT = "sales.cashshift"
MOVEMENT = "sales.cashmovement"
SALE = "sales.sale"
ZERO = Decimal(0)


@dataclass(frozen=True)
class Booking:
    """One ledger row a shift should have."""

    key: str
    kind: str  # income | expense | opening
    amount: Decimal  # positive, except opening (signed)
    account: MoneyAccount
    category: str | None
    is_contra: bool = False
    membership: Membership | None = None
    description: str = ""


# Accounts ------------------------------------------------------------------------------


def create_till_account(register_name: str, branch, *, by: Membership | None) -> MoneyAccount:
    """The cash account of a new till. A till's ledger balance may dip below zero during a
    shift, because its sales are booked only at close while payouts and handovers book at once
    (W0-F review), so the account allows an overdraft."""
    company = branch.company
    base = f"{branch.name}, {register_name}"
    account = finance.create_account(
        company,
        by=by,
        kind=MoneyAccount.Kind.CASH,
        name=_free_account_name(company, base),
        currency=company.base_currency,
        branch=branch,
    )
    allow_overdraft(account)
    return account


def allow_overdraft(account: MoneyAccount) -> None:
    """Let a till's cash account go below zero mid-shift.

    The finance contract has no switch for this yet; until package D adds one (hand-off), sales
    sets the flag on the accounts it made for its own tills, and only there.
    """
    if not account.allow_negative:
        MoneyAccount.objects.filter(pk=account.pk).update(allow_negative=True)
        account.allow_negative = True


def payment_account(register: Register, method: PaymentMethod) -> MoneyAccount:
    """Where a method's money lands: the method's own account when it has one; else cash lands
    in the till and any other money (never in a till) in the branch's clearing account."""
    if method.account_id is not None:
        return method.account
    if method.is_cash:
        return register.cash_account
    return finance.account_for_branch(register.branch, kind=MoneyAccount.Kind.CLEARING)


def _free_account_name(company, name: str) -> str:
    taken = set(
        MoneyAccount.objects.filter(company=company, name__startswith=name[:90]).values_list(
            "name", flat=True
        )
    )
    if name not in taken:
        return name[:100]
    number = 2
    while f"{name} ({number})" in taken:
        number += 1
    return f"{name[:90]} ({number})"


# Shifts --------------------------------------------------------------------------------


def shift_bookings(shift: CashShift) -> list[Booking]:
    """Every row a closed shift should have in the ledger (the float row aside)."""
    bookings: list[Booking] = []
    register = shift.register
    for payment in shift.payments.select_related("method__account"):
        method = payment.method
        if method.is_credit:
            continue
        account = payment_account(register, method)
        label = f"{shift.code} · {method.name}"
        if payment.sales:
            bookings.append(
                Booking(
                    f"m{method.pk}", "income", payment.sales, account, "sales", description=label
                )
            )
        if payment.refunds:
            bookings.append(
                Booking(
                    f"r{method.pk}",
                    "income",
                    payment.refunds,
                    account,
                    "refunds",
                    is_contra=True,
                    description=label,
                )
            )
        fee = fee_of(method, payment.sales - payment.refunds)
        if fee:
            bookings.append(
                Booking(f"f{method.pk}", "expense", fee, account, "bank_fees", description=label)
            )
    difference = shift.difference
    if difference:
        bookings.append(_difference_booking("diff", shift, difference))
    return bookings


def fee_of(method: PaymentMethod, net: Decimal) -> Decimal:
    if not method.fee_percent or net <= 0:
        return ZERO
    return (net * method.fee_percent / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _difference_booking(key: str, shift: CashShift, difference: Decimal) -> Booking:
    shortage = difference < 0
    if key == "float":
        description = _("%(shift)s: float difference at opening") % {"shift": shift.code}
    else:
        description = _("%(shift)s: cash difference") % {"shift": shift.code}
    return Booking(
        key,
        "expense" if shortage else "income",
        abs(difference),
        shift.register.cash_account,
        "cash_shortage" if shortage else "cash_surplus",
        membership=shift.cashier if key == "diff" else None,
        description=description,
    )


def float_booking(shift: CashShift, *, first: bool) -> Booking | None:
    """What opening the shift books: a till's first float is its opening balance; later, a float
    that differs from what the till should hold books the difference."""
    if first:
        if shift.opening_float <= 0:
            return None
        return Booking(
            "float",
            "opening",
            shift.opening_float,
            shift.register.cash_account,
            None,
            description=_("%(shift)s: first float of %(till)s")
            % {"shift": shift.code, "till": shift.register.name},
        )
    if shift.expected_float is None:
        return None
    difference = shift.opening_float - shift.expected_float
    if not difference:
        return None
    return _difference_booking("float", shift, difference)


def book_float(shift: CashShift, *, by: Membership | None, first: bool) -> None:
    booking = float_booking(shift, first=first)
    if booking is not None:
        _book(shift, booking, by=by)


def rebook_shift(shift: CashShift, *, by: Membership | None, reason: str = "") -> None:
    """Make the ledger hold exactly `shift_bookings(shift)`: void live rows that no longer match
    (a correction) and book the missing ones. Voids need a person (`by`)."""
    wanted = {booking.key: booking for booking in shift_bookings(shift)}
    live = {
        row.source_key: row
        for row in Transaction.objects.filter(
            company_id=shift.company_id,
            source_type=SHIFT,
            source_id=shift.pk,
            status__in=LIVE_STATUSES,
        ).exclude(source_key="float")
    }
    for key, row in live.items():
        booking = wanted.get(key)
        if booking is not None and _matches(row, booking):
            wanted.pop(key)
            continue
        if by is None:
            raise ValueError("Correcting a shift's bookings needs a person (by).")
        finance.void_transaction(row, by=by, reason=reason or _("Shift corrected"))
    for booking in wanted.values():
        _book(shift, booking, by=by)


def _matches(row: Transaction, booking: Booking) -> bool:
    return (
        row.kind == booking.kind
        and abs(row.amount) == booking.amount
        and row.account_id == booking.account.pk
        and row.is_contra == booking.is_contra
    )


def _book(shift: CashShift, booking: Booking, *, by: Membership | None) -> Transaction:
    return finance.record_transaction(
        shift.company,
        by=by,
        kind=booking.kind,
        amount=booking.amount,
        occurred_on=shift.business_day,
        account=booking.account,
        category=booking.category,
        membership=booking.membership,
        branch=shift.branch,
        is_contra=booking.is_contra,
        description=booking.description[:300],
        source=Source(SHIFT, shift.pk, booking.key),
    )


def shift_rows(shift: CashShift):
    """The shift's live ledger rows (for the drawer's "In the ledger" list)."""
    return (
        Transaction.objects.filter(
            company_id=shift.company_id, source_type=SHIFT, source_id=shift.pk
        )
        .filter(status__in=LIVE_STATUSES)
        .select_related("account", "category")
        .order_by("pk")
    )


# Movements -----------------------------------------------------------------------------


def book_movement(movement: CashMovement, *, by: Membership | None) -> None:
    """Book a movement that has happened (a handover: once confirmed). Idempotent."""
    if movement.transaction_id is not None or movement.transfer_id is not None:
        return
    company = movement.company
    till = movement.register.cash_account
    day = movement_day(movement)
    source = Source(MOVEMENT, movement.pk)
    description = movement.reason or movement.get_kind_display()
    if movement.kind == CashMovement.Kind.PAYOUT:
        movement.transaction = finance.record_transaction(
            company,
            by=by,
            kind="expense",
            amount=movement.amount,
            occurred_on=day,
            account=till,
            category=movement.category,
            branch=movement.branch,
            description=description[:300],
            source=source,
        )
        movement.save(update_fields=["transaction", "updated_at"])
        return
    source_account, target_account = _transfer_accounts(movement)
    movement.transfer = finance.transfer(
        company,
        by=by,
        from_account=source_account,
        to_account=target_account,
        amount_out=movement.amount,
        occurred_on=day,
        description=description[:300],
        source=source,
    )
    movement.save(update_fields=["transfer", "updated_at"])


def _transfer_accounts(movement: CashMovement) -> tuple[MoneyAccount, MoneyAccount]:
    till = movement.register.cash_account
    kind = movement.kind
    if kind == CashMovement.Kind.HANDOVER:
        return till, finance.account_for_holder(movement.company, movement.receiver)
    if kind == CashMovement.Kind.TO_SAFE:
        return till, finance.account_for_branch(movement.branch, currency=till.currency)
    if kind == CashMovement.Kind.FROM_SAFE:
        return finance.account_for_branch(movement.branch, currency=till.currency), till
    if kind == CashMovement.Kind.TO_BANK:
        return till, movement.to_account
    if kind == CashMovement.Kind.DEPOSIT:
        return movement.to_account, till
    raise ValueError(f"Unknown movement kind {kind!r}.")


def void_movement_booking(movement: CashMovement, *, by: Membership, reason: str) -> None:
    if movement.transaction_id is not None:
        finance.void_transaction(movement.transaction, by=by, reason=reason)
    if movement.transfer_id is not None:
        finance.void_transfer(movement.transfer, by=by, reason=reason)


def movement_day(movement: CashMovement):
    """A movement books on its shift's business day, or on the day it happened."""
    if movement.shift_id is not None:
        return movement.shift.business_day
    from apps.sales.days import business_day

    return business_day(movement.company, movement.created_at)


# Single receipts outside a shift --------------------------------------------------------


def book_sale(sale: Sale, register: Register, *, by: Membership | None) -> None:
    """A receipt entered without a shift books on its own (one row per payment method)."""
    for payment in sale.payments.select_related("method__account"):
        method = payment.method
        if method.is_credit:
            continue
        account = payment_account(register, method)
        is_refund = sale.kind == Sale.Kind.REFUND
        finance.record_transaction(
            sale.company,
            by=by,
            kind="income",
            amount=quantize(payment.amount),
            occurred_on=sale.business_day,
            account=account,
            category="refunds" if is_refund else "sales",
            is_contra=is_refund,
            branch=sale.branch,
            description=(sale.note or _("Receipt %(number)s") % {"number": sale})[:300],
            source=Source(SALE, sale.pk, f"m{method.pk}"),
        )


def void_sale_booking(sale: Sale, *, by: Membership, reason: str) -> None:
    rows = Transaction.objects.filter(
        company_id=sale.company_id, source_type=SALE, source_id=sale.pk, status__in=LIVE_STATUSES
    )
    for row in rows:
        finance.void_transaction(row, by=by, reason=reason)
