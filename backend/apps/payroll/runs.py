"""The monthly payroll run: create → calculate (again and again while a draft) → finalize →
publish → mark paid, with reopen and cancel. Re-exported by `apps.payroll.services`.

Calculating replaces a draft run's payslips with fresh ones (lines a person added by hand
stay). Finalizing calculates once more, then locks what it used (the pay setups in force, the
approved adjustments, the advance repayments) and books the month in finance
(`finance_bridge`). Reopening undoes exactly that; a run can be reopened until a payslip of it
is paid, and only when no later month is finalized.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.finance.models import MoneyAccount
from apps.finance.rates import rate_for
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import person_ref
from apps.payroll import calculator, conf, finance_bridge, notify, periods, queries, rules
from apps.payroll.audit_actions import PayrollAction
from apps.payroll.models import (
    Adjustment,
    Advance,
    AdvanceRepayment,
    Compensation,
    PayoutMethod,
    PayrollRun,
    Payslip,
    PayslipLine,
    TaskRate,
)
from apps.payroll.signals import payslips_published, run_paid

ZERO = Decimal(0)
Kind = PayslipLine.Kind
Status = PayrollRun.Status
PULSE_RUNS = "payroll.runs"
PULSE_ADJUSTMENTS = "payroll.adjustments"
PULSE_ADVANCES = "payroll.advances"
PULSE_PAY = "payroll.pay"
MAX_MANUAL_LINES = 20


def _require(by: Membership | None, *perms: Perm) -> None:
    if by is None:
        return
    if not any(by.has_perm(perm) for perm in perms):
        raise PermissionDenied(_("You don't have permission to do this."))


def _bump(company_id: int, *keys: str) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, *keys))


def _audit(by, action, target, *, company_id: int, **details) -> None:
    audit.record(
        action,
        company_id=company_id,
        actor=by.user if by is not None else None,
        target=target,
        required_perm=Perm.PAYROLL_VIEW,
        **details,
    )


def _lock(run: PayrollRun) -> PayrollRun:
    return (
        PayrollRun.objects.select_for_update(of=("self",)).select_related("company").get(pk=run.pk)
    )


def _money_text(value: Decimal) -> str:
    return f"{value:.2f}"


# Creating and calculating ---------------------------------------------------------------


@transaction.atomic
def create_run(
    company,
    *,
    by: Membership | None,
    period,
    usd_rate=None,
    notes: str = "",
    calculate: bool = True,
) -> PayrollRun:
    """A draft run for `period` (a month up to the current one), calculated at once."""
    _require(by, Perm.PAYROLL_MANAGE)
    period = periods.parse_period(period)
    this_month = periods.first_day(periods.today(company))
    if period > this_month:
        raise DomainError(_("A payroll can't be made for a month that hasn't started."))
    try:
        with transaction.atomic():
            run = PayrollRun.objects.create(
                company=company,
                period=period,
                usd_rate=Decimal(str(usd_rate)) if usd_rate not in (None, "") else None,
                notes=(notes or "").strip()[:2000],
                created_by=by.user if by is not None else None,
            )
    except IntegrityError:
        raise DomainError(
            _("There is already a payroll for %(month)s.") % {"month": queries.month_label(period)}
        ) from None
    _audit(by, PayrollAction.RUN_CREATED, run, company_id=company.pk, period=period.isoformat())
    if calculate:
        run = calculate_run(run, by=by)
    _bump(company.pk, PULSE_RUNS)
    return run


def _usd_rate(run: PayrollRun) -> Decimal | None:
    """The run's dollar rate: as given, else the company's rate for the month's last day when
    a pay setup or an active task rate is in another currency."""
    if run.usd_rate is not None:
        return run.usd_rate
    currency = conf.get_settings(run.company).currency
    foreign = (
        Compensation.objects.for_company(run.company).exclude(currency=currency).exists()
        or TaskRate.objects.for_company(run.company)
        .filter(is_active=True)
        .exclude(currency=currency)
        .exists()
    )
    if not foreign:
        return None
    try:
        return rate_for(run.company, "USD", periods.last_day(run.period)).rate
    except DomainError:
        return None


def _warnings(run: PayrollRun, inputs, people, results, members) -> list[dict]:
    company = run.company
    start, end = periods.bounds(run.period)
    found: list[dict] = []
    paid_ids = {person.member_id for person in people}
    from apps.hr.queries import employment_dates
    from apps.payroll.services import PAYABLE_STATUSES

    staff = list(
        Membership.objects.for_company(company)
        .filter(status__in=PAYABLE_STATUSES)
        .exclude(pk__in=paid_ids)
        .exclude(role__is_owner=True)
        .select_related("user")
        .order_by("first_name", "last_name", "pk")
    )
    # Only people who worked here during the month and have no pay setup for it.
    dates = employment_dates(company, [member.pk for member in staff])
    for member in staff:
        first, last = dates.get(member.pk, (None, None))
        if first is None or first > end or (last is not None and last < start):
            continue
        found.append({"code": "no_pay_setup", "level": "warning", "member": person_ref(member)})
    for result in results:
        member = members.get(result.member_id)
        for warning in result.warnings:
            found.append({"level": "warning", **warning, "member": person_ref(member)})
        if sum((line.amount for line in result.lines), ZERO) < 0:
            found.append({"code": "negative_net", "level": "error", "member": person_ref(member)})
    proposed = Adjustment.objects.for_company(company).filter(
        period=start, status=Adjustment.Status.PROPOSED
    )
    if count := proposed.count():
        found.append({"code": "proposed", "level": "warning", "count": count})
    disputes = queries.open_disputes(company).filter(period=start)
    if count := disputes.count():
        found.append({"code": "disputes", "level": "warning", "count": count})
    from apps.attendance import queries as attendance
    from apps.attendance.models import AttendanceRecord

    records = attendance.records_between(company, start, end, branch_ids=None).filter(
        membership_id__in=paid_ids
    )
    if count := records.filter(overtime_status=AttendanceRecord.Overtime.PENDING).count():
        found.append({"code": "pending_overtime", "level": "warning", "count": count})
    if count := records.filter(status=AttendanceRecord.Status.OPEN).count():
        found.append({"code": "open_attendance", "level": "info", "count": count})
    return found


def _totals(run: PayrollRun) -> dict:
    payslips = list(run.payslips.all())
    lines = list(PayslipLine.objects.filter(payslip__run=run).values_list("kind", "amount"))

    def total(kinds) -> Decimal:
        return sum((amount for kind, amount in lines if kind in kinds), ZERO)

    bonuses = total((Kind.BONUS, Kind.ALLOWANCE, Kind.TASK_REWARD))
    fines = -total((Kind.FINE, Kind.DEDUCTION))
    taxes = finance_bridge.tax_totals(run)
    return {
        "currency": conf.get_settings(run.company).currency,
        "people": len(payslips),
        "gross": _money_text(sum((p.gross for p in payslips), ZERO)),
        "deductions": _money_text(sum((p.deductions for p in payslips), ZERO)),
        "net": _money_text(sum((p.net for p in payslips), ZERO)),
        "bonuses": _money_text(bonuses),
        "fines": _money_text(fines),
        "advances": _money_text(-total((Kind.ADVANCE,))),
        "reimbursements": _money_text(total((Kind.REIMBURSEMENT,))),
        "taxes": {key: _money_text(value) for key, value in taxes.items()},
        "paid": sum(1 for p in payslips if p.status == Payslip.Status.PAID),
        "published": sum(1 for p in payslips if p.published_at is not None),
    }


def _store(run: PayrollRun, result: calculator.Result, payslip: Payslip | None, by) -> Payslip:
    """Write one person's result: their payslip (made or refreshed) and its lines."""
    manual = []
    if payslip is None:
        payslip = Payslip(company=run.company, run=run, membership_id=result.member_id)
    else:
        manual = list(payslip.lines.filter(kind=Kind.MANUAL).order_by("order", "pk"))
        payslip.lines.exclude(kind=Kind.MANUAL).delete()
    lines = result.lines
    payslip.currency = result.currency
    payslip.pay_type = result.pay_type
    payslip.base_pay = sum(
        (line.amount for line in lines if line.kind in (Kind.BASE, Kind.PRORATION)), ZERO
    )
    payslip.scheduled_days = Decimal(result.scheduled_days)
    payslip.paid_days = result.paid_days
    payslip.paid_leave_days = Decimal(result.paid_leave_days)
    payslip.unpaid_leave_days = Decimal(result.unpaid_leave_days)
    payslip.absent_days = Decimal(result.absent_days)
    payslip.worked_minutes = result.worked_minutes
    payslip.overtime_minutes = result.overtime_minutes
    payslip.night_minutes = result.night_minutes
    payslip.late_arrivals = result.late_arrivals
    payslip.task_stats = result.task_stats
    payslip.taxes = result.taxes
    payslip.gross = sum(
        (
            line.amount
            for line in lines
            if line.kind in PayslipLine.EARNINGS or (line.kind == Kind.MANUAL and line.amount > 0)
        ),
        ZERO,
    )
    payslip.deductions = -sum(
        (
            line.amount
            for line in lines
            if line.kind in PayslipLine.DEDUCTIONS or (line.kind == Kind.MANUAL and line.amount < 0)
        ),
        ZERO,
    )
    payslip.net = sum((line.amount for line in lines), ZERO)
    payslip.save()
    kept_lines = {row.pk: row for row in manual}
    rows = []
    for order, line in enumerate(lines):
        if line.kind == Kind.MANUAL and line.line_id in kept_lines:
            kept = kept_lines.pop(line.line_id)
            if kept.order != order:
                kept.order = order
                kept.save(update_fields=["order"])
            continue
        rows.append(
            PayslipLine(
                payslip=payslip,
                kind=line.kind,
                label=line.label[:200],
                params=line.params,
                quantity=line.quantity,
                rate=line.rate,
                amount=line.amount,
                adjustment_id=line.adjustment_id,
                advance_id=line.advance_id,
                debt_id=line.debt_id,
                order=order,
            )
        )
    PayslipLine.objects.bulk_create(rows)
    return payslip


