"""Business logic of sales and cash: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

Services check business rules (one open shift per till and per cashier, who may confirm a
handover, a closed shift can't be closed twice); permissions are the API's and the bots' job.
Ledger rows go through `apps.sales.finance_bridge`, inside the same transaction, so a shift and
its bookings commit together or not at all. Rows are locked in one order everywhere: the sales
settings row, then the register, the shift, the movement, then whatever finance locks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.core.signals import send_on_commit
from apps.core.uploads import sanitize_image
from apps.finance.models import Category, MoneyAccount
from apps.inbox import services as inbox
from apps.members.models import Membership
from apps.sales import alerts, cash, finance_bridge, signals, tasks
from apps.sales.audit_actions import SalesAction
from apps.sales.conf import get_settings
from apps.sales.days import business_day
from apps.sales.models import (
    CashMovement,
    CashShift,
    PaymentMethod,
    Register,
    Sale,
    SalePayment,
    SalesSettings,
    SalesTarget,
    ShiftPayment,
)

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
MAX_AMOUNT = Decimal("9999999999999999.99")
MAX_COUNT = 100_000
MAX_DENOMINATION = 10_000_000

Status = CashShift.Status
Movement = CashMovement.Kind

# Pulse keys (registered in hooks.py).
PULSE_SHIFTS = "sales.shifts"
PULSE_OPEN = "sales.open_shifts"
PULSE_VERIFY = "sales.to_verify"
PULSE_CASH = "sales.cash"
PULSE_SETUP = "sales.setup"
PULSE_ENTRIES = "sales.entries"
PULSE_TARGETS = "sales.targets"


@dataclass(frozen=True)
class PaymentLine:
    """A shift's totals for one payment method, as typed at close or in a correction."""

    method: PaymentMethod
    sales: Decimal = ZERO
    refunds: Decimal = ZERO
    receipts: int = 0


# Helpers -------------------------------------------------------------------------------


def money(value, *, allow_zero: bool = False) -> Decimal:
    """A positive (or, with `allow_zero`, non-negative) amount with two decimals."""
    if isinstance(value, bool) or value is None or value == "":
        raise DomainError(_("Enter an amount."))
    try:
        amount = quantize(Decimal(str(value)))
    except InvalidOperation, ValueError:
        raise DomainError(_("Enter an amount.")) from None
    if amount < 0 or (amount == 0 and not allow_zero):
        raise DomainError(_("The amount must be more than zero."))
    if amount > MAX_AMOUNT:
        raise DomainError(_("That amount is too large."))
    return amount


def clean_count(count: dict | None) -> dict[str, int]:
    """A banknote count {"200000": 3, "50000": 4}: denominations as strings, counts ≥ 0. Rows
    counted as zero are dropped."""
    if not count:
        return {}
    if not isinstance(count, dict):
        raise DomainError(_("The cash count isn't readable."))
    cleaned: dict[str, int] = {}
    for key, value in count.items():
        try:
            denomination = int(str(key))
            pieces = int(value)
        except TypeError, ValueError:
            raise DomainError(_("The cash count isn't readable.")) from None
        if isinstance(value, bool) or denomination <= 0 or denomination > MAX_DENOMINATION:
            raise DomainError(_("The cash count isn't readable."))
        if pieces < 0 or pieces > MAX_COUNT:
            raise DomainError(_("The cash count isn't readable."))
        if pieces:
            cleaned[str(denomination)] = cleaned.get(str(denomination), 0) + pieces
    return dict(sorted(cleaned.items(), key=lambda item: -int(item[0])))


def count_total(count: dict[str, int]) -> Decimal:
    return quantize(sum((Decimal(key) * pieces for key, pieces in count.items()), ZERO))


def _counted(count: dict | None, amount) -> tuple[dict[str, int], Decimal | None]:
    """The count and its total; an explicit amount must agree with a non-empty count."""
    cleaned = clean_count(count)
    if cleaned:
        total = count_total(cleaned)
        if amount not in (None, "") and money(amount, allow_zero=True) != total:
            raise DomainError(_("The total doesn't match the banknotes counted."))
        return cleaned, total
    if amount in (None, ""):
        return {}, None
    return {}, money(amount, allow_zero=True)


def _same_company(company, *objects) -> None:
    for obj in objects:
        if obj is not None and getattr(obj, "company_id", company.pk) != company.pk:
            raise DomainError(_("Everything must belong to the same company."))


def _need_person(by) -> None:
    if not isinstance(by, Membership):
        raise ValueError("This needs a person (by).")


def _reason(reason: str, *, required: bool = True) -> str:
    text = (reason or "").strip()
    if required and not text:
        raise DomainError(_("Please give a reason."))
    return text[:300]


def _record(action: str, company, by: Membership | None, target, **details) -> None:
    audit.record(
        action,
        company_id=company.pk,
        actor=by.user if by is not None else None,
        target=target,
        **{key: _jsonable(value) for key, value in details.items()},
    )


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime | time):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _rollup(branch_id: int, day: date) -> None:
    transaction.on_commit(lambda: tasks.rollup_day.delay(branch_id, day.isoformat()))


def _lock_shift(shift: CashShift) -> CashShift:
    return (
        CashShift.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "register__cash_account", "cashier__user")
        .get(pk=shift.pk)
    )


def _photo(file):
    return sanitize_image(file) if file else None


