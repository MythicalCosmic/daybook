"""Business logic of payroll: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), checks that `by` may do it
(`_require`), audits its changes with `apps.audit.services.record` (rows that show someone's
pay need `payroll.view`) and bumps the module's pulse keys after commit. Money is Decimal end
to end; amounts come in positive and a kind says the direction.

Contracts other apps call (docs/PLAN-OWNER.md §13.4), with fixed signatures:

    propose_fine(membership, *, by, amount, reason, source)            -> Adjustment
    propose_pay_change(membership, *, by, setup: dict, effective_on, reason) -> Compensation

The monthly run itself (calculate, finalize, reopen, cancel, publish, mark paid) lives in
`apps.payroll.runs`, the arithmetic in `calculator.py`, the ledger in `finance_bridge.py`;
they are re-exported here.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.companies.models import Company
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.money import Currency, quantize
from apps.finance import services as finance
from apps.finance.models import MoneyAccount
from apps.finance.sources import Source
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.payroll import conf, notify, periods, queries
from apps.payroll.audit_actions import PayrollAction
from apps.payroll.models import (
    Adjustment,
    AdjustmentRule,
    Advance,
    AdvanceRepayment,
    Compensation,
    PayoutMethod,
    PayrollRun,
    PayrollSettings,
    PayType,
    TaskRate,
)
from apps.payroll.runs import (
    calculate_run,
    cancel_run,
    confirm_received,
    create_run,
    finalize_run,
    mark_paid,
    mark_viewed,
    publish,
    reopen_run,
    set_manual_lines,
)

# Pulse keys (registered in hooks.py).
PULSE_PENDING = "payroll.pending"
PULSE_ADVANCES = "payroll.advances"
PULSE_ADJUSTMENTS = "payroll.adjustments"
PULSE_PAY = "payroll.pay"
PULSE_RUNS = "payroll.runs"
PULSE_RULES = "payroll.rules"
PULSE_SETTINGS = "payroll.settings"

ADVANCE_SOURCE = "payroll.advance"
MAX_AMOUNT = Decimal("9999999999999999.99")
MAX_BULK = 200
# People who can be paid: still working, or paused.
PAYABLE_STATUSES = (Membership.Status.APPROVED, Membership.Status.SUSPENDED)

AdjustmentStatus = Adjustment.Status
AdvanceStatus = Advance.Status


# Helpers --------------------------------------------------------------------------------


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _audit(by: Membership | None, action: str, target, *, company_id: int, **details) -> None:
    """An audit row only `payroll.view` holders read (it shows someone's pay)."""
    audit.record(
        action,
        company_id=company_id,
        actor=by.user if by is not None else None,
        target=target,
        required_perm=Perm.PAYROLL_VIEW,
        **details,
    )


def _require(by: Membership | None, *perms: Perm) -> None:
    """`by` holds one of `perms`; the system (`by=None`) may do anything."""
    if by is None:
        return
    if not any(by.has_perm(perm) for perm in perms):
        raise PermissionDenied(_("You don't have permission to do this."))


def _same_company(company: Company, *objects) -> None:
    for obj in objects:
        if obj is not None and getattr(obj, "company_id", company.pk) != company.pk:
            raise DomainError(_("That doesn't belong to this company."))


def _amount(value, *, allow_zero: bool = False) -> Decimal:
    """A positive amount of money from a caller, in whole tiyin."""
    if isinstance(value, bool):
        raise DomainError(_("Enter an amount of money."))
    try:
        amount = quantize(Decimal(str(value) if isinstance(value, float) else value))
    except InvalidOperation, TypeError, ValueError:
        raise DomainError(_("Enter an amount of money.")) from None
    if not amount.is_finite() or amount > MAX_AMOUNT:
        raise DomainError(_("This amount is too large."))
    if amount < 0:
        raise DomainError(_("Enter the amount without a minus sign."))
    if amount == 0 and not allow_zero:
        raise DomainError(_("The amount can't be zero."))
    return amount


def _text(value, *, required: bool, limit: int, message: str = "") -> str:
    text = (value or "").strip()[:limit]
    if required and not text:
        raise DomainError(message or _("Say why."))
    return text


def _clean(instance) -> None:
    try:
        instance.full_clean(exclude=["company"], validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        first = next(iter(exc.message_dict.values()))[0] if hasattr(exc, "message_dict") else exc
        raise DomainError(str(first)) from exc


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "pk"):
        return value.pk
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _changes(before: dict, after: dict) -> dict:
    return {
        key: [_plain(before.get(key)), _plain(value)]
        for key, value in after.items()
        if before.get(key) != value
    }


def _check_member(company: Company, membership: Membership) -> None:
    _same_company(company, membership)
    if membership.status not in PAYABLE_STATUSES:
        raise DomainError(_("%(name)s doesn't work here any more.") % {"name": membership})


def _check_period_open(company: Company, period: date) -> None:
    """Nothing changes in a month whose regular run is finalized (reopen it first)."""
    run = (
        PayrollRun.objects.for_company(company)
        .filter(
            kind=PayrollRun.Kind.REGULAR,
            period=periods.first_day(period),
            status__in=(PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID),
        )
        .first()
    )
    if run is not None:
        raise DomainError(
            _("The payroll for %(month)s is finalized. Reopen it first.")
            % {"month": queries.month_label(run.period)}
        )


def _period(company: Company, value) -> date:
    if value in (None, ""):
        return periods.first_day(periods.today(company))
    return periods.parse_period(value)


def _currency(company: Company, value) -> str:
    currency = value or conf.get_settings(company).currency
    if currency not in Currency.values:
        raise DomainError(_("Pick a currency."))
    return currency


# Settings -------------------------------------------------------------------------------

SETTINGS_FIELDS = (
    "currency",
    "pay_day",
    "advance_day",
    "advance_cap_percent",
    "amounts_are_net",
    "taxes_enabled",
    "income_tax_percent",
    "social_tax_percent",
    "inps_percent",
    "deductions_cap_percent",
    "rounding_step",
    "overtime_multiplier",
    "holiday_work_multiplier",
    "night_multiplier",
    "night_starts_at",
    "night_ends_at",
    "daily_hours",
    "auto_prepare",
    "leave_payout_months",
)


def update_settings(company: Company, *, by: Membership | None, **changes) -> PayrollSettings:
    """Change the company's payroll rules. Changing the currency is refused once a run used it.
    A change reaches draft runs the next time they are calculated."""
    _require(by, Perm.PAYROLL_MANAGE)
    if unknown := set(changes) - set(SETTINGS_FIELDS):
        raise DomainError(_("Unknown setting: %(name)s") % {"name": ", ".join(sorted(unknown))})
    with transaction.atomic():
        row = PayrollSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        if (
            "currency" in changes
            and changes["currency"] != row.currency
            and PayrollRun.objects.for_company(company).exists()
        ):
            raise DomainError(_("The payroll currency can't change once a run was made."))
        before = {name: getattr(row, name) for name in changes}
        for name, value in changes.items():
            setattr(row, name, value)
        if row.night_starts_at == row.night_ends_at:
            raise DomainError(_("The night starts and ends at different times."))
        _clean(row)
        row.save()
        if changed := _changes(before, changes):
            audit.record(
                PayrollAction.SETTINGS_CHANGED,
                company_id=company.pk,
                actor=by.user if by is not None else None,
                target=row,
                required_perm=Perm.PAYROLL_MANAGE,
                changes=changed,
            )
            _bump(company.pk, PULSE_SETTINGS)
    return row


# Pay setups -----------------------------------------------------------------------------

PAY_FIELDS = (
    "effective_from",
    "pay_type",
    "amount",
    "currency",
    "proration",
    "pays_task_rates",
    "overtime_eligible",
    "note",
)


def _locked_until(membership: Membership) -> date | None:
    """The last day of the latest finalized month this person was paid in: pay setups can only
    start after it."""
    period = (
        PayrollRun.objects.filter(
            company_id=membership.company_id,
            status__in=(PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID),
            payslips__membership=membership,
        )
        .order_by("-period")
        .values_list("period", flat=True)
        .first()
    )
    return periods.last_day(period) if period else None


def _check_pay_fields(company: Company, fields: dict) -> dict:
    clean = dict(fields)
    if "pay_type" in clean and clean["pay_type"] not in PayType.values:
        raise DomainError(_("Pick how the pay is counted."))
    if "proration" in clean and clean["proration"] not in Compensation.Proration.values:
        raise DomainError(_("Pick how missed days are counted."))
    if "amount" in clean:
        per_task = clean.get("pay_type") == PayType.PER_TASK
        clean["amount"] = _amount(clean["amount"], allow_zero=per_task)
    if "currency" in clean:
        clean["currency"] = _currency(company, clean["currency"])
    if "note" in clean:
        clean["note"] = _text(clean["note"], required=False, limit=300)
    for flag in ("pays_task_rates", "overtime_eligible"):
        if flag in clean:
            clean[flag] = bool(clean[flag])
    return clean


def _check_start(membership: Membership, effective_from: date) -> None:
    if not isinstance(effective_from, date):
        raise DomainError(_("Pick the day the pay starts."))
    locked_until = _locked_until(membership)
    if locked_until is not None and effective_from <= locked_until:
        raise DomainError(
            _("Pay up to %(date)s is already finalized: pick a later day.")
            % {"date": locked_until.strftime("%d.%m.%Y")}
        )


def _pay_details(row: Compensation) -> dict:
    return {
        "compensation": row.pk,
        "effective_from": row.effective_from.isoformat(),
        "pay_type": row.pay_type,
        "amount": str(row.amount),
        "currency": row.currency,
        "proration": row.proration,
    }


@transaction.atomic
def set_pay(membership: Membership, *, by: Membership | None, **fields) -> Compensation:
    """A new pay setup for `membership` from `effective_from` (a raise, a new pay type…).
    Days before it keep the earlier setup; a month already finalized can't change."""
    _require(by, Perm.PAYROLL_MANAGE)
    company = membership.company
    _check_member(company, membership)
    if unknown := set(fields) - set(PAY_FIELDS):
        raise DomainError(_("Unknown field: %(name)s") % {"name": ", ".join(sorted(unknown))})
    fields.setdefault("pay_type", PayType.MONTHLY)
    if "amount" not in fields:
        raise DomainError(_("Enter an amount of money."))
    fields = _check_pay_fields(company, fields)
    effective_from = fields.pop("effective_from", None)
    _check_start(membership, effective_from)
    fields.setdefault("currency", conf.get_settings(company).currency)
    if Compensation.objects.filter(membership=membership, effective_from=effective_from).exists():
        raise DomainError(_("There is already a pay setup from that day: change that one."))
    row = Compensation(
        company=company,
        membership=membership,
        effective_from=effective_from,
        created_by=by.user if by is not None else None,
        **fields,
    )
    _clean(row)
    try:
        with transaction.atomic():
            row.save()
    except IntegrityError:
        raise DomainError(
            _("There is already a pay setup from that day: change that one.")
        ) from None
    _audit(by, PayrollAction.PAY_SET, membership, company_id=company.pk, **_pay_details(row))
    _bump(company.pk, PULSE_PAY)
    return row


@transaction.atomic
def update_pay(row: Compensation, *, by: Membership | None, **fields) -> Compensation:
    """Correct a pay setup no finalized run has used yet (a used one is locked: add a new one)."""
    _require(by, Perm.PAYROLL_MANAGE)
    row = Compensation.objects.select_for_update().select_related("membership").get(pk=row.pk)
    if row.locked:
        raise DomainError(
            _("A finalized payroll used this pay setup, so it can't change. Add a new one instead.")
        )
    if unknown := set(fields) - set(PAY_FIELDS):
        raise DomainError(_("Unknown field: %(name)s") % {"name": ", ".join(sorted(unknown))})
    company = row.company
    merged = {"pay_type": fields.get("pay_type", row.pay_type), **fields}
    fields = {
        key: value for key, value in _check_pay_fields(company, merged).items() if key in fields
    }
    if "effective_from" in fields:
        _check_start(row.membership, fields["effective_from"])
        clash = Compensation.objects.filter(
            membership=row.membership, effective_from=fields["effective_from"]
        ).exclude(pk=row.pk)
        if clash.exists():
            raise DomainError(_("There is already a pay setup from that day: change that one."))
    else:
        _check_start(row.membership, row.effective_from)
    before = {name: getattr(row, name) for name in fields}
    for name, value in fields.items():
        setattr(row, name, value)
    _clean(row)
    row.save()
    if changed := _changes(before, fields):
        _audit(
            by,
            PayrollAction.PAY_CHANGED,
            row.membership,
            company_id=company.pk,
            compensation=row.pk,
            changes=changed,
        )
        _bump(company.pk, PULSE_PAY)
    return row


@transaction.atomic
def remove_pay(row: Compensation, *, by: Membership | None) -> None:
    _require(by, Perm.PAYROLL_MANAGE)
    row = Compensation.objects.select_for_update().select_related("membership").get(pk=row.pk)
    if row.locked:
        raise DomainError(_("A finalized payroll used this pay setup, so it stays."))
    _check_start(row.membership, row.effective_from)
    details = _pay_details(row)
    membership = row.membership
    row.delete()
    _audit(by, PayrollAction.PAY_REMOVED, membership, company_id=membership.company_id, **details)
    _bump(membership.company_id, PULSE_PAY)


SETUP_KEYS = ("pay_type", "amount", "currency", "proration", "pays_task_rates", "overtime_eligible")


def propose_pay_change(
    membership: Membership, *, by: Membership | None, setup: dict, effective_on: date, reason: str
) -> Compensation:
    """A pay change decided elsewhere (an approved job change in `apps.lifecycle`): the new
    setup from `effective_on`. Keys of `setup` not given keep the current setup's values; a
    setup already starting that day (and not yet used) is replaced."""
    if unknown := set(setup) - set(SETUP_KEYS):
        raise DomainError(_("Unknown field: %(name)s") % {"name": ", ".join(sorted(unknown))})
    current = queries.compensation(membership, on=effective_on)
    base = {key: getattr(current, key) for key in SETUP_KEYS} if current is not None else {}
    fields = {**base, **setup, "note": _text(reason, required=False, limit=300)}
    same_day = Compensation.objects.filter(
        membership=membership, effective_from=effective_on, locked=False
    ).first()
    if same_day is not None:
        return update_pay(same_day, by=by, **fields)
    return set_pay(membership, by=by, effective_from=effective_on, **fields)


def lock_pay(membership: Membership, start: date, end: date) -> int:
    """Lock the setups in force on any day from `start` to `end` (a finalized run used them)."""
    ids = queries.compensation_ids_between(membership, start, end)
    return Compensation.objects.filter(pk__in=ids, locked=False).update(locked=True)


def unlock_pay(company: Company, *, keep_run: PayrollRun | None = None) -> int:
    """Unlock every setup no finalized run uses any more (after a run was reopened)."""
    used: set[int] = set()
    finalized = (
        PayrollRun.objects.for_company(company)
        .filter(status__in=(PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID))
        .prefetch_related("payslips__membership")
    )
    for run in finalized:
        if keep_run is not None and run.pk == keep_run.pk:
            continue
        start, end = periods.bounds(run.period)
        for payslip in run.payslips.all():
            used |= queries.compensation_ids_between(payslip.membership, start, end)
    return (
        Compensation.objects.for_company(company)
        .filter(locked=True)
        .exclude(pk__in=used)
        .update(locked=False)
    )


# Task rates -----------------------------------------------------------------------------

RATE_FIELDS = ("template", "position", "amount", "currency", "on_time_only", "is_active")


@transaction.atomic
def save_task_rate(
    company: Company, *, by: Membership | None, rate: TaskRate | None = None, **fields
) -> TaskRate:
    _require(by, Perm.PAYROLL_MANAGE)
    if unknown := set(fields) - set(RATE_FIELDS):
        raise DomainError(_("Unknown field: %(name)s") % {"name": ", ".join(sorted(unknown))})
    _same_company(company, rate, fields.get("template"), fields.get("position"))
    row = rate or TaskRate(company=company)
    before = {name: getattr(row, name) for name in fields} if rate else {}
    if "amount" in fields or rate is None:
        fields["amount"] = _amount(fields.get("amount"))
    if "currency" in fields or rate is None:
        fields["currency"] = _currency(company, fields.get("currency"))
    for name, value in fields.items():
        setattr(row, name, value)
    _clean(row)
    row.save()
    audit.record(
        PayrollAction.TASK_RATE_SAVED,
        company_id=company.pk,
        actor=by.user if by is not None else None,
        target=row,
        required_perm=Perm.PAYROLL_VIEW,
        changes=_changes(before, fields),
    )
    _bump(company.pk, PULSE_PAY)
    return row


@transaction.atomic
def remove_task_rate(rate: TaskRate, *, by: Membership | None) -> None:
    _require(by, Perm.PAYROLL_MANAGE)
    company_id = rate.company_id
    audit.record(
        PayrollAction.TASK_RATE_REMOVED,
        company_id=company_id,
        actor=by.user if by is not None else None,
        target=rate,
        required_perm=Perm.PAYROLL_VIEW,
    )
    rate.delete()
    _bump(company_id, PULSE_PAY)


# Bonuses and fines ----------------------------------------------------------------------


def _adjustment_details(row: Adjustment) -> dict:
    return {
        "adjustment": row.pk,
        "kind": row.kind,
        "amount": str(row.amount),
        "currency": row.currency,
        "period": row.period.isoformat(),
        "reason": row.reason,
        "source": row.source,
    }


def _lock_adjustment(row: Adjustment) -> Adjustment:
    return (
        Adjustment.objects.select_for_update(of=("self",))
        .select_related("company", "membership__user")
        .get(pk=row.pk)
    )


def _unlocked(row: Adjustment) -> None:
    if row.is_locked:
        raise DomainError(_("This is on a finalized payslip, so it can't change."))
    _check_period_open(row.company, row.period)


@transaction.atomic
def propose(
    membership: Membership,
    *,
    by: Membership | None,
    kind: str,
    amount,
    reason: str,
    period=None,
    source: str = Adjustment.Source.MANUAL,
    rule: AdjustmentRule | None = None,
    rule_key: str = "",
    task=None,
    attendance=None,
    approve: bool = False,
    currency: str | None = None,
) -> Adjustment:
    """Propose a bonus, fine, allowance or deduction for `membership` in `period` (a month;
    this month by default). With `approve` (payroll.manage) it is approved at once. Nobody
    proposes one for themselves."""
    company = membership.company
    _require(by, Perm.PAYROLL_PROPOSE, Perm.PAYROLL_MANAGE)
    if approve:
        _require(by, Perm.PAYROLL_MANAGE)
    _check_member(company, membership)
    _same_company(company, by, rule, task, attendance)
    if by is not None and by.pk == membership.pk:
        raise DomainError(_("You can't propose a bonus or a fine for yourself."))
    if kind not in Adjustment.Kind.values:
        raise DomainError(_("Pick a bonus, a fine, an allowance or a deduction."))
    if source not in Adjustment.Source.values:
        raise ValueError(f"Unknown adjustment source {source!r}.")
    period = _period(company, period)
    _check_period_open(company, period)
    row = Adjustment(
        company=company,
        membership=membership,
        period=period,
        kind=kind,
        amount=_amount(amount),
        currency=_currency(company, currency),
        reason=_text(reason, required=True, limit=300),
        source=source,
        rule=rule,
        rule_key=rule_key[:64],
        task=task,
        attendance=attendance,
        proposed_by=by.user if by is not None else None,
    )
    if approve:
        row.status = AdjustmentStatus.APPROVED
        row.decided_by = by.user if by is not None else None
        row.decided_at = timezone.now()
    row.save()
    _audit(
        by,
        PayrollAction.ADJUSTMENT_PROPOSED,
        row,
        company_id=company.pk,
        **_adjustment_details(row),
    )
    if approve:
        _approved(row, by)
    else:
        notify.adjustment_proposed(row, by)
    _bump(company.pk, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


def _source_value(source) -> str:
    """What `propose_fine` callers pass as `source`: a source name, or the record that led to
    the fine (a disciplinary record of `apps.lifecycle` counts as `discipline`)."""
    if source in (None, ""):
        return Adjustment.Source.MANUAL
    if isinstance(source, str):
        if source in Adjustment.Source.values:
            return source
        if source.split(".", 1)[0] == "lifecycle":
            return Adjustment.Source.DISCIPLINE
        raise ValueError(f"Unknown adjustment source {source!r}.")
    if getattr(source, "_meta", None) is not None and source._meta.app_label == "lifecycle":
        return Adjustment.Source.DISCIPLINE
    raise ValueError(f"Unknown adjustment source {source!r}.")


@transaction.atomic
def propose_fine(
    membership: Membership, *, by: Membership | None, amount, reason: str, source="discipline"
) -> Adjustment:
    """Propose a fine on this month's pay from another app (a disciplinary record): it waits
    for a `payroll.manage` holder like any proposal. `source` is an `Adjustment.Source` value
    ("discipline" for apps.lifecycle) or the record itself. The caller checks its own
    permission (issuing a disciplinary record), so this one doesn't ask for payroll.propose."""
    company = membership.company
    source = _source_value(source)
    _check_member(company, membership)
    _same_company(company, by)
    period = periods.first_day(periods.today(company))
    _check_period_open(company, period)
    row = Adjustment.objects.create(
        company=company,
        membership=membership,
        period=period,
        kind=Adjustment.Kind.FINE,
        amount=_amount(amount),
        currency=conf.get_settings(company).currency,
        reason=_text(reason, required=True, limit=300),
        source=source,
        proposed_by=by.user if by is not None else None,
    )
    _audit(
        by,
        PayrollAction.ADJUSTMENT_PROPOSED,
        row,
        company_id=company.pk,
        **_adjustment_details(row),
    )
    notify.adjustment_proposed(row, by)
    _bump(company.pk, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


def _approved(row: Adjustment, by: Membership | None) -> None:
    """Audit an approval on the person too (their History) and tell them."""
    _audit(
        by,
        PayrollAction.ADJUSTMENT_APPROVED,
        row.membership,
        company_id=row.company_id,
        **_adjustment_details(row),
    )
    notify.adjustment_approved(row, by)


@transaction.atomic
def approve(row: Adjustment, *, by: Membership | None, note: str = "") -> Adjustment:
    _require(by, Perm.PAYROLL_MANAGE)
    row = _lock_adjustment(row)
    _unlocked(row)
    if row.status != AdjustmentStatus.PROPOSED:
        raise DomainError(_("This was already decided."))
    if by is not None and by.pk == row.membership_id:
        raise DomainError(_("You can't approve a bonus or a fine of your own."))
    _check_member(row.company, row.membership)
    row.status = AdjustmentStatus.APPROVED
    row.decided_by = by.user if by is not None else None
    row.decided_at = timezone.now()
    row.decision_note = _text(note, required=False, limit=300)
    row.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    _approved(row, by)
    _bump(row.company_id, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


@transaction.atomic
def reject(row: Adjustment, *, by: Membership | None, reason: str) -> Adjustment:
    _require(by, Perm.PAYROLL_MANAGE)
    row = _lock_adjustment(row)
    _unlocked(row)
    if row.status != AdjustmentStatus.PROPOSED:
        raise DomainError(_("This was already decided."))
    row.status = AdjustmentStatus.REJECTED
    row.decided_by = by.user if by is not None else None
    row.decided_at = timezone.now()
    row.decision_note = _text(reason, required=False, limit=300)
    row.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    _audit(
        by,
        PayrollAction.ADJUSTMENT_REJECTED,
        row,
        company_id=row.company_id,
        note=row.decision_note,
        **_adjustment_details(row),
    )
    _bump(row.company_id, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


@transaction.atomic
def void(row: Adjustment, *, by: Membership | None, reason: str) -> Adjustment:
    """Take back a proposed or approved bonus or fine that no finalized payslip holds."""
    _require(by, Perm.PAYROLL_MANAGE)
    row = _lock_adjustment(row)
    _unlocked(row)
    if row.status not in (AdjustmentStatus.PROPOSED, AdjustmentStatus.APPROVED):
        raise DomainError(_("Only a proposed or approved one can be voided."))
    row.status = AdjustmentStatus.VOID
    row.decided_by = by.user if by is not None else None
    row.decided_at = timezone.now()
    row.decision_note = _text(reason, required=True, limit=300)
    row.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    _audit(
        by,
        PayrollAction.ADJUSTMENT_VOIDED,
        row.membership,
        company_id=row.company_id,
        note=row.decision_note,
        **_adjustment_details(row),
    )
    _bump(row.company_id, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


@transaction.atomic
def dispute(row: Adjustment, *, by: Membership, text: str) -> Adjustment:
    """The person disputes their own fine or deduction (once, while it can still change)."""
    row = _lock_adjustment(row)
    if by.pk != row.membership_id:
        raise PermissionDenied(_("You can only dispute your own fines."))
    if row.kind not in Adjustment.NEGATIVE:
        raise DomainError(_("Only a fine or a deduction can be disputed."))
    if row.status not in (AdjustmentStatus.PROPOSED, AdjustmentStatus.APPROVED):
        raise DomainError(_("This fine was taken back already."))
    if row.disputed_at is not None:
        raise DomainError(_("You already disputed this fine."))
    _unlocked(row)
    row.disputed_at = timezone.now()
    row.dispute_text = _text(text, required=True, limit=500, message=_("Write why you disagree."))
    row.save(update_fields=["disputed_at", "dispute_text", "updated_at"])
    _audit(
        by,
        PayrollAction.ADJUSTMENT_DISPUTED,
        row,
        company_id=row.company_id,
        adjustment=row.pk,
        text=row.dispute_text,
    )
    notify.adjustment_disputed(row)
    _bump(row.company_id, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


@transaction.atomic
def answer_dispute(
    row: Adjustment, *, by: Membership | None, answer: str, void_it: bool = False
) -> Adjustment:
    """Answer a disputed fine; with `void_it` the fine is also taken back."""
    _require(by, Perm.PAYROLL_MANAGE)
    row = _lock_adjustment(row)
    if not row.dispute_open:
        raise DomainError(_("There is no open dispute on this."))
    row.dispute_answer = _text(answer, required=True, limit=500, message=_("Write an answer."))
    row.dispute_answered_at = timezone.now()
    row.dispute_answered_by = by.user if by is not None else None
    fields = ["dispute_answer", "dispute_answered_at", "dispute_answered_by", "updated_at"]
    if void_it:
        _unlocked(row)
        if row.status not in (AdjustmentStatus.PROPOSED, AdjustmentStatus.APPROVED):
            raise DomainError(_("Only a proposed or approved one can be voided."))
        row.status = AdjustmentStatus.VOID
        row.decided_by = by.user if by is not None else None
        row.decided_at = timezone.now()
        row.decision_note = row.dispute_answer[:300]
        fields += ["status", "decided_by", "decided_at", "decision_note"]
    row.save(update_fields=fields)
    _audit(
        by,
        PayrollAction.DISPUTE_ANSWERED,
        row,
        company_id=row.company_id,
        adjustment=row.pk,
        answer=row.dispute_answer,
        voided=void_it,
    )
    notify.dispute_answered(row, by)
    _bump(row.company_id, PULSE_ADJUSTMENTS, PULSE_PENDING)
    return row


def bulk_decide(rows, *, by: Membership | None, approve_them: bool, reason: str = "") -> list[dict]:
    """Approve or reject many proposals; each one succeeds or fails on its own:
    `[{"id", "ok", "status" | "error"}]`."""
    _require(by, Perm.PAYROLL_MANAGE)
    rows = list(rows)
    if len(rows) > MAX_BULK:
        raise DomainError(_("At most %(count)s at a time.") % {"count": MAX_BULK})
    results = []
    for row in rows:
        try:
            done = approve(row, by=by) if approve_them else reject(row, by=by, reason=reason)
            results.append({"id": row.pk, "ok": True, "status": done.status})
        except (DomainError, PermissionDenied) as exc:
            results.append({"id": row.pk, "ok": False, "error": str(exc)})
    return results


# Advances -------------------------------------------------------------------------------


def _advance_details(row: Advance) -> dict:
    return {
        "advance": row.pk,
        "amount": str(row.amount),
        "currency": row.currency,
        "installments": row.installments,
        "first_period": row.first_period.isoformat(),
    }


def _lock_advance(row: Advance) -> Advance:
    return (
        Advance.objects.select_for_update(of=("self",))
        .select_related("company", "membership__user", "debt")
        .get(pk=row.pk)
    )


def _check_first_period(company: Company, first_period: date) -> date:
    first_period = periods.parse_period(first_period)
    this_month = periods.first_day(periods.today(company))
    if first_period < this_month:
        raise DomainError(_("Advances are paid back from this month or a later one."))
    if first_period > periods.add_months(this_month, 12):
        raise DomainError(_("Pick a month within a year."))
    _check_period_open(company, first_period)
    return first_period


def _installments(value) -> int:
    try:
        count = int(value)
    except TypeError, ValueError:
        raise DomainError(_("Pick in how many months it is paid back.")) from None
    if not 1 <= count <= 12:
        raise DomainError(_("An advance is paid back in 1 to 12 months."))
    return count


@transaction.atomic
def request_advance(
    membership: Membership, *, by: Membership, amount, reason: str = "", installments=1
) -> Advance:
    """The person asks for an advance on their own pay, up to the company's cap."""
    if by.pk != membership.pk:
        raise PermissionDenied(_("You can only ask for an advance for yourself."))
    company = membership.company
    _check_member(company, membership)
    amount = _amount(amount)
    cap = queries.advance_cap(membership)
    if amount > cap["available"]:
        if cap["available"] <= 0:
            raise DomainError(_("No advance is available to you right now."))
        raise DomainError(
            _("You can ask for at most %(amount)s now.")
            % {"amount": queries.money_text(cap["available"], cap["currency"])}
        )
    row = Advance.objects.create(
        company=company,
        membership=membership,
        amount=amount,
        currency=cap["currency"],
        installments=_installments(installments),
        first_period=periods.first_day(periods.today(company)),
        reason=_text(reason, required=False, limit=300),
        requested_by=by.user,
    )
    _audit(by, PayrollAction.ADVANCE_REQUESTED, row, company_id=company.pk, **_advance_details(row))
    notify.advance_requested(row, cap)
    _bump(company.pk, PULSE_ADVANCES, PULSE_PENDING)
    return row


@transaction.atomic
def create_advance(
    membership: Membership,
    *,
    by: Membership | None,
    amount,
    installments=1,
    first_period=None,
    reason: str = "",
) -> Advance:
    """An advance given from the dashboard ("Give an advance"): approved at once, waiting to
    be paid. The cap is the person's own limit; a manager may go above it."""
    _require(by, Perm.PAYROLL_MANAGE)
    company = membership.company
    _check_member(company, membership)
    if by is not None and by.pk == membership.pk:
        raise DomainError(_("You can't give an advance to yourself."))
    first_period = _check_first_period(company, first_period or periods.today(company))
    row = Advance.objects.create(
        company=company,
        membership=membership,
        amount=_amount(amount),
        currency=conf.get_settings(company).currency,
        installments=_installments(installments),
        first_period=first_period,
        reason=_text(reason, required=False, limit=300),
        status=AdvanceStatus.APPROVED,
        requested_by=by.user if by is not None else None,
        decided_by=by.user if by is not None else None,
        decided_at=timezone.now(),
    )
    _audit(by, PayrollAction.ADVANCE_APPROVED, row, company_id=company.pk, **_advance_details(row))
    _bump(company.pk, PULSE_ADVANCES)
    return row


@transaction.atomic
def decide_advance(
    row: Advance,
    *,
    by: Membership | None,
    approve_it: bool,
    note: str = "",
    installments=None,
    first_period=None,
) -> Advance:
    """Approve (optionally changing the months it is paid back over) or reject a request."""
    _require(by, Perm.PAYROLL_MANAGE)
    row = _lock_advance(row)
    if row.status != AdvanceStatus.REQUESTED:
        raise DomainError(_("This was already decided."))
    if by is not None and by.pk == row.membership_id:
        raise DomainError(_("You can't decide your own advance."))
    row.decided_by = by.user if by is not None else None
    row.decided_at = timezone.now()
    row.decision_note = _text(note, required=False, limit=300)
    fields = ["status", "decided_by", "decided_at", "decision_note", "updated_at"]
    if approve_it:
        _check_member(row.company, row.membership)
        row.status = AdvanceStatus.APPROVED
        if installments is not None:
            row.installments = _installments(installments)
            fields.append("installments")
        if first_period is not None:
            row.first_period = _check_first_period(row.company, first_period)
            fields.append("first_period")
        action = PayrollAction.ADVANCE_APPROVED
    else:
        row.status = AdvanceStatus.REJECTED
        action = PayrollAction.ADVANCE_REJECTED
    row.save(update_fields=fields)
    _audit(by, action, row, company_id=row.company_id, **_advance_details(row))
    notify.advance_decided(row, by)
    _bump(row.company_id, PULSE_ADVANCES, PULSE_PENDING)
    return row


@transaction.atomic
def cancel_advance(row: Advance, *, by: Membership, reason: str = "") -> Advance:
    """The person takes back their request, or a manager cancels one not paid yet."""
    row = _lock_advance(row)
    own = by.pk == row.membership_id
    if not own:
        _require(by, Perm.PAYROLL_MANAGE)
    allowed = (
        (AdvanceStatus.REQUESTED,) if own else (AdvanceStatus.REQUESTED, AdvanceStatus.APPROVED)
    )
    if row.status not in allowed:
        raise DomainError(_("This advance can't be cancelled any more."))
    row.status = AdvanceStatus.CANCELLED
    row.decision_note = _text(reason, required=False, limit=300)
    row.save(update_fields=["status", "decision_note", "updated_at"])
    _audit(
        by, PayrollAction.ADVANCE_CANCELLED, row, company_id=row.company_id, **_advance_details(row)
    )
    _bump(row.company_id, PULSE_ADVANCES, PULSE_PENDING)
    return row


@transaction.atomic
def pay_advance(
    row: Advance,
    *,
    by: Membership | None,
    account: MoneyAccount,
    method: str = PayoutMethod.CASH,
    paid_on: date | None = None,
) -> Advance:
    """Hand an approved advance out from `account`: a receivable (kind advance) opens in
    finance and the money leaves the account. Repaid from `first_period`'s payslip on."""
    _require(by, Perm.PAYROLL_PAY)
    row = _lock_advance(row)
    company = row.company
    if row.status != AdvanceStatus.APPROVED:
        raise DomainError(_("Only an approved advance can be paid."))
    _same_company(company, account)
    if method not in PayoutMethod.values:
        raise DomainError(_("Pick how it was paid."))
    paid_on = paid_on or periods.today(company)
    if periods.first_day(paid_on) > row.first_period:
        row.first_period = periods.first_day(paid_on)
    _check_period_open(company, row.first_period)
    row.debt = finance.open_debt(
        company,
        by=by,
        direction="receivable",
        kind="advance",
        amount=row.amount,
        currency=row.currency,
        issued_on=paid_on,
        membership=row.membership,
        account=account,
        branch=row.membership.home_branch,
        description=_("Advance to %(name)s") % {"name": row.membership},
        source=Source(ADVANCE_SOURCE, row.pk, "paid"),
    )
    row.status = AdvanceStatus.PAID
    row.paid_at = timezone.now()
    row.paid_by = by.user if by is not None else None
    row.payout_method = method
    row.save(
        update_fields=[
            "debt",
            "status",
            "paid_at",
            "paid_by",
            "payout_method",
            "first_period",
            "updated_at",
        ]
    )
    _audit(
        by,
        PayrollAction.ADVANCE_PAID,
        row.membership,
        company_id=company.pk,
        account=account.pk,
        method=method,
        **_advance_details(row),
    )
    notify.advance_paid(row, by)
    _bump(company.pk, PULSE_ADVANCES)
    return row


@transaction.atomic
def repay_advance(
    row: Advance,
    *,
    by: Membership | None,
    amount,
    account: MoneyAccount,
    paid_on: date | None = None,
    note: str = "",
) -> AdvanceRepayment:
    """The person pays (part of) an advance back in money, onto `account`."""
    _require(by, Perm.PAYROLL_PAY)
    row = _lock_advance(row)
    company = row.company
    if row.status != AdvanceStatus.PAID or row.debt is None:
        raise DomainError(_("Only a paid advance can be paid back."))
    _same_company(company, account)
    amount = _amount(amount)
    left = queries.advance_left(row)
    if amount > left:
        raise DomainError(
            _("That's more than the %(left)s still owed.")
            % {"left": queries.money_text(left, row.currency)}
        )
    paid_on = paid_on or periods.today(company)
    repayment = AdvanceRepayment.objects.create(
        advance=row,
        amount=amount,
        paid_on=paid_on,
        note=_text(note, required=False, limit=300),
        created_by=by.user if by is not None else None,
    )
    repayment.transaction = finance.pay_debt(
        row.debt,
        by=by,
        amount=amount,
        paid_on=paid_on,
        account=account,
        source=Source(ADVANCE_SOURCE, row.pk, f"back{repayment.pk}"),
    )
    repayment.save(update_fields=["transaction"])
    if queries.advance_left(row) == 0:
        row.status = AdvanceStatus.REPAID
        row.save(update_fields=["status", "updated_at"])
    _audit(
        by,
        PayrollAction.ADVANCE_REPAID,
        row,
        company_id=company.pk,
        repayment=repayment.pk,
        paid=str(amount),
        **_advance_details(row),
    )
    _bump(company.pk, PULSE_ADVANCES)
    return repayment


__all__ = [
    "PAYABLE_STATUSES",
    "answer_dispute",
    "approve",
    "bulk_decide",
    "calculate_run",
    "cancel_advance",
    "cancel_run",
    "confirm_received",
    "create_advance",
    "create_run",
    "decide_advance",
    "dispute",
    "finalize_run",
    "lock_pay",
    "mark_paid",
    "mark_viewed",
    "pay_advance",
    "propose",
    "propose_fine",
    "propose_pay_change",
    "publish",
    "reject",
    "remove_pay",
    "remove_task_rate",
    "reopen_run",
    "repay_advance",
    "request_advance",
    "save_task_rate",
    "set_manual_lines",
    "set_pay",
    "unlock_pay",
    "update_pay",
    "update_settings",
    "void",
]