def _calculate(run: PayrollRun, *, by, member_ids=None) -> PayrollRun:
    if run.is_final:
        return _calculate_final(run, by=by)
    company = run.company
    if member_ids is None:
        rules.evaluate_monthly(company, run.period, by=by)
    run.usd_rate = _usd_rate(run)
    inputs, people = calculator.gather(
        company, run.period, usd_rate=run.usd_rate, member_ids=member_ids
    )
    # People settled by a final run of that month are paid there, not here (unless this run
    # had paid their month already when they left: then the final run pays only the rest).
    finals = set(
        PayrollRun.objects.for_company(company)
        .filter(kind=PayrollRun.Kind.FINAL, period=run.period, after_regular=False)
        .exclude(status=Status.CANCELLED)
        .values_list("membership_id", flat=True)
    )
    people = [person for person in people if person.member_id not in finals]
    existing = {
        payslip.membership_id: payslip
        for payslip in run.payslips.prefetch_related("lines")
        if member_ids is None or payslip.membership_id in member_ids
    }
    results = []
    for person in people:
        payslip = existing.pop(person.member_id, None)
        manual = list(payslip.lines.filter(kind=Kind.MANUAL)) if payslip is not None else []
        result = calculator.compute(person, inputs, manual_lines=manual)
        if result is None:
            if payslip is not None:
                existing[person.member_id] = payslip
            continue
        results.append(result)
        _store(run, result, payslip, by)
    # Nobody left to pay for these any more (a pay setup removed, a member out of the month).
    for payslip in existing.values():
        payslip.delete()
    members = {
        member.pk: member
        for member in Membership.objects.filter(
            pk__in=[result.member_id for result in results]
        ).select_related("user")
    }
    if member_ids is None:
        run.warnings = _warnings(run, inputs, people, results, members)
    run.calculated_at = timezone.now()
    run.totals = _totals(run)
    run.save(update_fields=["usd_rate", "warnings", "calculated_at", "totals", "updated_at"])
    return run