# Settings ------------------------------------------------------------------------------

SETTINGS_FIELDS = (
    "business_day_ends_at",
    "cash_tolerance",
    "blind_cash_count",
    "require_z_photo",
    "require_terminal_photo",
    "mode",
    "handover_confirm_hours",
    "big_payout_alert",
    "late_open_minutes",
    "close_alert_minutes",
)


@transaction.atomic
def update_settings(company, *, by: Membership, **fields) -> SalesSettings:
    _need_person(by)
    unknown = set(fields) - set(SETTINGS_FIELDS)
    if unknown:
        raise ValueError(f"Unknown sales settings: {sorted(unknown)}")
    settings = SalesSettings.objects.select_for_update().get(pk=get_settings(company).pk)
    if "mode" in fields and fields["mode"] not in SalesSettings.Mode.values:
        raise DomainError(_("Pick a way of recording sales."))
    if fields.get("mode") == SalesSettings.Mode.INVOICES:
        raise DomainError(_("Invoices mode arrives with the invoices module."))
    for key in ("cash_tolerance", "big_payout_alert"):
        if fields.get(key) not in (None, ""):
            fields[key] = money(fields[key], allow_zero=True)
        elif key in fields:
            fields[key] = None if key == "big_payout_alert" else ZERO
    changes = {}
    for key, value in fields.items():
        before = getattr(settings, key)
        if before != value:
            changes[key] = [before, value]
            setattr(settings, key, value)
    if changes:
        settings.save()
        _record(SalesAction.SETTINGS_CHANGED, company, by, settings, changes=changes)
        _bump(company.pk, PULSE_SETUP)
    return settings


# Payment methods -----------------------------------------------------------------------


def _method_account(company, account) -> MoneyAccount | None:
    if account is None:
        return None
    _same_company(company, account)
    if not account.is_active:
        raise DomainError(_("%(account)s is archived.") % {"account": account})
    if account.currency != company.base_currency:
        raise DomainError(
            _("Sales are in %(currency)s: pick an account in %(currency)s.")
            % {"currency": company.base_currency}
        )
    return account


def _fee(value) -> Decimal:
    try:
        fee = Decimal(str(value if value not in (None, "") else 0)).quantize(Decimal("0.01"))
    except InvalidOperation, ValueError:
        raise DomainError(_("The fee is a percentage from 0 to 100.")) from None
    if fee < 0 or fee > 100:
        raise DomainError(_("The fee is a percentage from 0 to 100."))
    return fee


@transaction.atomic
def create_payment_method(
    company,
    *,
    by: Membership,
    name: str,
    kind: str,
    account: MoneyAccount | None = None,
    fee_percent=0,
    is_active: bool = True,
) -> PaymentMethod:
    _need_person(by)
    name = (name or "").strip()[:50]
    if not name:
        raise DomainError(_("Give the payment method a name."))
    if kind not in PaymentMethod.Kind.values:
        raise DomainError(_("Pick what kind of payment this is."))
    if kind == PaymentMethod.Kind.CASH:
        account = None
    if PaymentMethod.objects.filter(company=company, name__iexact=name).exists():
        raise DomainError(_("There is already a payment method called %(name)s.") % {"name": name})
    order = PaymentMethod.objects.filter(company=company).order_by("-order").first()
    method = PaymentMethod.objects.create(
        company=company,
        name=name,
        kind=kind,
        account=_method_account(company, account),
        fee_percent=_fee(fee_percent),
        is_active=is_active,
        order=(order.order + 1) if order else 0,
    )
    _record(SalesAction.METHOD_CREATED, company, by, method, name=name, kind=kind)
    _bump(company.pk, PULSE_SETUP)
    return method


@transaction.atomic
def update_payment_method(method: PaymentMethod, *, by: Membership, **fields) -> PaymentMethod:
    _need_person(by)
    company = method.company
    method = PaymentMethod.objects.select_for_update().get(pk=method.pk)
    allowed = {"name", "kind", "account", "fee_percent", "is_active"}
    if unknown := set(fields) - allowed:
        raise ValueError(f"Unknown payment method fields: {sorted(unknown)}")
    if "name" in fields:
        name = (fields["name"] or "").strip()[:50]
        if not name:
            raise DomainError(_("Give the payment method a name."))
        clash = PaymentMethod.objects.filter(company=company, name__iexact=name).exclude(
            pk=method.pk
        )
        if clash.exists():
            raise DomainError(
                _("There is already a payment method called %(name)s.") % {"name": name}
            )
        fields["name"] = name
    if "kind" in fields and fields["kind"] not in PaymentMethod.Kind.values:
        raise DomainError(_("Pick what kind of payment this is."))
    if "account" in fields:
        fields["account"] = _method_account(company, fields["account"])
    if "fee_percent" in fields:
        fields["fee_percent"] = _fee(fields["fee_percent"])
    kind = fields.get("kind", method.kind)
    if kind == PaymentMethod.Kind.CASH:
        fields["account"] = None
    if fields.get("is_active") is False and method.kind == PaymentMethod.Kind.CASH:
        others = PaymentMethod.objects.filter(
            company=company, kind=PaymentMethod.Kind.CASH, is_active=True
        ).exclude(pk=method.pk)
        if not others.exists():
            raise DomainError(_("Keep at least one cash method: every till takes cash."))
    changes = {}
    for key, value in fields.items():
        before = getattr(method, key)
        if before != value:
            changes[key] = [
                str(before) if before is not None else None,
                str(value) if value is not None else None,
            ]
            setattr(method, key, value)
    if changes:
        method.save()
        _record(SalesAction.METHOD_CHANGED, company, by, method, changes=changes)
        _bump(company.pk, PULSE_SETUP)
    return method


