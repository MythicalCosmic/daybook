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
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Branch
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.core.signals import send_on_commit
from apps.core.uploads import accept_document, sanitize_image
from apps.finance.models import Category, MoneyAccount
from apps.inbox import services as inbox
from apps.members.models import Membership
from apps.sales import alerts, cash, finance_bridge, importer, lines, signals, tasks
from apps.sales.audit_actions import SalesAction
from apps.sales.bot_messages import money as msg_money
from apps.sales.conf import get_settings
from apps.sales.days import business_day
from apps.sales.models import (
    CashMovement,
    CashShift,
    CustomerKind,
    PaymentMethod,
    PosCashier,
    Register,
    Sale,
    SalePayment,
    SalesImport,
    SalesImportProfile,
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
PULSE_LINES = lines.PULSE_LINES  # the Import and Lines pages
PULSE_UNMATCHED = lines.PULSE_UNMATCHED  # the match list's badge
PULSE_CUSTOMERS = "sales.customers"


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
    "sales_lines",
    "credit_days",
    "invoice_prefix",
    "invoice_terms_days",
    "invoice_footer",
    "rx_wholesale_max_markup_percent",
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
    if "sales_lines" in fields:
        if fields["sales_lines"] not in SalesSettings.Lines.values:
            raise DomainError(_("Pick where your sale lines come from."))
        if fields["sales_lines"] == SalesSettings.Lines.RECEIPTS:
            raise DomainError(_("Sale lines typed with each receipt arrive in a later version."))
        if settings.sales_lines_confirmed_at is None:
            # Answering the "Get started" question counts even when the answer is the default.
            settings.sales_lines_confirmed_at = timezone.now()
            settings.save(update_fields=["sales_lines_confirmed_at", "updated_at"])
            _bump(company.pk, PULSE_SETUP)
    if "invoice_prefix" in fields:
        prefix = "".join(ch for ch in str(fields["invoice_prefix"] or "").upper() if ch.isalnum())
        if not prefix:
            raise DomainError(_("An invoice prefix has letters or digits, like INV."))
        fields["invoice_prefix"] = prefix[:8]
    if "invoice_footer" in fields:
        fields["invoice_footer"] = (fields["invoice_footer"] or "").strip()[:2000]
    if "rx_wholesale_max_markup_percent" in fields:
        try:
            markup = Decimal(str(fields["rx_wholesale_max_markup_percent"])).quantize(
                Decimal("0.01")
            )
        except InvalidOperation, ValueError:
            raise DomainError(_("The markup is a percentage from 0 to 100.")) from None
        if not 0 <= markup <= 100:
            raise DomainError(_("The markup is a percentage from 0 to 100."))
        fields["rx_wholesale_max_markup_percent"] = markup
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
    """Receipts mode: the shift's totals per method from its recorded receipts, the credit
    sales recorded with their customers on the credit (Nasiya) method."""
    found = cash.receipts_by_method(shift)
    methods = PaymentMethod.objects.filter(pk__in=found)
    lines = [
        PaymentLine(m, found[m.pk]["sales"], found[m.pk]["refunds"], found[m.pk]["receipts"])
        for m in methods
    ]
    credit = credit_total(shift)
    if credit:
        nasiya = (
            PaymentMethod.objects.filter(
                company_id=shift.company_id, kind=PaymentMethod.Kind.CREDIT
            )
            .order_by("-is_active", "order", "pk")
            .first()
        )
        if nasiya is not None:
            for index, line in enumerate(lines):
                if line.method.pk == nasiya.pk:
                    lines[index] = PaymentLine(
                        line.method, line.sales + credit, line.refunds, line.receipts
                    )
                    break
            else:
                lines.append(PaymentLine(nasiya, credit, ZERO, 0))
    return lines


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
        if receipts < 0 or receipts > MAX_COUNT * 10:
            raise DomainError(_("The number of receipts doesn't look right."))
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
    typed = payments is not None
    if payments is None:
        payments = receipt_lines(shift) if settings.mode == SalesSettings.Mode.RECEIPTS else []
    lines = _check_lines(company, payments)
    if typed:
        check_credit_total(shift, lines)
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
    pk = movement.pk
    transaction.on_commit(lambda: alerts.handover_answered(pk))
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
    transaction.on_commit(lambda: alerts.handover_answered(pk))
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
    if sale.is_imported:
        raise DomainError(
            _("Imported receipts come from the cash-register program: correct them there.")
        )
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


# Sale lines from the cash-register software (§14.7) -----------------------------------

PROFILE_FIELDS = (
    "name",
    "file_kind",
    "encoding",
    "delimiter",
    "header_row",
    "columns",
    "date_format",
    "default_unit",
    "branch",
    "branch_map",
    "is_active",
)
ENCODINGS = ("", "utf-8", "utf-8-sig", "cp1251", "cp866", "koi8-r", "utf-16")


def _profile_values(company, fields: dict, *, current: SalesImportProfile | None) -> dict:
    """Checked profile fields; the column map is checked against what an import needs."""
    if unknown := set(fields) - set(PROFILE_FIELDS):
        raise ValueError(f"Unknown import profile fields: {sorted(unknown)}")
    values = dict(fields)
    if "name" in values:
        name = (values["name"] or "").strip()[:80]
        if not name:
            raise DomainError(_("Give the profile a name, e.g. the cash-register program's."))
        clash = SalesImportProfile.objects.filter(company=company, name__iexact=name)
        if current is not None:
            clash = clash.exclude(pk=current.pk)
        if clash.exists():
            raise DomainError(_("There is already a profile called %(name)s.") % {"name": name})
        values["name"] = name
    if "file_kind" in values and values["file_kind"] not in SalesImportProfile.FileKind.values:
        raise DomainError(_("Pick CSV or Excel."))
    if "encoding" in values:
        values["encoding"] = (values["encoding"] or "").strip().lower()
        if values["encoding"] not in ENCODINGS:
            raise DomainError(_("Pick the file's encoding."))
    if "delimiter" in values:
        delimiter = values["delimiter"] or ""
        if delimiter in ("\\t", "tab"):
            delimiter = "\t"
        if len(delimiter) > 1:
            raise DomainError(_("The delimiter is one character, like ; or ,"))
        values["delimiter"] = delimiter
    if "header_row" in values:
        try:
            values["header_row"] = int(values["header_row"] or 1)
        except TypeError, ValueError:
            raise DomainError(_("The header row is a number.")) from None
        if not 1 <= values["header_row"] <= 50:
            raise DomainError(_("The header row is between 1 and 50."))
    if "date_format" in values:
        values["date_format"] = (values["date_format"] or "").strip()[:32]
        if values["date_format"] and "%" not in values["date_format"]:
            raise DomainError(_('A date format looks like "%d.%m.%Y %H:%M".'))
    if "default_unit" in values and values["default_unit"] not in SalesImportProfile.Unit.values:
        raise DomainError(_("Pick packs or parts."))
    if "branch" in values and values["branch"] is not None:
        _same_company(company, values["branch"])
    if "branch_map" in values:
        mapped = values["branch_map"] or {}
        if not isinstance(mapped, dict):
            raise DomainError(_("The branch map isn't readable."))
        known = set(Branch.objects.for_company(company).values_list("pk", flat=True))
        cleaned = {}
        for word, branch_id in mapped.items():
            word = str(word).strip()[:100]
            if not word:
                continue
            try:
                branch_id = int(branch_id)
            except TypeError, ValueError:
                raise DomainError(_("The branch map isn't readable.")) from None
            if branch_id not in known:
                raise DomainError(_("The branch map names a branch of another company."))
            cleaned[word] = branch_id
        values["branch_map"] = cleaned
    if "columns" in values:
        columns = values["columns"] or {}
        if not isinstance(columns, dict):
            raise DomainError(_("The column map isn't readable."))
        values["columns"] = {
            str(key): value if isinstance(value, int) else str(value).strip()[:100]
            for key, value in columns.items()
            if value not in (None, "")
        }
    branch = values.get("branch", current.branch if current else None)
    columns = values.get("columns", current.columns if current else {})
    importer.check_columns(columns, needs_branch=branch is None)
    return values


@transaction.atomic
def create_import_profile(company, *, by: Membership, name: str, **fields) -> SalesImportProfile:
    """How to read one cash-register program's export, saved once and reused every day."""
    _need_person(by)
    values = _profile_values(company, {"name": name, **fields}, current=None)
    profile = SalesImportProfile.objects.create(company=company, created_by=by, **values)
    _record(
        SalesAction.IMPORT_PROFILE_CREATED,
        company,
        by,
        profile,
        name=profile.name,
        file_kind=profile.file_kind,
        columns=profile.columns,
    )
    _bump(company.pk, PULSE_LINES)
    return profile


@transaction.atomic
def update_import_profile(
    profile: SalesImportProfile, *, by: Membership, **fields
) -> SalesImportProfile:
    _need_person(by)
    profile = SalesImportProfile.objects.select_for_update().get(pk=profile.pk)
    company = profile.company
    values = _profile_values(company, fields, current=profile)
    changes = {}
    for key, value in values.items():
        before = getattr(profile, key)
        if before != value:
            changes[key] = [
                before.pk if hasattr(before, "pk") else before,
                value.pk if hasattr(value, "pk") else value,
            ]
            setattr(profile, key, value)
    if changes:
        profile.save()
        _record(SalesAction.IMPORT_PROFILE_CHANGED, company, by, profile, changes=changes)
        _bump(company.pk, PULSE_LINES)
    return profile


@transaction.atomic
def start_import(profile: SalesImportProfile, *, by: Membership, file) -> SalesImport:
    """Take a file of sale lines and read it in the background. Nothing is read while the
    company's sale lines don't come from imports."""
    _need_person(by)
    company = profile.company
    _same_company(company, by)
    if not lines.lines_on(company):
        raise DomainError(_("Turn on imported sale lines in the sales settings first."))
    if not profile.is_active:
        raise DomainError(_("This profile is archived."))
    clean = accept_document(file, allowed=("csv", "xlsx"))
    kind = clean.name.rsplit(".", 1)[-1]
    if kind != profile.file_kind:
        raise DomainError(
            _("%(profile)s reads %(kind)s files.")
            % {"profile": profile.name, "kind": profile.get_file_kind_display()}
        )
    imp = SalesImport(company=company, profile=profile, created_by=by)
    imp.file.save(clean.name, clean, save=False)
    imp.save()
    _record(SalesAction.IMPORT_STARTED, company, by, imp, profile=profile.pk)
    pk = imp.pk
    transaction.on_commit(lambda: tasks.process_import.delay(pk))
    _bump(company.pk, PULSE_LINES)
    return imp


def match_code(company, *, by: Membership, code: str, product) -> int:
    """A code of the match list means `product`: remembered, and every waiting line settled.
    Each line commits on its own (a long list never holds the stock's locks for long)."""
    _need_person(by)
    return lines.match(company, code, product, by=by)


@transaction.atomic
def skip_code(company, *, by: Membership, code: str) -> int:
    """The waiting lines with `code` aren't goods the stock keeps (a bag, a service)."""
    _need_person(by)
    if not (code or "").strip():
        raise DomainError(_("Pick a code."))
    return lines.skip(company, code, by=by)


@transaction.atomic
def map_cashier(pos: PosCashier, *, by: Membership, membership: Membership | None) -> PosCashier:
    """The program's cashier code means this person (or nobody): their imported receipts
    follow, earlier ones included."""
    _need_person(by)
    pos = PosCashier.objects.select_for_update().get(pk=pos.pk)
    company = pos.company
    _same_company(company, membership)
    if membership is not None and membership.status != Membership.Status.APPROVED:
        raise DomainError(_("%(person)s isn't on the team now.") % {"person": membership})
    before = pos.membership_id
    if before == (membership.pk if membership else None):
        return pos
    pos.membership = membership
    pos.save(update_fields=["membership", "updated_at"])
    Sale.objects.imported().filter(company=company, pos_cashier=pos).update(
        cashier=membership, updated_at=timezone.now()
    )
    _record(
        SalesAction.CASHIER_MAPPED,
        company,
        by,
        pos,
        code=pos.code,
        before=before,
        membership=membership.pk if membership else None,
    )
    _bump(company.pk, PULSE_LINES)
    return pos


# Customers and nasiya (§11.4, §3.8) ------------------------------------------------------

# A customer's kind in pharmacy words, kept as a tag of its counterparty (§14.7).
CUSTOMER_KINDS = tuple(CustomerKind.values)
CUSTOMER_FIELDS = (
    "name",
    "phone",
    "kind",
    "credit_limit",
    "credit_blocked",
    "tin",
    "telegram_username",
    "contact_person",
    "address",
    "notes",
    "bank_details",
    "is_active",
)
CREDIT = "sales.creditentry"


def customer_kind(party) -> str:
    """The pharmacy word for a customer (its first kind tag), "person" by default."""
    tags = {str(tag).lower() for tag in (party.tags or [])}
    return next((kind for kind in CUSTOMER_KINDS if kind in tags), "person")


def _customer_values(party, fields: dict) -> dict:
    if unknown := set(fields) - set(CUSTOMER_FIELDS):
        raise ValueError(f"Unknown customer fields: {sorted(unknown)}")
    values = dict(fields)
    if "kind" in values:
        kind = values.pop("kind") or "person"
        if kind not in CUSTOMER_KINDS:
            raise DomainError(_("Pick what kind of customer this is."))
        others = [t for t in (party.tags if party else []) if str(t).lower() not in CUSTOMER_KINDS]
        values["tags"] = [kind, *others]
    return values


@transaction.atomic
def create_customer(company, *, by: Membership, name: str, **fields):
    """A customer in the one party directory (`finance.Counterparty`, kind customer): a regular
    who takes nasiya, a clinic, another pharmacy or a company. The phone is normalized
    (+998…) and unique in the company (finance's rules)."""
    from apps.finance import services as finance

    _need_person(by)
    values = _customer_values(None, {"kind": "person", **fields})
    return finance.create_counterparty(company, by=by, name=name, kind="customer", **values)


@transaction.atomic
def update_customer(party, *, by: Membership, **fields):
    from apps.finance import services as finance

    _need_person(by)
    values = _customer_values(party, fields)
    return finance.update_counterparty(party, by=by, **values)


def _customer_for_credit(company, customer):
    """The customer's row, fresh and locked: two credit sales to one customer at once wait for
    each other, so both can't pass the credit limit."""
    from apps.finance.models import Counterparty

    _same_company(company, customer)
    customer = Counterparty.objects.select_for_update().get(pk=customer.pk)
    if customer.kind not in (Counterparty.Kind.CUSTOMER, Counterparty.Kind.BOTH):
        raise DomainError(_("%(name)s isn't a customer.") % {"name": customer})
    if not customer.is_active:
        raise DomainError(_("%(name)s is archived.") % {"name": customer})
    return customer


def open_receivables(customer, *, currency: str):
    """The customer's open receivables in `currency`, oldest first (the order payments settle
    them in)."""
    from apps.finance.models import Debt

    return Debt.objects.filter(
        company_id=customer.company_id,
        counterparty=customer,
        direction=Debt.Direction.RECEIVABLE,
        status=Debt.Status.OPEN,
        currency=currency,
    ).order_by("issued_on", "pk")


def owed(customer, *, currency: str) -> Decimal:
    """What the customer still owes in `currency`."""
    total = ZERO
    for amount, paid in open_receivables(customer, currency=currency).values_list("amount", "paid"):
        total += amount - paid
    return total


@transaction.atomic
def record_credit(
    *,
    by: Membership,
    kind: str,
    customer,
    amount,
    method: PaymentMethod | None = None,
    note: str = "",
):
    """Nasiya on `by`'s open shift: a credit sale opens one receivable (its income booked now,
    due after `SalesSettings.credit_days`); a payment settles the customer's oldest receivables
    first, cash into the till (it counts in the till's expected cash)."""
    from datetime import timedelta

    from apps.finance import services as finance
    from apps.finance.sources import Source
    from apps.sales.models import CreditEntry

    _need_person(by)
    company = by.company
    if kind not in CreditEntry.Kind.values:
        raise DomainError(_("Pick a credit sale or a payment."))
    amount = money(amount)
    # The shift first, then the customer (a finance row): the one lock order of this module.
    shift = (
        CashShift.objects.select_for_update(of=("self",))
        .select_related("branch__manager", "register__cash_account")
        .filter(cashier=by, status=Status.OPEN)
        .first()
    )
    if shift is None:
        raise DomainError(_("Open a shift first."))
    customer = _customer_for_credit(company, customer)
    currency = company.base_currency
    left = owed(customer, currency=currency)
    if kind == CreditEntry.Kind.SALE:
        if customer.credit_blocked:
            raise DomainError(_("%(name)s may not take nasiya now.") % {"name": customer})
        if customer.credit_limit is not None and left + amount > customer.credit_limit:
            raise DomainError(
                _("That goes over %(name)s's limit: %(left)s owed of %(limit)s.")
                % {
                    "name": customer,
                    "left": msg_money(left, currency),
                    "limit": msg_money(customer.credit_limit, currency),
                }
            )
        method = None
    else:
        if left <= 0:
            raise DomainError(_("%(name)s owes nothing.") % {"name": customer})
        if amount > left:
            raise DomainError(
                _("That's more than the %(left)s %(name)s owes.")
                % {"left": msg_money(left, currency), "name": customer}
            )
        if method is None:
            method = (
                PaymentMethod.objects.filter(
                    company=company, kind=PaymentMethod.Kind.CASH, is_active=True
                )
                .order_by("order", "pk")
                .first()
            )
        if method is None or method.company_id != company.pk or not method.is_active:
            raise DomainError(_("Pick how the customer paid."))
        if method.is_credit:
            raise DomainError(_("Nasiya can't be paid back with nasiya."))
    entry = CreditEntry.objects.create(
        company=company,
        kind=kind,
        customer=customer,
        branch=shift.branch,
        shift=shift,
        register=shift.register,
        method=method,
        amount=amount,
        business_day=shift.business_day,
        note=(note or "").strip()[:300],
        created_by=by,
    )
    label = _("Nasiya, %(shift)s") % {"shift": shift.code}
    if kind == CreditEntry.Kind.SALE:
        terms = get_settings(company).credit_days
        entry.debt = finance.open_debt(
            company,
            by=by,
            direction="receivable",
            kind="trade",
            amount=amount,
            currency=currency,
            issued_on=shift.business_day,
            counterparty=customer,
            due_on=shift.business_day + timedelta(days=terms),
            category="sales",
            branch=shift.branch,
            description=(entry.note or label)[:300],
            responsible=shift.branch.manager or by,
            source=Source(CREDIT, entry.pk),
        )
        entry.save(update_fields=["debt", "updated_at"])
    else:
        account = finance_bridge.payment_account(shift.register, method)
        rest = amount
        for debt in open_receivables(customer, currency=currency):
            if rest <= 0:
                break
            part = min(rest, debt.amount - debt.paid)
            if part <= 0:
                continue
            finance.pay_debt(
                debt,
                by=by,
                amount=part,
                paid_on=shift.business_day,
                account=account,
                source=Source(CREDIT, entry.pk, f"d{debt.pk}"),
            )
            rest -= part
    _record(
        SalesAction.CREDIT_RECORDED,
        company,
        by,
        entry,
        kind=kind,
        customer=customer.pk,
        amount=amount,
        shift=shift.pk,
    )
    _bump(company.pk, PULSE_CUSTOMERS, PULSE_SHIFTS, PULSE_CASH)
    return entry


@transaction.atomic
def void_credit(entry, *, by: Membership, reason: str):
    """Cancel a nasiya entry typed by mistake, while its shift is open: a credit sale's
    receivable is cancelled (refused once anything was paid on it), a payment's rows are voided
    and the receivables it settled are owed again."""
    from apps.finance import services as finance
    from apps.finance.models import LIVE_STATUSES, Transaction
    from apps.sales.models import CreditEntry

    _need_person(by)
    reason = _reason(reason)
    entry = (
        CreditEntry.objects.select_for_update(of=("self",))
        .select_related("shift", "debt", "company")
        .get(pk=entry.pk)
    )
    if entry.voided_at is not None:
        raise DomainError(_("This entry is already void."))
    if entry.shift_id and entry.shift.status != Status.OPEN:
        raise DomainError(
            _("This entry is part of the closed shift %(shift)s.") % {"shift": entry.shift.code}
        )
    if entry.kind == CreditEntry.Kind.SALE and entry.debt_id:
        if entry.debt.paid:
            raise DomainError(_("Part of this nasiya was already paid back."))
        finance.cancel_debt(entry.debt, by=by, reason=reason)
    else:
        for row in Transaction.objects.filter(
            company_id=entry.company_id,
            source_type=CREDIT,
            source_id=entry.pk,
            status__in=LIVE_STATUSES,
        ).order_by("-pk"):
            finance.void_transaction(row, by=by, reason=reason)
    entry.voided_at = timezone.now()
    entry.voided_by = by.user
    entry.void_reason = reason
    entry.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    _record(SalesAction.CREDIT_VOIDED, entry.company, by, entry, reason=reason)
    _bump(entry.company_id, PULSE_CUSTOMERS, PULSE_SHIFTS, PULSE_CASH)
    return entry


def credit_total(shift: CashShift) -> Decimal:
    """The credit sales recorded in a shift (what its Nasiya total must equal)."""
    from django.db.models import Sum

    from apps.sales.models import CreditEntry

    return (
        CreditEntry.objects.filter(
            shift=shift, kind=CreditEntry.Kind.SALE, voided_at__isnull=True
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )


def check_credit_total(shift: CashShift, lines: list[PaymentLine]) -> None:
    """At close: the Nasiya the Z-report shows must be the credit sales recorded in the shift,
    once the company records nasiya at all (until then nothing changes)."""
    from apps.sales.models import CreditEntry

    if not CreditEntry.objects.filter(company_id=shift.company_id).exists():
        return
    typed = sum((line.sales for line in lines if line.method.is_credit), ZERO)
    recorded = credit_total(shift)
    if typed != recorded:
        currency = shift.company.base_currency
        raise DomainError(
            _(
                "Nasiya on the Z-report is %(typed)s, but %(recorded)s was recorded as credit "
                "sales in this shift (a gap of %(gap)s). Record the missing credit sales with "
                "their customers, or correct the total."
            )
            % {
                "typed": msg_money(typed, currency),
                "recorded": msg_money(recorded, currency),
                "gap": msg_money(abs(typed - recorded), currency),
            }
        )


# Invoices (§3.8, §14.7) -------------------------------------------------------------------

INVOICE = "sales.invoice"
INVOICE_PULSE = "sales.invoices"
QUANTITY_STEP = Decimal("0.001")


def _invoice_customer(company, counterparty):
    from apps.finance.models import Counterparty

    _same_company(company, counterparty)
    if counterparty is None:
        raise DomainError(_("Pick the customer."))
    if counterparty.kind not in (Counterparty.Kind.CUSTOMER, Counterparty.Kind.BOTH):
        raise DomainError(_("%(name)s isn't a customer.") % {"name": counterparty})
    return counterparty


def _invoice_lines(company, lines) -> list[dict]:
    """Draft lines: [{"product_id"?, "name", "quantity", "price", "discount"?}], quantities in
    packs, checked and with their totals."""
    from apps.inventory.models import Product

    if not lines:
        raise DomainError(_("Add at least one line."))
    if len(lines) > 300:
        raise DomainError(_("An invoice holds at most 300 lines."))
    product_ids = {int(row["product_id"]) for row in lines if row.get("product_id")}
    products = Product.objects.for_company(company).in_bulk(product_ids)
    if len(products) != len(product_ids):
        raise DomainError(_("Pick medicines of this company's catalogue."))
    cleaned = []
    for number, row in enumerate(lines, start=1):
        product = products.get(int(row["product_id"])) if row.get("product_id") else None
        name = (row.get("name") or (product.name if product else "")).strip()[:200]
        if not name:
            raise DomainError(_("Line %(n)s needs a name.") % {"n": number})
        try:
            quantity = Decimal(str(row.get("quantity"))).quantize(QUANTITY_STEP)
        except InvalidOperation, ValueError, TypeError:
            raise DomainError(_("Line %(n)s needs a quantity.") % {"n": number}) from None
        if quantity <= 0 or quantity > 1_000_000:
            raise DomainError(_("Line %(n)s needs a quantity.") % {"n": number})
        price = money(
            row.get("price") if row.get("price") not in (None, "") else 0, allow_zero=True
        )
        discount = money(row.get("discount") or 0, allow_zero=True)
        gross = quantize(quantity * price)
        if discount > gross:
            raise DomainError(_("Line %(n)s has a discount above its amount.") % {"n": number})
        cleaned.append(
            {
                "line_number": number,
                "product": product,
                "name": name,
                "quantity": quantity,
                "price": price,
                "discount": discount,
                "total": gross - discount,
            }
        )
    return cleaned


def _write_invoice_lines(invoice, cleaned: list[dict]) -> None:
    from apps.sales.models import InvoiceLine

    invoice.lines.all().delete()
    InvoiceLine.objects.bulk_create(InvoiceLine(invoice=invoice, **row) for row in cleaned)
    invoice.subtotal = sum((quantize(row["quantity"] * row["price"]) for row in cleaned), ZERO)
    invoice.discount = sum((row["discount"] for row in cleaned), ZERO)
    invoice.total = invoice.subtotal - invoice.discount


def _invoice_currency(company, currency: str) -> str:
    from apps.core.money import Currency

    currency = (currency or company.base_currency).upper()
    if currency not in Currency.values:
        raise DomainError(_("Pick the invoice's currency."))
    return currency


@transaction.atomic
def create_invoice(
    company,
    *,
    by: Membership,
    counterparty,
    lines,
    branch=None,
    currency="UZS",
    notes="",
):
    """A draft invoice to `counterparty` (a customer: a clinic, a pharmacy, a company). `lines`
    are `[{"product_id"?, "name", "quantity", "price", "discount"?}]`, quantities in packs. The
    fixed signature the CRM package calls (§14.13); nothing moves until it is issued."""
    from apps.sales.models import Invoice

    _need_person(by)
    _same_company(company, branch)
    counterparty = _invoice_customer(company, counterparty)
    cleaned = _invoice_lines(company, lines)
    invoice = Invoice.objects.create(
        company=company,
        counterparty=counterparty,
        branch=branch,
        currency=_invoice_currency(company, currency),
        notes=(notes or "").strip()[:4000],
        created_by=by,
    )
    _write_invoice_lines(invoice, cleaned)
    invoice.save(update_fields=["subtotal", "discount", "total", "updated_at"])
    _record(
        SalesAction.INVOICE_CREATED,
        company,
        by,
        invoice,
        counterparty=counterparty.pk,
        total=invoice.total,
        currency=invoice.currency,
        lines=len(cleaned),
    )
    _bump(company.pk, INVOICE_PULSE, PULSE_CUSTOMERS)
    return invoice


def _lock_invoice(invoice):
    from apps.sales.models import Invoice

    return (
        Invoice.objects.select_for_update(of=("self",))
        .select_related("company", "branch", "counterparty", "debt")
        .get(pk=invoice.pk)
    )


@transaction.atomic
def update_invoice(invoice, *, by: Membership, **fields):
    """Change a draft: customer, branch, currency, notes, lines. The e-invoice id may be typed at
    any time."""
    _need_person(by)
    invoice = _lock_invoice(invoice)
    company = invoice.company
    allowed = {"counterparty", "lines", "branch", "currency", "notes", "e_invoice_ref"}
    if unknown := set(fields) - allowed:
        raise ValueError(f"Unknown invoice fields: {sorted(unknown)}")
    if set(fields) - {"e_invoice_ref"} and not invoice.is_draft:
        raise DomainError(_("Only a draft can be changed."))
    changes = {}
    if "counterparty" in fields:
        invoice.counterparty = _invoice_customer(company, fields["counterparty"])
        changes["counterparty"] = invoice.counterparty.pk
    if "branch" in fields:
        _same_company(company, fields["branch"])
        invoice.branch = fields["branch"]
        changes["branch"] = invoice.branch.pk if invoice.branch else None
    if "currency" in fields:
        invoice.currency = _invoice_currency(company, fields["currency"])
        changes["currency"] = invoice.currency
    if "notes" in fields:
        invoice.notes = (fields["notes"] or "").strip()[:4000]
        changes["notes"] = invoice.notes
    if "e_invoice_ref" in fields:
        invoice.e_invoice_ref = (fields["e_invoice_ref"] or "").strip()[:64]
        changes["e_invoice_ref"] = invoice.e_invoice_ref
    if "lines" in fields:
        _write_invoice_lines(invoice, _invoice_lines(company, fields["lines"]))
        changes["lines"] = invoice.lines.count()
        changes["total"] = invoice.total
    invoice.save()
    if changes:
        _record(SalesAction.INVOICE_CHANGED, company, by, invoice, changes=changes)
        _bump(company.pk, INVOICE_PULSE)
    return invoice


def _wholesale_cap(product, batch, markup: Decimal):
    """The most a prescription medicine may cost a pack by invoice: its batch cost plus the
    wholesale markup cap, never above its reference price (None when neither is known)."""
    if not product.rx_required:
        return None
    caps = []
    if batch is not None:
        caps.append(quantize(batch.unit_cost * (1 + markup / 100)))
    if product.reference_price is not None:
        caps.append(product.reference_price)
    return min(caps) if caps else None


@transaction.atomic
def issue_invoice(invoice, *, by: Membership, issued_on: date | None = None):
    """Issue a draft: its number (under the settings row's lock, so numbers never repeat), the
    stock of its medicines (FEFO; one row per batch with series and expiry), one receivable with
    its income booked now, due after the invoice terms. A prescription medicine priced above the
    wholesale cap warns; nothing else is refused but a missing pharmacy for stock lines."""
    from datetime import timedelta

    from apps.finance import services as finance
    from apps.finance.sources import Source
    from apps.inventory import services as stock
    from apps.inventory.models import StockBatch
    from apps.sales import integrations
    from apps.sales.models import Invoice, InvoiceLine

    _need_person(by)
    company = Invoice.objects.select_related("company").get(pk=invoice.pk).company
    # The settings row first (the one lock order), then the invoice.
    settings = SalesSettings.objects.select_for_update().get(pk=get_settings(company).pk)
    invoice = _lock_invoice(invoice)
    if not invoice.is_draft:
        raise DomainError(_("This invoice is already issued."))
    lines = list(invoice.lines.select_related("product").order_by("line_number", "pk"))
    if not lines or invoice.total <= 0:
        raise DomainError(_("Add lines with a price before issuing."))
    stocked = [line for line in lines if line.product_id and line.product.track_stock]
    if stocked and invoice.branch_id is None:
        raise DomainError(_("Pick the warehouse or pharmacy the goods leave from."))
    issued_on = issued_on or business_day(company, ends_at=settings.business_day_ends_at)
    number = settings.next_invoice_number
    SalesSettings.objects.filter(pk=settings.pk).update(
        next_invoice_number=F("next_invoice_number") + 1
    )
    code = (invoice.branch.code if invoice.branch_id else "") or "S"
    invoice.number = f"{settings.invoice_prefix or 'INV'}-{code.upper()}-{number:04d}"[:24]
    vat = integrations.vat_percent(company)
    markup = settings.rx_wholesale_max_markup_percent
    warnings = []
    for line in lines:
        product = line.product
        line.vat_percent = (
            product.vat_percent if product is not None and product.vat_percent is not None else vat
        )
        line.mxik_code = product.mxik_code if product is not None else ""
        if not (product is not None and product.track_stock):
            line.save()
            continue
        per_pack = max(int(product.units_per_pack or 1), 1)
        parts = (line.quantity * per_pack).quantize(QUANTITY_STEP)
        found = stock.deduct(
            invoice.branch,
            product,
            parts,
            by=by,
            document=(INVOICE, invoice.pk),
            kind="sale",
        )
        allocations = [a for a in found if a.quantity and a.quantity > 0] or []
        covered = sum((a.quantity for a in allocations), ZERO)
        if covered < parts:
            from apps.inventory.services import Allocation

            allocations.append(Allocation(None, parts - covered, None))
        batches = StockBatch.objects.in_bulk([a.batch_id for a in allocations if a.batch_id])
        left_total, left_discount = line.total, line.discount
        for index, allocation in enumerate(allocations):
            last = index == len(allocations) - 1
            share = allocation.quantity / parts
            row = line if index == 0 else InvoiceLine(invoice=invoice, line_number=line.line_number)
            batch = batches.get(allocation.batch_id)
            row.product, row.name, row.unit, row.price = product, line.name, line.unit, line.price
            row.vat_percent, row.mxik_code = line.vat_percent, line.mxik_code
            row.quantity = (allocation.quantity / per_pack).quantize(QUANTITY_STEP)
            row.total = left_total if last else quantize(line.total * share)
            row.discount = left_discount if last else quantize(line.discount * share)
            left_total -= row.total
            left_discount -= row.discount
            row.batch = batch
            row.series = batch.series if batch else ""
            row.expires_on = batch.expires_on if batch else None
            row.cost = (
                quantize(allocation.unit_cost * allocation.quantity)
                if allocation.unit_cost is not None
                else None
            )
            row.save()
            cap = _wholesale_cap(product, batch, markup)
            pack = quantize(row.total / row.quantity) if row.quantity else ZERO
            if cap is not None and pack > cap:
                warnings.append(
                    {
                        "line": line.line_number,
                        "product": product.name,
                        "price": str(pack),
                        "cap": str(cap),
                    }
                )
    invoice.issued_on = issued_on
    invoice.due_on = issued_on + timedelta(days=settings.invoice_terms_days)
    invoice.warnings = warnings
    invoice.status = Invoice.Status.ISSUED
    invoice.save()
    invoice.debt = finance.open_debt(
        company,
        by=by,
        direction="receivable",
        kind="trade",
        amount=invoice.total,
        currency=invoice.currency,
        issued_on=issued_on,
        counterparty=invoice.counterparty,
        due_on=invoice.due_on,
        category="sales",
        branch=invoice.branch,
        description=(_("Invoice %(number)s") % {"number": invoice.number})[:300],
        responsible=by,
        source=Source(INVOICE, invoice.pk, "issue"),
    )
    invoice.save(update_fields=["debt", "updated_at"])
    _record(
        SalesAction.INVOICE_ISSUED,
        company,
        by,
        invoice,
        number=invoice.number,
        total=invoice.total,
        currency=invoice.currency,
        warnings=warnings,
    )
    _bump(company.pk, INVOICE_PULSE, PULSE_CUSTOMERS)
    return invoice


@transaction.atomic
def record_invoice_payment(
    invoice, *, by: Membership, account, amount, paid_on: date, debt_amount=None
):
    """A payment on an issued invoice (part of it, or in another currency: `amount` is in the
    account's currency, `debt_amount` what it settles when that differs)."""
    from apps.finance import services as finance
    from apps.sales.models import Invoice

    _need_person(by)
    invoice = _lock_invoice(invoice)
    if invoice.status not in (Invoice.Status.ISSUED, Invoice.Status.PARTLY_PAID):
        raise DomainError(_("Only an issued invoice takes payments."))
    _same_company(invoice.company, account)
    finance.pay_debt(
        invoice.debt,
        by=by,
        amount=amount,
        paid_on=paid_on,
        account=account,
        debt_amount=debt_amount,
    )
    invoice.debt.refresh_from_db()
    invoice.status = (
        Invoice.Status.PAID if invoice.debt.status == "paid" else Invoice.Status.PARTLY_PAID
    )
    invoice.save(update_fields=["status", "updated_at"])
    _record(
        SalesAction.INVOICE_PAID,
        invoice.company,
        by,
        invoice,
        amount=str(amount),
        account=account.pk,
        paid_on=paid_on,
    )
    _bump(invoice.company_id, INVOICE_PULSE, PULSE_CUSTOMERS)
    return invoice


@transaction.atomic
def void_invoice(invoice, *, by: Membership, reason: str):
    """Void a draft, or an issued invoice nobody paid anything on yet: its receivable is
    cancelled and its goods go back on sale (they never left)."""
    from apps.finance import services as finance
    from apps.inventory import services as stock
    from apps.inventory.services import Allocation
    from apps.sales.models import Invoice

    _need_person(by)
    reason = _reason(reason)
    invoice = _lock_invoice(invoice)
    if invoice.status == Invoice.Status.VOID:
        raise DomainError(_("This invoice is already void."))
    if invoice.status in (Invoice.Status.PARTLY_PAID, Invoice.Status.PAID) or (
        invoice.debt_id and invoice.debt.paid
    ):
        raise DomainError(_("A payment was made on this invoice: it can't be voided."))
    if invoice.status == Invoice.Status.ISSUED:
        if invoice.debt_id:
            finance.cancel_debt(invoice.debt, by=by, reason=reason)
        by_line: dict[int, list] = defaultdict(list)
        for row in invoice.lines.select_related("product").order_by("line_number", "pk"):
            if row.product_id and row.product.track_stock:
                per_pack = max(int(row.product.units_per_pack or 1), 1)
                parts = (row.quantity * per_pack).quantize(QUANTITY_STEP)
                unit_cost = (row.cost / parts).quantize(Decimal("0.01")) if row.cost else None
                by_line[row.line_number].append(Allocation(row.batch_id, parts, unit_cost))
        for allocations in by_line.values():
            stock.restock(
                invoice.branch,
                allocations,
                by=by,
                document=(INVOICE, invoice.pk),
                kind="refund",
                status="sellable",
            )
    invoice.status = Invoice.Status.VOID
    invoice.voided_at = timezone.now()
    invoice.voided_by = by.user
    invoice.void_reason = reason
    invoice.save(update_fields=["status", "voided_at", "voided_by", "void_reason", "updated_at"])
    _record(SalesAction.INVOICE_VOIDED, invoice.company, by, invoice, reason=reason)
    _bump(invoice.company_id, INVOICE_PULSE, PULSE_CUSTOMERS)
    return invoice


def invoice_pdf(invoice, *, language: str) -> bytes:
    """The invoice as a PDF: the company and the customer, each line with its MXIK code, VAT,
    series and expiry, and the footer saying it isn't the electronic invoice (EHF)."""
    from apps.core.pdf import render_pdf
    from apps.sales.invoice_print import context

    return render_pdf("sales/invoice.html", context(invoice), language=language)


@transaction.atomic
def send_invoice(invoice, *, by: Membership) -> dict:
    """Send an issued invoice: its PDF to the customer's Telegram when they started the bot
    (their username is on the customer card), else a link for the owner to pass on (valid 7
    days). Returns {"delivered": "telegram"} or {"delivered": "link", "url": …}."""
    from django.core.files.base import ContentFile

    from apps.accounts.models import User
    from apps.core.files import MAX_TTL, signed_url
    from apps.sales.models import Invoice

    _need_person(by)
    invoice = _lock_invoice(invoice)
    if invoice.status in (Invoice.Status.DRAFT, Invoice.Status.VOID):
        raise DomainError(_("Issue the invoice before sending it."))
    company = invoice.company
    data = invoice_pdf(invoice, language=company.default_language)
    invoice.pdf.save(f"{invoice.number or invoice.pk}.pdf", ContentFile(data), save=False)
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=["pdf", "sent_at", "updated_at"])
    username = (invoice.counterparty.telegram_username or "").strip().lstrip("@")
    person = (
        User.objects.filter(telegram_username__iexact=username, telegram_id__isnull=False).first()
        if username
        else None
    )
    if person is not None:
        path, chat, name = invoice.pdf.name, person.telegram_id, f"{invoice.number}.pdf"
        caption = _("Invoice %(number)s from %(company)s") % {
            "number": invoice.number,
            "company": company.name,
        }

        def deliver():
            from apps.notifications.telegram import send_document

            send_document("employee", chat, path, storage="private", caption=caption, filename=name)

        transaction.on_commit(deliver)
        result = {"delivered": "telegram"}
    else:
        url = signed_url(
            invoice.pdf,
            user=by.user,
            company_id=company.pk,
            check=f"sales.invoice_pdf:{invoice.pk}",
            ttl=MAX_TTL,
            filename=f"{invoice.number}.pdf",
        )
        result = {"delivered": "link", "url": url}
    _record(SalesAction.INVOICE_SENT, company, by, invoice, delivered=result["delivered"])
    _bump(company.pk, INVOICE_PULSE)
    return result