def _calculate_final(run: PayrollRun, *, by) -> PayrollRun:
    """A final settlement's one payslip (`apps.payroll.settlement`): the month through the last
    day, the unused leave, every advance left; monthly rules are not evaluated for it."""
    from apps.payroll import settlement

    company = run.company
    member = run.membership
    run.usd_rate = _usd_rate(run)
    terms = settlement.terms_for(run)
    inputs, people = calculator.gather(
        company,
        run.period,
        usd_rate=run.usd_rate,
        member_ids=[member.pk],
        last_day=run.last_day,
        advances_in_full=True,
        unpaid_only=run.after_regular,
    )
    payslip = run.payslips.filter(membership=member).first()
    result = None
    if people:
        manual = list(payslip.lines.filter(kind=Kind.MANUAL)) if payslip is not None else []
        result = calculator.compute(people[0], inputs, manual_lines=manual, settlement=terms)
    if result is None:
        if payslip is not None:
            payslip.delete()
    else:
        _store(run, result, payslip, by)
    run.warnings = settlement.warnings(run, inputs, people, result, terms)
    run.calculated_at = timezone.now()
    run.totals = _totals(run)
    run.save(update_fields=["usd_rate", "warnings", "calculated_at", "totals", "updated_at"])
    return run


@transaction.atomic
def calculate_run(run: PayrollRun, *, by: Membership | None, usd_rate=None) -> PayrollRun:
    """Work every payslip of a draft run out again from today's data."""
    _require(by, Perm.PAYROLL_MANAGE)
    run = _lock(run)
    if run.status != Status.DRAFT:
        raise DomainError(_("Only a draft payroll can be calculated."))
    if usd_rate not in (None, ""):
        run.usd_rate = Decimal(str(usd_rate))
    run = _calculate(run, by=by)
    _audit(
        by,
        PayrollAction.RUN_CALCULATED,
        run,
        company_id=run.company_id,
        people=run.totals.get("people"),
        net=run.totals.get("net"),
    )
    _bump(run.company_id, PULSE_RUNS)
    return run