@transaction.atomic
def reorder_payment_methods(company, *, by: Membership, ids: list[int]) -> None:
    _need_person(by)
    methods = {m.pk: m for m in PaymentMethod.objects.select_for_update().filter(company=company)}
    if set(ids) - set(methods):
        raise DomainError(_("Some of these payment methods don't exist."))
    ordered = list(ids) + [
        pk for pk in sorted(methods, key=lambda pk: methods[pk].order) if pk not in ids
    ]
    for position, pk in enumerate(ordered):
        if methods[pk].order != position:
            PaymentMethod.objects.filter(pk=pk).update(order=position, updated_at=timezone.now())
    _record(SalesAction.METHODS_REORDERED, company, by, company, ids=ordered)
    _bump(company.pk, PULSE_SETUP)


# Registers -----------------------------------------------------------------------------


@transaction.atomic
def create_register(
    company, *, by: Membership, branch, name: str, fiscal_serial: str = ""
) -> Register:
    _need_person(by)
    _same_company(company, branch)
    if not branch.is_active:
        raise DomainError(_("%(branch)s is closed.") % {"branch": branch})
    name = (name or "").strip()[:50]
    if not name:
        raise DomainError(_("Give the till a name."))
    if Register.objects.filter(branch=branch, name__iexact=name).exists():
        raise DomainError(
            _("%(branch)s already has a till called %(name)s.") % {"branch": branch, "name": name}
        )
    account = finance_bridge.create_till_account(name, branch, by=by)
    order = Register.objects.filter(branch=branch).count()
    try:
        with transaction.atomic():
            register = Register.objects.create(
                company=company,
                branch=branch,
                name=name,
                cash_account=account,
                fiscal_serial=(fiscal_serial or "").strip()[:32],
                order=order,
            )
    except IntegrityError:
        raise DomainError(
            _("%(branch)s already has a till called %(name)s.") % {"branch": branch, "name": name}
        ) from None
    _record(SalesAction.REGISTER_CREATED, company, by, register, branch=branch.pk, name=name)
    _bump(company.pk, PULSE_SETUP)
    return register


@transaction.atomic
def update_register(register: Register, *, by: Membership, **fields) -> Register:
    _need_person(by)
    company = register.company
    register = Register.objects.select_for_update().select_related("branch").get(pk=register.pk)
    allowed = {"name", "fiscal_serial", "is_active", "order"}
    if unknown := set(fields) - allowed:
        raise ValueError(f"Unknown till fields: {sorted(unknown)}")
    if "name" in fields:
        name = (fields["name"] or "").strip()[:50]
        if not name:
            raise DomainError(_("Give the till a name."))
        if (
            Register.objects.filter(branch=register.branch, name__iexact=name)
            .exclude(pk=register.pk)
            .exists()
        ):
            raise DomainError(
                _("%(branch)s already has a till called %(name)s.")
                % {"branch": register.branch, "name": name}
            )
        fields["name"] = name
    if "fiscal_serial" in fields:
        fields["fiscal_serial"] = (fields["fiscal_serial"] or "").strip()[:32]
    open_now = CashShift.objects.filter(register=register, status=Status.OPEN)
    if fields.get("is_active") is False and open_now.exists():
        raise DomainError(_("Close the open shift on this till first."))
    changes = {}
    for key, value in fields.items():
        before = getattr(register, key)
        if before != value:
            changes[key] = [before, value]
            setattr(register, key, value)
    if changes:
        register.save()
        _record(SalesAction.REGISTER_CHANGED, company, by, register, changes=changes)
        _bump(company.pk, PULSE_SETUP)
    return register


# Targets -------------------------------------------------------------------------------


@transaction.atomic
def set_target(
    company, *, by: Membership, month: date, amount, branch=None, membership=None
) -> SalesTarget:
    """Set (or change) the goal for a month: the company's, a branch's or one person's."""
    _need_person(by)
    _same_company(company, branch, membership)
    if branch is not None and membership is not None:
        raise DomainError(_("A target is for the company, a branch or one person."))
    month = month.replace(day=1)
    amount = money(amount)
    target, created = SalesTarget.objects.select_for_update().get_or_create(
        company=company,
        month=month,
        branch=branch,
        membership=membership,
        defaults={"amount": amount},
    )
    before = None if created else target.amount
    if not created and target.amount != amount:
        target.amount = amount
        target.save(update_fields=["amount", "updated_at"])
    _record(
        SalesAction.TARGET_SET,
        company,
        by,
        target,
        month=month,
        amount=amount,
        before=before,
        branch=branch.pk if branch else None,
        membership=membership.pk if membership else None,
    )
    _bump(company.pk, PULSE_TARGETS)
    return target


@transaction.atomic
def delete_target(target: SalesTarget, *, by: Membership) -> None:
    _need_person(by)
    company = target.company
    _record(
        SalesAction.TARGET_DELETED, company, by, target, month=target.month, amount=target.amount
    )
    target.delete()
    _bump(company.pk, PULSE_TARGETS)


# Shifts --------------------------------------------------------------------------------


@transaction.atomic
def open_shift(
    *,
    by: Membership,
    register: Register,
    opening_count: dict | None = None,
    opening_float=None,
    now: datetime | None = None,
) -> CashShift:
    """`by` starts a shift on `register` with the float they counted."""
    _need_person(by)
    company = register.company
    _same_company(company, by)
    count, total = _counted(opening_count, opening_float)
    opening = total if total is not None else ZERO
    now = now or timezone.now()

    # The counter first (one global order), then the till: two cashiers opening at once wait
    # for each other here, so numbers never repeat.
    settings = SalesSettings.objects.select_for_update().get(pk=get_settings(company).pk)
    register = (
        Register.objects.select_for_update(of=("self",))
        .select_related("branch", "cash_account")
        .get(pk=register.pk)
    )
    if not register.is_active or not register.branch.is_active:
        raise DomainError(_("This till is closed."))
    taken = (
        CashShift.objects.filter(register=register, status=Status.OPEN)
        .select_related("cashier", "branch")
        .first()
    )
    if taken is not None:
        raise DomainError(
            _("%(till)s already has an open shift (%(shift)s, %(person)s).")
            % {"till": register.name, "shift": taken.code, "person": taken.cashier}
        )
    mine = CashShift.objects.filter(cashier=by, status=Status.OPEN).select_related("branch").first()
    if mine is not None:
        raise DomainError(
            _("You already have an open shift (%(shift)s). Close it first.") % {"shift": mine.code}
        )
    first = not CashShift.objects.filter(register=register).exists() and not cash.till_physical(
        register
    )
    number = settings.next_shift_number
    SalesSettings.objects.filter(pk=settings.pk).update(
        next_shift_number=F("next_shift_number") + 1
    )
    try:
        with transaction.atomic():
            shift = CashShift.objects.create(
                company=company,
                number=number,
                branch=register.branch,
                register=register,
                cashier=by,
                business_day=business_day(company, now, ends_at=settings.business_day_ends_at),
                opened_at=now,
                opening_float=opening,
                opening_count=count,
                expected_float=None if first else cash.till_physical(register),
            )
    except IntegrityError:
        raise DomainError(_("This till or this cashier already has an open shift.")) from None
    finance_bridge.book_float(shift, by=by, first=first)
    _record(
        SalesAction.SHIFT_OPENED,
        company,
        by,
        shift,
        register=register.pk,
        opening_float=opening,
        expected_float=shift.expected_float,
    )
    difference = None if shift.expected_float is None else opening - shift.expected_float
    if difference and abs(difference) > settings.cash_tolerance:
        transaction.on_commit(lambda: alerts.float_difference(shift.pk))
    _bump(company.pk, PULSE_SHIFTS, PULSE_OPEN, PULSE_CASH)
    return shift


def receipt_lines(shift: CashShift) -> list[PaymentLine]:
    """Receipts mode: the shift's totals per method from its recorded receipts."""
    found = cash.receipts_by_method(shift)
    methods = PaymentMethod.objects.filter(pk__in=found)
    return [
        PaymentLine(m, found[m.pk]["sales"], found[m.pk]["refunds"], found[m.pk]["receipts"])
        for m in methods
    ]


def _check_lines(company, lines: list[PaymentLine]) -> list[PaymentLine]:
    seen = set()
    cleaned = []
    for line in lines:
        method = line.method
        _same_company(company, method)
        if method.pk in seen:
            raise DomainError(_("%(method)s is listed twice.") % {"method": method})
        seen.add(method.pk)
        sales = money(line.sales or 0, allow_zero=True)
        refunds = money(line.refunds or 0, allow_zero=True)
        receipts = int(line.receipts or 0)
        if receipts < 0:
            raise DomainError(_("The number of receipts can't be negative."))
        if sales or refunds or receipts:
            cleaned.append(PaymentLine(method, sales, refunds, receipts))
    return cleaned


def _save_lines(shift: CashShift, lines: list[PaymentLine]) -> None:
    shift.payments.all().delete()
    ShiftPayment.objects.bulk_create(
        ShiftPayment(
            shift=shift,
            method=line.method,
            sales=line.sales,
            refunds=line.refunds,
            receipts=line.receipts,
        )
        for line in lines
    )


def _settle_difference(shift: CashShift) -> None:
    shift.expected_cash = cash.expected_cash(shift)
    final = shift.final_count
    shift.difference = None if final is None else final - shift.expected_cash


def _lines_snapshot(lines) -> list[dict]:
    return [
        {
            "method": line.method.pk,
            "sales": str(line.sales),
            "refunds": str(line.refunds),
            "receipts": line.receipts,
        }
        for line in lines
    ]