# Finalizing and reopening ---------------------------------------------------------------


@transaction.atomic
def finalize_run(run: PayrollRun, *, by: Membership | None) -> PayrollRun:
    """Calculate once more and freeze the month: setups, adjustments and repayments lock and
    the pay is booked in finance."""
    _require(by, Perm.PAYROLL_FINALIZE)
    run = _lock(run)
    if run.status != Status.DRAFT:
        raise DomainError(_("Only a draft payroll can be finalized."))
    run = _calculate(run, by=by)
    payslips = list(run.payslips.select_related("membership__home_branch", "run"))
    if not payslips:
        raise DomainError(_("There is nobody to pay in this payroll."))
    if run.is_final:
        # A final payslip may end below zero because every advance left is deducted: the
        # rest stays owed on the advance. Its pay itself never goes below zero.
        below = [p for p in payslips if finance_bridge.accrued_amount(p) < 0]
        if below:
            raise DomainError(
                _(
                    "The deductions on the final payslip of %(names)s are more than the pay: "
                    "lower a line added by hand."
                )
                % {"names": ", ".join(str(p.membership) for p in below)}
            )
    else:
        below = [p for p in payslips if p.net < 0]
        if below:
            raise DomainError(
                _("The pay of %(names)s is below zero: lower a deduction first.")
                % {"names": ", ".join(str(p.membership) for p in below)}
            )
    start, end = periods.bounds(run.period)
    if run.is_final and run.last_day is not None:
        end = run.last_day
    from apps.payroll.services import lock_pay

    for payslip in payslips:
        lock_pay(payslip.membership, start, end)
        lines = list(payslip.lines.all())
        Adjustment.objects.filter(
            pk__in=[line.adjustment_id for line in lines if line.adjustment_id]
        ).update(payslip=payslip)
        for line, taken in finance_bridge.advance_offsets(payslip, lines):
            if taken > 0:
                AdvanceRepayment.objects.create(
                    advance_id=line.advance_id,
                    amount=taken,
                    paid_on=finance_bridge.booked_on(run),
                    payslip_line=line,
                    created_by=by.user if by is not None else None,
                )
        finance_bridge.book_payslip(payslip, by=by)
    for advance in Advance.objects.filter(
        pk__in=PayslipLine.objects.filter(payslip__run=run, advance__isnull=False).values(
            "advance_id"
        )
    ).prefetch_related("repayments"):
        if queries.advance_left(advance) <= 0:
            advance.status = Advance.Status.REPAID
            advance.save(update_fields=["status", "updated_at"])
    finance_bridge.book_taxes(run, by=by)
    run.status = Status.FINALIZED
    run.finalized_at = timezone.now()
    run.finalized_by = by.user if by is not None else None
    run.totals = _totals(run)
    run.save(update_fields=["status", "finalized_at", "finalized_by", "totals", "updated_at"])
    _audit(
        by,
        PayrollAction.RUN_FINALIZED,
        run,
        company_id=run.company_id,
        people=run.totals.get("people"),
        net=run.totals.get("net"),
    )
    _bump(run.company_id, PULSE_RUNS, PULSE_PAY, PULSE_ADJUSTMENTS, PULSE_ADVANCES)
    return run