@transaction.atomic
def close_shift(
    shift: CashShift,
    *,
    by: Membership,
    payments: list[PaymentLine] | None = None,
    counted_cash=None,
    closing_count: dict | None = None,
    receipts: int | None = None,
    z_number: str = "",
    fiscal_cash_total=None,
    fiscal_card_total=None,
    z_photo=None,
    terminal_photo=None,
    note: str = "",
    now: datetime | None = None,
) -> CashShift:
    """The cashier closes their shift: totals per method from the Z-report, the cash they
    counted (blind), photos. Books the ledger rows of §3.8."""
    _need_person(by)
    shift = _lock_shift(shift)
    company = shift.company
    if shift.status != Status.OPEN:
        raise DomainError(_("This shift is already closed."))
    settings = get_settings(company)
    if payments is None:
        payments = receipt_lines(shift) if settings.mode == SalesSettings.Mode.RECEIPTS else []
    lines = _check_lines(company, payments)
    count, counted = _counted(closing_count, counted_cash)
    if counted is None:
        raise DomainError(_("Count the cash in the till."))
    takes_cards = any(
        line.sales and line.method.kind in (PaymentMethod.Kind.CARD, PaymentMethod.Kind.QR)
        for line in lines
    )
    if settings.require_z_photo and not z_photo:
        raise DomainError(_("Add a photo of the Z-report."))
    if settings.require_terminal_photo and takes_cards and not terminal_photo:
        raise DomainError(_("Add a photo of the terminal slip."))
    z_image, terminal_image = _photo(z_photo), _photo(terminal_photo)

    _save_lines(shift, lines)
    shift.counted_cash = counted
    shift.closing_count = count
    shift.receipts = max(int(receipts or 0), 0) or sum(line.receipts for line in lines)
    shift.status = Status.CLOSED
    _settle_difference(shift)
    shift.closed_at = now or timezone.now()
    shift.closed_by = by
    shift.z_number = (z_number or "").strip()[:32]
    shift.fiscal_cash_total = (
        money(fiscal_cash_total, allow_zero=True) if fiscal_cash_total not in (None, "") else None
    )
    shift.fiscal_card_total = (
        money(fiscal_card_total, allow_zero=True) if fiscal_card_total not in (None, "") else None
    )
    shift.cashier_note = (note or "").strip()[:2000]
    if z_image is not None:
        shift.z_photo.save(z_image.name, z_image, save=False)
    if terminal_image is not None:
        shift.terminal_photo.save(terminal_image.name, terminal_image, save=False)
    shift.save()
    finance_bridge.rebook_shift(shift, by=by)
    _record(
        SalesAction.SHIFT_CLOSED,
        company,
        by,
        shift,
        payments=_lines_snapshot(lines),
        counted_cash=counted,
        expected_cash=shift.expected_cash,
        difference=shift.difference,
    )
    _after_close(shift, settings)
    return shift


def _after_close(shift: CashShift, settings: SalesSettings) -> None:
    pk, company_id = shift.pk, shift.company_id
    _rollup(shift.branch_id, shift.business_day)
    transaction.on_commit(lambda: alerts.shift_closed(pk))
    send_on_commit(signals.shift_closed, sender=CashShift, shift=shift)
    _bump(company_id, PULSE_SHIFTS, PULSE_OPEN, PULSE_VERIFY, PULSE_CASH)


@transaction.atomic
def force_close(
    shift: CashShift,
    *,
    by: Membership,
    reason: str,
    payments: list[PaymentLine] | None = None,
    counted_cash=None,
    now: datetime | None = None,
) -> CashShift:
    """A manager closes a shift the cashier left open. Without a count the difference stays
    unknown (nothing is booked for it) until someone corrects the shift with one."""
    _need_person(by)
    reason = _reason(reason)
    shift = _lock_shift(shift)
    company = shift.company
    if shift.status != Status.OPEN:
        raise DomainError(_("This shift is already closed."))
    settings = get_settings(company)
    if payments is None:
        payments = receipt_lines(shift) if settings.mode == SalesSettings.Mode.RECEIPTS else []
    lines = _check_lines(company, payments)
    _save_lines(shift, lines)
    shift.counted_cash = (
        money(counted_cash, allow_zero=True) if counted_cash not in (None, "") else None
    )
    shift.receipts = sum(line.receipts for line in lines)
    shift.status = Status.CLOSED
    _settle_difference(shift)
    shift.forced = True
    shift.closed_at = now or timezone.now()
    shift.closed_by = by
    shift.note = reason
    shift.save()
    finance_bridge.rebook_shift(shift, by=by, reason=reason)
    _record(
        SalesAction.SHIFT_FORCE_CLOSED,
        company,
        by,
        shift,
        reason=reason,
        payments=_lines_snapshot(lines),
        counted_cash=shift.counted_cash,
        difference=shift.difference,
    )
    _after_close(shift, settings)
    return shift


def _may_verify(shift: CashShift, by: Membership) -> None:
    if shift.cashier_id == by.pk and not (by.role and by.role.is_owner):
        raise DomainError(_("Someone else has to check your own shift."))


@transaction.atomic
def verify_shift(
    shift: CashShift, *, by: Membership, recount_cash=None, note: str = ""
) -> CashShift:
    """A manager checks a closed (or disputed) shift, optionally recounting the cash: the
    recount then decides the difference, and the ledger follows."""
    _need_person(by)
    shift = _lock_shift(shift)
    company = shift.company
    if shift.status not in (Status.CLOSED, Status.DISPUTED):
        raise DomainError(_("Only a closed shift can be verified."))
    _may_verify(shift, by)
    before = shift.difference
    if recount_cash not in (None, ""):
        shift.recount_cash = money(recount_cash, allow_zero=True)
    _settle_difference(shift)
    shift.status = Status.VERIFIED
    shift.verified_by = by
    shift.verified_at = timezone.now()
    if note:
        shift.note = note.strip()[:2000]
    shift.save()
    if shift.difference != before:
        finance_bridge.rebook_shift(shift, by=by, reason=_("Recounted at verification"))
        _rollup(shift.branch_id, shift.business_day)
    inbox.settle(shift, outcome=_("Verified"), by=by)
    _record(
        SalesAction.SHIFT_VERIFIED,
        company,
        by,
        shift,
        recount_cash=shift.recount_cash,
        difference=shift.difference,
        note=shift.note,
    )
    pk = shift.pk
    transaction.on_commit(lambda: alerts.shift_verified(pk))
    send_on_commit(signals.shift_verified, sender=CashShift, shift=shift)
    _bump(company.pk, PULSE_SHIFTS, PULSE_VERIFY)
    return shift


@transaction.atomic
def dispute_shift(shift: CashShift, *, by: Membership, reason: str) -> CashShift:
    """A manager doesn't accept a closed shift as it is; the cashier is told why."""
    _need_person(by)
    reason = _reason(reason)
    shift = _lock_shift(shift)
    company = shift.company
    if shift.status not in (Status.CLOSED, Status.VERIFIED):
        raise DomainError(_("Only a closed shift can be disputed."))
    _may_verify(shift, by)
    shift.status = Status.DISPUTED
    shift.note = reason
    shift.verified_by = None
    shift.verified_at = None
    shift.save(update_fields=["status", "note", "verified_by", "verified_at", "updated_at"])
    inbox.settle(shift, outcome=_("Disputed"), by=by)
    _record(SalesAction.SHIFT_DISPUTED, company, by, shift, reason=reason)
    pk = shift.pk
    by_id = by.pk
    transaction.on_commit(lambda: alerts.shift_disputed(pk, by_id))
    _bump(company.pk, PULSE_SHIFTS, PULSE_VERIFY)
    return shift


@transaction.atomic
def correct_shift(
    shift: CashShift,
    *,
    by: Membership,
    payments: list[PaymentLine],
    reason: str,
    counted_cash=None,
) -> CashShift:
    """A manager fixes a closed shift's totals (and optionally the cash count, as their own
    recount). The difference is recomputed and the ledger voided and rebooked to match."""
    _need_person(by)
    reason = _reason(reason)
    shift = _lock_shift(shift)
    company = shift.company
    if shift.status == Status.OPEN:
        raise DomainError(_("Close the shift before correcting it."))
    before = _lines_snapshot(list(shift.payments.select_related("method")))
    before_difference = shift.difference
    lines = _check_lines(company, payments)
    _save_lines(shift, lines)
    if counted_cash not in (None, ""):
        shift.recount_cash = money(counted_cash, allow_zero=True)
    _settle_difference(shift)
    shift.save()
    finance_bridge.rebook_shift(shift, by=by, reason=reason)
    _record(
        SalesAction.SHIFT_CORRECTED,
        company,
        by,
        shift,
        reason=reason,
        before=before,
        after=_lines_snapshot(lines),
        difference_before=before_difference,
        difference=shift.difference,
    )
    _rollup(shift.branch_id, shift.business_day)
    _bump(company.pk, PULSE_SHIFTS, PULSE_CASH)
    return shift


@transaction.atomic
def record_ai_reading(shift: CashShift, *, reading: dict, mismatch: bool) -> CashShift:
    """What AI read from the Z-report and terminal photos (package K). The only writer of
    `ai_reading`; a mismatch tells the people who verify shifts."""
    if not isinstance(reading, dict):
        raise ValueError("reading is a dict.")
    shift = _lock_shift(shift)
    shift.ai_reading = _jsonable(reading)
    shift.ai_mismatch = bool(mismatch)
    shift.save(update_fields=["ai_reading", "ai_mismatch", "updated_at"])
    _record(SalesAction.SHIFT_AI_READING, shift.company, None, shift, mismatch=bool(mismatch))
    if mismatch:
        pk = shift.pk
        transaction.on_commit(lambda: alerts.ai_mismatch(pk))
    _bump(shift.company_id, PULSE_SHIFTS)
    return shift


# Cash movements ------------------------------------------------------------------------

APP_MOVEMENTS = (Movement.PAYOUT, Movement.HANDOVER, Movement.TO_SAFE, Movement.FROM_SAFE)


def _payout_category(company, category) -> Category:
    if category is None or category == "":
        category = "other_expense"
    if isinstance(category, str):
        found = Category.objects.filter(company=company, system_code=category).first()
        if found is None:
            raise DomainError(_("Pick what the money was spent on."))
        category = found
    _same_company(company, category)
    if category.kind != Category.Kind.EXPENSE or not category.is_active:
        raise DomainError(_("Pick what the money was spent on."))
    return category


def _counter_account(company, account, till: MoneyAccount) -> MoneyAccount:
    if account is None:
        raise DomainError(_("Pick the account."))
    _same_company(company, account)
    if not account.is_active:
        raise DomainError(_("%(account)s is archived.") % {"account": account})
    if account.pk == till.pk:
        raise DomainError(_("Pick another account than the till itself."))
    if account.currency != till.currency:
        raise DomainError(
            _("The till holds %(currency)s: pick an account in %(currency)s.")
            % {"currency": till.currency}
        )
    return account