@transaction.atomic
def reopen_run(run: PayrollRun, *, by: Membership | None, reason: str = "") -> PayrollRun:
    """Back to a draft: the ledger rows are voided, reservations released, setups, adjustments
    and advances unlocked. Refused once a payslip is paid or a later month is finalized."""
    _require(by, Perm.PAYROLL_FINALIZE)
    run = _lock(run)
    if run.status != Status.FINALIZED:
        raise DomainError(_("Only a finalized payroll that isn't paid can be reopened."))
    if run.payslips.filter(status=Payslip.Status.PAID).exists():
        raise DomainError(_("Some payslips are paid already, so this payroll stays finalized."))
    later = PayrollRun.objects.for_company(run.company).filter(
        kind=PayrollRun.Kind.REGULAR,
        period__gt=run.period,
        status__in=(Status.FINALIZED, Status.PAID),
    )
    # A final settlement is nobody else's month: a later month doesn't hold it.
    if not run.is_final and later.exists():
        raise DomainError(_("A later month is finalized: reopen that one first."))
    finance_bridge.unbook_run(run, by=by)
    payslips = list(run.payslips.all())
    advance_ids = set(
        AdvanceRepayment.objects.filter(payslip_line__payslip__run=run).values_list(
            "advance_id", flat=True
        )
    )
    AdvanceRepayment.objects.filter(payslip_line__payslip__run=run).delete()
    Advance.objects.filter(pk__in=advance_ids, status=Advance.Status.REPAID).update(
        status=Advance.Status.PAID
    )
    Adjustment.objects.filter(payslip__run=run).update(payslip=None)
    Payslip.objects.filter(pk__in=[p.pk for p in payslips]).update(
        status=Payslip.Status.DRAFT, published_at=None
    )
    run.status = Status.DRAFT
    run.finalized_at = None
    run.finalized_by = None
    run.save(update_fields=["status", "finalized_at", "finalized_by", "updated_at"])
    from apps.payroll.services import unlock_pay

    unlock_pay(run.company)
    run.totals = _totals(run)
    run.save(update_fields=["totals"])
    _audit(
        by,
        PayrollAction.RUN_REOPENED,
        run,
        company_id=run.company_id,
        reason=(reason or "").strip()[:300],
    )
    _bump(run.company_id, PULSE_RUNS, PULSE_PAY, PULSE_ADJUSTMENTS, PULSE_ADVANCES)
    return run


@transaction.atomic
def cancel_run(run: PayrollRun, *, by: Membership | None, reason: str = "") -> PayrollRun:
    _require(by, Perm.PAYROLL_MANAGE)
    run = _lock(run)
    if run.status != Status.DRAFT:
        raise DomainError(_("Only a draft payroll can be cancelled. Reopen it first."))
    run.status = Status.CANCELLED
    run.save(update_fields=["status", "updated_at"])
    _audit(
        by,
        PayrollAction.RUN_CANCELLED,
        run,
        company_id=run.company_id,
        reason=(reason or "").strip()[:300],
    )
    _bump(run.company_id, PULSE_RUNS)
    return run


# Publishing and paying ------------------------------------------------------------------


def _chosen(run: PayrollRun, payslip_ids) -> list[Payslip]:
    payslips = run.payslips.select_related("membership__user", "salary_debt", "run")
    if payslip_ids is not None:
        wanted = set(payslip_ids)
        payslips = payslips.filter(pk__in=wanted)
        if payslips.count() != len(wanted):
            raise DomainError(_("Some of those payslips aren't in this payroll."))
    return list(payslips)


@transaction.atomic
def publish(run: PayrollRun, *, by: Membership | None, payslip_ids=None) -> list[Payslip]:
    """Show the payslips to their people (the employee bot sends each its payslip and PDF)."""
    _require(by, Perm.PAYROLL_FINALIZE)
    run = _lock(run)
    if run.status not in (Status.FINALIZED, Status.PAID):
        raise DomainError(_("Finalize the payroll before publishing it."))
    now = timezone.now()
    done = []
    for payslip in _chosen(run, payslip_ids):
        if payslip.published_at is not None:
            continue
        payslip.published_at = now
        if payslip.status == Payslip.Status.DRAFT:
            payslip.status = Payslip.Status.PUBLISHED
        payslip.save(update_fields=["published_at", "status", "updated_at"])
        done.append(payslip)
    if done:
        _audit(
            by,
            PayrollAction.PAYSLIPS_PUBLISHED,
            run,
            company_id=run.company_id,
            payslips=[p.pk for p in done],
        )
        notify.payslips_published([p.pk for p in done])
        transaction.on_commit(lambda: payslips_published.send(sender=PayrollRun, run=run))
        run.totals = _totals(run)
        run.save(update_fields=["totals", "updated_at"])
    _bump(run.company_id, PULSE_RUNS)
    return done


@transaction.atomic
def mark_paid(
    run: PayrollRun,
    *,
    by: Membership | None,
    payslip_ids,
    account: MoneyAccount,
    method: str = PayoutMethod.CASH,
    paid_on: date | None = None,
) -> list[Payslip]:
    """Pay the chosen payslips from `account` (finance books each payment). A payslip not
    published yet is published with it; once every payslip is paid, so is the run."""
    _require(by, Perm.PAYROLL_PAY)
    run = _lock(run)
    if run.status != Status.FINALIZED:
        raise DomainError(_("Only a finalized payroll can be paid."))
    if account.company_id != run.company_id:
        raise DomainError(_("That doesn't belong to this company."))
    if method not in PayoutMethod.values:
        raise DomainError(_("Pick how it was paid."))
    paid_on = paid_on or periods.today(run.company)
    now = timezone.now()
    done = []
    for payslip in _chosen(run, payslip_ids):
        if payslip.status == Payslip.Status.PAID:
            continue
        finance_bridge.pay_payslip(payslip, by=by, account=account, paid_on=paid_on)
        payslip.status = Payslip.Status.PAID
        payslip.paid_at = now
        payslip.paid_by = by.user if by is not None else None
        payslip.payout_method = method
        payslip.published_at = payslip.published_at or now
        payslip.save(
            update_fields=[
                "status",
                "paid_at",
                "paid_by",
                "payout_method",
                "published_at",
                "updated_at",
            ]
        )
        _audit(
            by,
            PayrollAction.PAYSLIPS_PAID,
            payslip.membership,
            company_id=run.company_id,
            payslip=payslip.pk,
            period=run.period.isoformat(),
            net=_money_text(payslip.net),
            method=method,
            account=account.pk,
        )
        done.append(payslip)
    if not run.payslips.exclude(status=Payslip.Status.PAID).exists():
        run.status = Status.PAID
        run.paid_at = now
        transaction.on_commit(lambda: run_paid.send(sender=PayrollRun, run=run))
    run.totals = _totals(run)
    run.save(update_fields=["status", "paid_at", "totals", "updated_at"])
    if done:
        notify.payslips_paid([p.pk for p in done])
    _bump(run.company_id, PULSE_RUNS, PULSE_PAY)
    return done