@transaction.atomic
def record_movement(
    *,
    by: Membership,
    register: Register,
    kind: str,
    amount,
    receiver: Membership | None = None,
    to_account: MoneyAccount | None = None,
    category=None,
    reason: str = "",
    photo=None,
    now: datetime | None = None,
) -> CashMovement:
    """Cash leaves or enters a till: a payout (an expense), a handover to a person (booked when
    they confirm), to or from the safe, to the bank, or a deposit from another account."""
    _need_person(by)
    company = register.company
    _same_company(company, by, receiver, to_account)
    if kind not in Movement.values:
        raise DomainError(_("Pick what kind of movement this is."))
    amount = money(amount)
    register = Register.objects.select_related("branch", "cash_account").get(pk=register.pk)
    if not register.is_active:
        raise DomainError(_("This till is closed."))
    shift = (
        CashShift.objects.select_for_update(of=("self",))
        .filter(register=register, status=Status.OPEN)
        .first()
    )
    reason = (reason or "").strip()[:200]
    payout_category = None
    if kind == Movement.PAYOUT:
        if not reason:
            raise DomainError(_("Say what the money was paid for."))
        payout_category = _payout_category(company, category)
    if kind == Movement.HANDOVER:
        if receiver is None:
            raise DomainError(_("Pick who receives the cash."))
        if receiver.status != Membership.Status.APPROVED:
            raise DomainError(_("%(person)s can't receive cash now.") % {"person": receiver})
        if receiver.pk == by.pk:
            raise DomainError(_("You can't hand cash over to yourself."))
    else:
        receiver = None
    if kind in (Movement.TO_BANK, Movement.DEPOSIT):
        to_account = _counter_account(company, to_account, register.cash_account)
    else:
        to_account = None
    image = _photo(photo)
    now = now or timezone.now()
    movement = CashMovement(
        company=company,
        branch=register.branch,
        register=register,
        shift=shift,
        kind=kind,
        amount=amount,
        currency=register.cash_account.currency,
        receiver=receiver,
        to_account=to_account,
        category=payout_category,
        reason=reason,
        created_by=by,
        confirmed_at=None if kind == Movement.HANDOVER else now,
        confirmed_by=None if kind == Movement.HANDOVER else by,
    )
    if image is not None:
        movement.photo.save(image.name, image, save=False)
    movement.save()
    if kind != Movement.HANDOVER:
        finance_bridge.book_movement(movement, by=by)
    _record(
        SalesAction.MOVEMENT_RECORDED,
        company,
        by,
        movement,
        kind=kind,
        amount=amount,
        register=register.pk,
        shift=shift.pk if shift else None,
        receiver=receiver.pk if receiver else None,
        reason=reason,
    )
    pk = movement.pk
    if kind == Movement.HANDOVER:
        transaction.on_commit(lambda: alerts.handover_sent(pk))
    settings = get_settings(company)
    if (
        kind == Movement.PAYOUT
        and settings.big_payout_alert
        and amount >= settings.big_payout_alert
    ):
        transaction.on_commit(lambda: alerts.big_payout(pk))
    _bump(company.pk, PULSE_CASH, PULSE_SHIFTS)
    return movement


def _lock_movement(movement: CashMovement) -> CashMovement:
    return (
        CashMovement.objects.select_for_update(of=("self",))
        .select_related(
            "company", "branch", "register__cash_account", "shift", "receiver", "created_by"
        )
        .get(pk=movement.pk)
    )


@transaction.atomic
def confirm_handover(movement: CashMovement, *, by: Membership) -> CashMovement:
    """The receiver confirms they got the cash: only now does it move in the ledger."""
    _need_person(by)
    movement = _lock_movement(movement)
    _check_pending_handover(movement, by)
    movement.confirmed_at = timezone.now()
    movement.confirmed_by = by
    movement.save(update_fields=["confirmed_at", "confirmed_by", "updated_at"])
    finance_bridge.book_movement(movement, by=by)
    inbox.settle(movement, outcome=_("Received"), by=by)
    _record(SalesAction.HANDOVER_CONFIRMED, movement.company, by, movement, amount=movement.amount)
    _bump(movement.company_id, PULSE_CASH)
    return movement


@transaction.atomic
def decline_handover(movement: CashMovement, *, by: Membership, reason: str = "") -> CashMovement:
    """The receiver says the cash never arrived: nothing moves, and the owners hear at once."""
    _need_person(by)
    movement = _lock_movement(movement)
    _check_pending_handover(movement, by)
    movement.declined_at = timezone.now()
    movement.decline_reason = (reason or "").strip()[:200]
    movement.save(update_fields=["declined_at", "decline_reason", "updated_at"])
    inbox.settle(movement, outcome=_("Not received"), by=by)
    _record(
        SalesAction.HANDOVER_DECLINED,
        movement.company,
        by,
        movement,
        amount=movement.amount,
        reason=movement.decline_reason,
    )
    pk = movement.pk
    transaction.on_commit(lambda: alerts.handover_declined(pk))
    _bump(movement.company_id, PULSE_CASH)
    return movement


def _check_pending_handover(movement: CashMovement, by: Membership) -> None:
    if movement.kind != Movement.HANDOVER:
        raise DomainError(_("This isn't a handover."))
    if movement.receiver_id != by.pk:
        raise DomainError(_("Only the person receiving the cash can answer this."))
    if movement.voided_at is not None:
        raise DomainError(_("This handover was cancelled."))
    if movement.confirmed_at is not None or movement.declined_at is not None:
        raise DomainError(_("This has already been answered."))


@transaction.atomic
def void_movement(movement: CashMovement, *, by: Membership, reason: str) -> CashMovement:
    """Cancel a movement entered by mistake: its ledger rows are voided and, on a closed shift,
    the expected cash and the difference follow."""
    _need_person(by)
    reason = _reason(reason)
    movement = _lock_movement(movement)
    if movement.voided_at is not None:
        raise DomainError(_("This movement is already void."))
    shift = _lock_shift(movement.shift) if movement.shift_id else None
    finance_bridge.void_movement_booking(movement, by=by, reason=reason)
    movement.voided_at = timezone.now()
    movement.voided_by = by.user
    movement.void_reason = reason
    movement.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    inbox.settle(movement, outcome=_("Cancelled"), by=by)
    if shift is not None and shift.status != Status.OPEN:
        _settle_difference(shift)
        shift.save(update_fields=["expected_cash", "difference", "updated_at"])
        finance_bridge.rebook_shift(shift, by=by, reason=reason)
        _rollup(shift.branch_id, shift.business_day)
    _record(SalesAction.MOVEMENT_VOIDED, movement.company, by, movement, reason=reason)
    _bump(movement.company_id, PULSE_CASH, PULSE_SHIFTS)
    return movement


# Single receipts -----------------------------------------------------------------------


@transaction.atomic
def record_sale(
    *,
    by: Membership,
    payments: list[tuple[PaymentMethod, object]],
    kind: str = Sale.Kind.SALE,
    branch=None,
    register: Register | None = None,
    discount=0,
    number: str = "",
    note: str = "",
    source: str = Sale.Source.APP,
    sold_at: datetime | None = None,
    external_id: str = "",
) -> Sale:
    """A single receipt. From the mini app it belongs to the cashier's open shift (and counts in
    its totals at close); from the dashboard it books on its own."""
    _need_person(by)
    company = by.company
    if kind not in Sale.Kind.values:
        raise DomainError(_("Pick sale or refund."))
    if not payments:
        raise DomainError(_("Add how the customer paid."))
    lines = []
    for method, amount in payments:
        _same_company(company, method)
        if not method.is_active:
            raise DomainError(_("%(method)s is switched off.") % {"method": method})
        lines.append((method, money(amount)))
    total = sum((amount for _method, amount in lines), ZERO)
    sold_at = sold_at or timezone.now()
    shift = None
    if source == Sale.Source.APP:
        shift = (
            CashShift.objects.select_for_update(of=("self",))
            .select_related("branch", "register")
            .filter(cashier=by, status=Status.OPEN)
            .first()
        )
        if shift is None:
            raise DomainError(_("Open a shift first."))
        branch, register = shift.branch, shift.register
    else:
        _same_company(company, branch, register)
        if branch is None:
            raise DomainError(_("Pick the branch."))
        if register is None:
            register = (
                Register.objects.filter(branch=branch, is_active=True)
                .order_by("order", "pk")
                .first()
            )
        if register is None:
            raise DomainError(_("%(branch)s has no till yet.") % {"branch": branch})
        if register.branch_id != branch.pk:
            raise DomainError(_("That till is in another branch."))
    day = shift.business_day if shift else business_day(company, sold_at)
    sale = Sale.objects.create(
        company=company,
        branch=branch,
        shift=shift,
        register=register,
        cashier=shift.cashier if shift else None,
        performed_by=by,
        sold_at=sold_at,
        business_day=day,
        kind=kind,
        number=(number or "").strip()[:32],
        total=total,
        discount=money(discount, allow_zero=True) if discount not in (None, "") else ZERO,
        note=(note or "").strip()[:300],
        source=source,
        external_id=(external_id or "").strip()[:64],
    )
    SalePayment.objects.bulk_create(
        SalePayment(sale=sale, method=method, amount=amount) for method, amount in lines
    )
    if shift is None:
        finance_bridge.book_sale(sale, register, by=by)
        _rollup(branch.pk, day)
    _record(
        SalesAction.SALE_RECORDED,
        company,
        by,
        sale,
        kind=kind,
        total=total,
        shift=shift.pk if shift else None,
    )
    _bump(company.pk, PULSE_ENTRIES, PULSE_CASH)
    return sale


@transaction.atomic
def void_sale(sale: Sale, *, by: Membership, reason: str) -> Sale:
    _need_person(by)
    reason = _reason(reason)
    sale = Sale.objects.select_for_update(of=("self",)).select_related("shift").get(pk=sale.pk)
    if sale.voided_at is not None:
        raise DomainError(_("This receipt is already void."))
    if sale.shift_id is not None and sale.shift.status != Status.OPEN:
        raise DomainError(
            _("This receipt is part of the closed shift %(shift)s: correct the shift instead.")
            % {"shift": sale.shift.code}
        )
    if sale.shift_id is None:
        finance_bridge.void_sale_booking(sale, by=by, reason=reason)
        _rollup(sale.branch_id, sale.business_day)
    sale.voided_at = timezone.now()
    sale.voided_by = by.user
    sale.void_reason = reason
    sale.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    _record(SalesAction.SALE_VOIDED, sale.company, by, sale, reason=reason)
    _bump(sale.company_id, PULSE_ENTRIES, PULSE_CASH)
    return sale