@transaction.atomic
def confirm_received(payslip: Payslip, *, by: Membership) -> Payslip:
    """The person taps "I received it"."""
    payslip = Payslip.objects.select_for_update(of=("self",)).get(pk=payslip.pk)
    if by.pk != payslip.membership_id:
        raise PermissionDenied(_("This isn't your payslip."))
    if payslip.status != Payslip.Status.PAID:
        raise DomainError(_("This pay isn't marked paid yet."))
    if payslip.received_at is None:
        payslip.received_at = timezone.now()
        payslip.save(update_fields=["received_at", "updated_at"])
        _audit(
            by,
            PayrollAction.PAYSLIP_RECEIVED,
            payslip.membership,
            company_id=payslip.company_id,
            payslip=payslip.pk,
        )
        _bump(payslip.company_id, PULSE_RUNS)
    return payslip


def mark_viewed(payslip: Payslip, *, by: Membership) -> Payslip:
    """The person opened their payslip (first time only)."""
    if by.pk == payslip.membership_id and payslip.viewed_at is None:
        payslip.viewed_at = timezone.now()
        Payslip.objects.filter(pk=payslip.pk, viewed_at__isnull=True).update(
            viewed_at=payslip.viewed_at
        )
    return payslip


# Lines added by hand --------------------------------------------------------------------


@transaction.atomic
def set_manual_lines(payslip: Payslip, *, by: Membership | None, lines: list[dict]) -> Payslip:
    """Replace the hand-made lines of a draft payslip (`[{"id"?, "label", "amount"}]`, signed
    amounts) and work the payslip out again."""
    _require(by, Perm.PAYROLL_MANAGE)
    run = _lock(payslip.run)
    if run.status != Status.DRAFT:
        raise DomainError(_("Lines can be added only while the payroll is a draft."))
    if len(lines) > MAX_MANUAL_LINES:
        raise DomainError(_("At most %(count)s at a time.") % {"count": MAX_MANUAL_LINES})
    current = {line.pk: line for line in payslip.lines.filter(kind=Kind.MANUAL)}
    keep = set()
    added = removed = 0
    for order, item in enumerate(lines):
        label = (item.get("label") or "").strip()[:200]
        if not label:
            raise DomainError(_("Write what the line is for."))
        try:
            amount = Decimal(str(item.get("amount"))).quantize(Decimal("0.01"))
        except Exception:
            raise DomainError(_("Enter an amount of money.")) from None
        if not amount.is_finite() or amount == 0 or abs(amount) > Decimal("999999999999"):
            raise DomainError(_("Enter an amount of money."))
        line = current.get(item.get("id")) if item.get("id") else None
        if line is not None:
            line.label, line.amount, line.order = label, amount, 1000 + order
            line.save(update_fields=["label", "amount", "order"])
            keep.add(line.pk)
        else:
            PayslipLine.objects.create(
                payslip=payslip,
                kind=Kind.MANUAL,
                label=label,
                amount=amount,
                params={"code": "manual"},
                order=1000 + order,
                created_by=by.user if by is not None else None,
            )
            added += 1
    for pk, line in current.items():
        if pk not in keep:
            line.delete()
            removed += 1
    _calculate(run, by=by, member_ids=[payslip.membership_id])
    if added:
        _audit(
            by,
            PayrollAction.PAYSLIP_LINE_ADDED,
            payslip,
            company_id=payslip.company_id,
            count=added,
        )
    if removed:
        _audit(
            by,
            PayrollAction.PAYSLIP_LINE_REMOVED,
            payslip,
            company_id=payslip.company_id,
            count=removed,
        )
    _bump(payslip.company_id, PULSE_RUNS)
    return Payslip.objects.get(pk=payslip.pk)
