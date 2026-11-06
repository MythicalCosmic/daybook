"""The final settlement of someone who leaves (docs/PLAN-OWNER.md §3.17, §1.8).

The offboarding wizard shows payroll's step (`offboard_step`, payroll.manage only, amounts
included): the final payslip worked out as if today were the last day, the switch "Prepare the
final payslip" (on for anyone with a pay setup) and the unused leave days to pay out (HR counts
them: leave balances aren't kept yet). Once the person has left, `on_member_left` prepares a
draft `PayrollRun(kind=final)` for the leaving month, worked out through the last working day,
and payroll managers hear about it. It is finalized, published and paid like a monthly run
(`apps.payroll.runs`).

- The month's regular run skips the person. When that run had already paid their month (it
  was finalized with their payslip), the final run pays only the unused leave and what is
  still open (`after_regular`), and says how much the month paid after the last day.
- Unused leave is paid at the average day's pay `a` (`average_day`): the pay for work on the
  regular payslips of the last `leave_payout_months` months before the leaving month (base,
  overtime, holiday and night work, piecework, allowances, paid leave; no one-off bonuses,
  expenses or leave payouts) over the calendar days employed in them, or over the days paid
  when leave counts in working days. Without one fully employed month among them, `a` is the
  current monthly pay over the month's days (or its working days). The method is a setting
  and must be confirmed by a local accountant.
- Every advance left is deducted in full (the deductions cap is for fines only). When that
  takes the net below zero, the rest stays owed on the advance in Finance: a receivable.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import formats
from django.utils.translation import gettext as _

from apps.console.registry import FieldSpec, OffboardStep
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import person_ref
from apps.payroll import calculator, conf, notify, periods, queries, runs
from apps.payroll.audit_actions import PayrollAction
from apps.payroll.models import LeaveUnit, PayrollRun, Payslip, PayslipLine

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
Kind = PayslipLine.Kind
Status = PayrollRun.Status
FEATURE = "payroll"
GONE = (Membership.Status.LEFT, Membership.Status.BLOCKED)
MAX_DAYS = Decimal(366)

# The pay for work an average day is made of (§3.17): not one-off bonuses and task rewards,
# expenses paid back, leave payouts or lines added by hand.
AVERAGE_KINDS = (
    Kind.BASE,
    Kind.PRORATION,
    Kind.OVERTIME,
    Kind.HOLIDAY_WORK,
    Kind.NIGHT_WORK,
    Kind.PIECE,
    Kind.ALLOWANCE,
    Kind.LEAVE_COMPENSATION,
)


def clean_days(value) -> Decimal:
    """Unused leave days as entered ("5,5", 5.5, "0"): 0 to 366, to the hundredth."""
    if value in (None, ""):
        return ZERO
    try:
        days = Decimal(str(value).strip().replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation, ValueError:
        raise DomainError(_("Enter the unused leave days: a number from 0 to 366.")) from None
    if not days.is_finite() or days < 0 or days > MAX_DAYS:
        raise DomainError(_("Enter the unused leave days: a number from 0 to 366."))
    return days


def _text(value: Decimal) -> str:
    return f"{value:.2f}"


# The average day ---------------------------------------------------------------------------


def average_day(
    membership: Membership, period: date, *, last_day: date
) -> tuple[Decimal | None, dict]:
    """`a` for unused leave paid out in `period` (exact), and how it was found (line params)."""
    from apps.hr.queries import employment_dates

    company = membership.company
    settings = conf.get_settings(company)
    months = settings.leave_payout_months
    unit = settings.leave_payout_unit
    hired, left = employment_dates(company, [membership.pk]).get(membership.pk, (None, None))
    payslips = (
        Payslip.objects.filter(
            company=company,
            membership=membership,
            currency=settings.currency,
            run__kind=PayrollRun.Kind.REGULAR,
            run__status__in=queries.DONE_STATUSES,
            run__period__gte=periods.add_months(period, -months),
            run__period__lt=period,
        )
        .select_related("run")
        .prefetch_related("lines")
        .order_by("run__period")
    )
    gross = days = ZERO
    used = full = 0
    for payslip in payslips:
        start, end = periods.bounds(payslip.run.period)
        first = max(start, hired or start)
        last = min(end, left or end)
        employed_days = (last - first).days + 1 if first <= last else 0
        count = Decimal(employed_days) if unit == LeaveUnit.CALENDAR else payslip.paid_days
        if count <= 0:
            continue
        used += 1
        full += employed_days == (end - start).days + 1
        days += count
        gross += _sum(payslip.lines.all(), AVERAGE_KINDS)
    params = {"unit": unit, "months": months}
    if full and days > 0 and gross > 0:
        return gross / days, params | {
            "basis": "history",
            "history_months": used,
            "history_gross": _text(gross),
            "history_days": _text(days),
        }
    monthly = queries.monthly_pay(membership, on=last_day)
    if not monthly or monthly <= 0:
        return None, params | {"basis": "none"}
    if unit == LeaveUnit.CALENDAR:
        divisor = Decimal((periods.last_day(period) - period).days + 1)
    else:
        divisor = Decimal(queries.plain_scheduled_days(company, period))
    if divisor <= 0:
        return None, params | {"basis": "none"}
    return monthly / divisor, params | {
        "basis": "current_pay",
        "monthly": _text(monthly),
        "divisor": _text(divisor),
    }


def regular_paid(company, period: date, membership: Membership) -> bool:
    """Whether the month's regular run is finalized (or paid) with a payslip of theirs."""
    run = queries.regular_run(company, period)
    return (
        run is not None
        and run.status in queries.DONE_STATUSES
        and run.payslips.filter(membership=membership).exists()
    )


def terms(
    membership: Membership,
    *,
    period: date,
    last_day: date,
    leave_days: Decimal,
    work_paid: bool,
) -> calculator.Settlement:
    day_value, day_params = average_day(membership, period, last_day=last_day)
    return calculator.Settlement(
        last_day=last_day,
        leave_days=leave_days,
        day_value=day_value,
        day_params=day_params,
        work_paid=work_paid,
    )


def terms_for(run: PayrollRun) -> calculator.Settlement:
    return terms(
        run.membership,
        period=run.period,
        last_day=run.last_day or periods.last_day(run.period),
        leave_days=run.leave_days,
        work_paid=run.after_regular,
    )


# The run's warnings --------------------------------------------------------------------------


def warnings(run: PayrollRun, inputs, people, result, settlement) -> list[dict]:
    """What a final run's reader should know, about its one person."""
    from apps.attendance import queries as attendance
    from apps.attendance.models import AttendanceRecord

    member = run.membership
    ref = person_ref(member)
    found: list[dict] = []
    if result is None:
        found.append({"code": "no_pay_setup", "level": "warning", "member": ref})
    else:
        for warning in result.warnings:
            found.append({"level": "warning", **warning, "member": ref})
        outside = (Kind.ADVANCE, Kind.REIMBURSEMENT)
        accrued = sum((line.amount for line in result.lines if line.kind not in outside), ZERO)
        net = sum((line.amount for line in result.lines), ZERO)
        if accrued < 0:
            found.append({"code": "negative_net", "level": "error", "member": ref})
        elif net < 0:
            found.append(
                {
                    "code": "owes",
                    "level": "info",
                    "member": ref,
                    "amount": _text(-net),
                    "currency": inputs.currency,
                }
            )
    if settlement.leave_days > 0:
        basis = settlement.day_params.get("basis")
        if basis == "none":
            found.append({"code": "leave_no_basis", "level": "warning", "member": ref})
        elif basis == "current_pay":
            found.append({"code": "leave_current_pay", "level": "info", "member": ref})
    if run.after_regular:
        month = run.period.isoformat()
        found.append({"code": "after_regular", "level": "info", "member": ref, "month": month})
        found += _paid_after_last_day(run, inputs, people, ref)
    found += _paid_in_later_months(run, ref)
    start = run.period
    proposed = queries.open_proposals(run.company).filter(membership=member, period=start)
    if count := proposed.count():
        found.append({"code": "proposed", "level": "warning", "count": count})
    disputes = queries.open_disputes(run.company).filter(membership=member, period=start)
    if count := disputes.count():
        found.append({"code": "disputes", "level": "warning", "count": count})
    last = run.last_day or periods.last_day(start)
    records = attendance.records_between(run.company, start, last, branch_ids=None).filter(
        membership=member
    )
    if count := records.filter(overtime_status=AttendanceRecord.Overtime.PENDING).count():
        found.append({"code": "pending_overtime", "level": "warning", "count": count})
    return found


def _paid_after_last_day(run: PayrollRun, inputs, people, ref) -> list[dict]:
    """How much more the month's regular payslip paid them than their work through the last day
    earns (it was worked out while they still worked here)."""
    regular = (
        Payslip.objects.filter(
            membership=run.membership,
            run__kind=PayrollRun.Kind.REGULAR,
            run__period=run.period,
            run__status__in=queries.DONE_STATUSES,
        )
        .select_related("run")
        .first()
    )
    if regular is None or not people:
        return []
    work = calculator.compute(people[0], inputs)
    if work is None:
        return []
    earned = sum(
        (line.amount for line in work.lines if line.kind in (Kind.BASE, Kind.PRORATION)), ZERO
    )
    extra = regular.base_pay - earned
    if extra <= 0:
        return []
    return [
        {
            "code": "paid_after_last_day",
            "level": "warning",
            "member": ref,
            "amount": _text(extra),
            "currency": inputs.currency,
            "days": _text(max(ZERO, regular.paid_days - work.paid_days)),
            "month": run.period.isoformat(),
        }
    ]


def _paid_in_later_months(run: PayrollRun, ref) -> list[dict]:
    """Months after the leaving one whose regular run paid them as if they still worked here
    (the leaving was written down late): all of that month's pay for days came after the last
    day."""
    later = (
        Payslip.objects.filter(
            membership=run.membership,
            run__kind=PayrollRun.Kind.REGULAR,
            run__period__gt=run.period,
            run__status__in=queries.DONE_STATUSES,
            base_pay__gt=0,
        )
        .select_related("run")
        .order_by("run__period")
    )
    return [
        {
            "code": "paid_after_last_day",
            "level": "warning",
            "member": ref,
            "amount": _text(payslip.base_pay),
            "currency": payslip.currency,
            "days": _text(payslip.paid_days),
            "month": payslip.run.period.isoformat(),
        }
        for payslip in later
    ]


# The preview in the offboarding wizard ---------------------------------------------------------


def preview(membership: Membership, *, last_day: date, leave_days: Decimal = ZERO):
    """The final payslip as it would be worked out today, written nowhere:
    (result or None, settlement terms, inputs)."""
    company = membership.company
    period = periods.first_day(last_day)
    work_paid = regular_paid(company, period, membership)
    settlement = terms(
        membership, period=period, last_day=last_day, leave_days=leave_days, work_paid=work_paid
    )
    draft = PayrollRun(company=company, period=period, kind=PayrollRun.Kind.FINAL)
    inputs, people = calculator.gather(
        company,
        period,
        usd_rate=runs._usd_rate(draft),
        member_ids=[membership.pk],
        last_day=last_day,
        advances_in_full=True,
        unpaid_only=work_paid,
    )
    if not people:
        return None, settlement, inputs
    manual = list(
        PayslipLine.objects.filter(
            kind=Kind.MANUAL,
            payslip__membership=membership,
            payslip__run__kind=PayrollRun.Kind.REGULAR,
            payslip__run__status=Status.DRAFT,
            payslip__run__period=period,
        )
    )
    result = calculator.compute(people[0], inputs, manual_lines=manual, settlement=settlement)
    return result, settlement, inputs


def _sum(lines, kinds) -> Decimal:
    return sum((line.amount for line in lines if line.kind in kinds), ZERO)


def _manual(lines, *, positive: bool) -> Decimal:
    """Lines added by hand that pay (`positive`) or take money."""
    return sum(
        (
            line.amount
            for line in lines
            if line.kind == Kind.MANUAL and (line.amount > 0 if positive else line.amount < 0)
        ),
        ZERO,
    )


def offboard_step(membership: Membership) -> OffboardStep:
    """Payroll's step of the offboarding wizard (payroll.manage holders only: it shows pay)."""
    company = membership.company
    today = periods.today(company)
    existing = (
        PayrollRun.objects.filter(membership=membership, kind=PayrollRun.Kind.FINAL)
        .exclude(status=Status.CANCELLED)
        .first()
    )
    if existing is not None:
        return OffboardStep(
            lines=[
                _("Their final payslip already exists (%(month)s).")
                % {"month": queries.month_label(existing.period)}
            ],
            blockers=[],
            fields=[],
            defaults={"prepare": False},
        )
    if queries.compensation(membership, on=today) is None:
        return OffboardStep(
            lines=[_("No pay setup: payroll has nothing to settle.")],
            blockers=[],
            fields=[],
            defaults={"prepare": False},
        )
    result, settlement, inputs = preview(membership, last_day=today)
    currency = inputs.currency

    def money(value: Decimal) -> str:
        return queries.money_text(value, currency)

    lines = [
        _(
            "Worked out as if today (%(date)s) were the last day: the final payslip follows the "
            "last day you pick."
        )
        % {"date": formats.date_format(today, "d.m.Y")}
    ]
    if result is not None:
        rows = result.lines
        if settlement.work_paid:
            lines.append(
                _(
                    "The %(month)s payroll has paid their month already: the final payslip pays "
                    "the unused leave and what is still open."
                )
                % {"month": queries.month_label(inputs.period)}
            )
        else:
            base = _sum(rows, (Kind.BASE, Kind.PRORATION))
            if result.pay_type == "monthly" and result.scheduled_days:
                lines.append(
                    _("Pay for %(paid)s of %(scheduled)s working days: %(amount)s")
                    % {
                        "paid": result.paid_days.normalize(),
                        "scheduled": result.scheduled_days,
                        "amount": money(base),
                    }
                )
            else:
                lines.append(_("Pay for work this month: %(amount)s") % {"amount": money(base)})
        other = _sum(
            rows,
            (
                Kind.OVERTIME,
                Kind.HOLIDAY_WORK,
                Kind.NIGHT_WORK,
                Kind.PIECE,
                Kind.TASK_REWARD,
                Kind.BONUS,
                Kind.ALLOWANCE,
                Kind.LEAVE_COMPENSATION,
            ),
        ) + _manual(rows, positive=True)
        if other:
            lines.append(_("Bonuses and other pay: %(amount)s") % {"amount": money(other)})
        fines = _sum(rows, (Kind.FINE, Kind.DEDUCTION)) + _manual(rows, positive=False)
        if fines:
            lines.append(_("Fines and deductions: %(amount)s") % {"amount": money(fines)})
        advances = _sum(rows, (Kind.ADVANCE,))
        if advances:
            lines.append(_("Advances deducted in full: %(amount)s") % {"amount": money(advances)})
        net = sum((line.amount for line in rows), ZERO)
        if net < 0:
            lines.append(
                _("They would owe %(amount)s: it stays as a debt in Finance.")
                % {"amount": money(-net)}
            )
        else:
            lines.append(_("To be paid before unused leave: %(amount)s") % {"amount": money(net)})
    if settlement.day_value is not None:
        day = money(calculator.money(settlement.day_value))
        basis = settlement.day_params.get("basis")
        if basis == "history":
            lines.append(
                _(
                    "Each unused leave day pays %(amount)s: the average day's pay of the last "
                    "%(months)s months."
                )
                % {"amount": day, "months": settlement.day_params["months"]}
            )
        else:
            lines.append(
                _(
                    "Each unused leave day pays %(amount)s: their monthly pay over the month's "
                    "days (less than a full month of pay history)."
                )
                % {"amount": day}
            )
    fields = [
        FieldSpec(
            name="prepare",
            label=_("Prepare the final payslip"),
            kind="bool",
            help=_("A draft payslip through the last day, for payroll managers to check and pay."),
        ),
        FieldSpec(
            name="leave_days",
            label=_("Unused leave days to pay out"),
            kind="number",
            help=_(
                "Count them from their leave records; 0 when none. Payroll can change it on "
                "the draft."
            ),
        ),
    ]
    return OffboardStep(
        lines=lines, blockers=[], fields=fields, defaults={"prepare": True, "leave_days": 0}
    )


# Creating and changing a final run --------------------------------------------------------------


@transaction.atomic
def create_final_run(
    membership: Membership,
    *,
    by: Membership | None,
    last_day: date | None = None,
    leave_days=ZERO,
    actor: Membership | None = None,
) -> PayrollRun:
    """A draft final settlement of someone who left, calculated at once; payroll managers
    hear about it. `by=None` is the system (the offboarding wizard's answer, made by `actor`)."""
    from apps.hr.queries import employment_dates

    runs._require(by, Perm.PAYROLL_MANAGE)
    company = membership.company
    if membership.status not in GONE:
        raise DomainError(_("A final payslip is only for someone who has left."))
    if last_day is None:
        last_day = employment_dates(company, [membership.pk]).get(membership.pk, (None, None))[1]
    last_day = last_day or periods.today(company)
    leave_days = clean_days(leave_days)
    period = periods.first_day(last_day)
    if not queries.in_force([membership.pk], period, last_day):
        raise DomainError(
            _("%(name)s has no pay setup for %(month)s.")
            % {"name": membership, "month": queries.month_label(period)}
        )
    regular = (
        PayrollRun.objects.select_for_update()
        .filter(company=company, kind=PayrollRun.Kind.REGULAR, period=period)
        .exclude(status=Status.CANCELLED)
        .first()
    )
    work_paid = (
        regular is not None
        and regular.is_locked
        and regular.payslips.filter(membership=membership).exists()
    )
    maker = by or actor
    try:
        with transaction.atomic():
            run = PayrollRun.objects.create(
                company=company,
                kind=PayrollRun.Kind.FINAL,
                period=period,
                membership=membership,
                last_day=last_day,
                leave_days=leave_days,
                after_regular=work_paid,
                created_by=maker.user if maker is not None else None,
            )
    except IntegrityError:
        raise DomainError(
            _("There is already a final payslip for %(name)s.") % {"name": membership}
        ) from None
    run = runs._calculate(run, by=by)
    # Their draft payslip in the month's regular run moves here, with the lines added by hand.
    if regular is not None and regular.status == Status.DRAFT:
        old = regular.payslips.filter(membership=membership).first()
        if old is not None:
            final = run.payslips.first()
            manual = old.lines.filter(kind=Kind.MANUAL)
            if final is not None and manual.exists():
                manual.update(payslip=final)
                run = runs._calculate(run, by=by)
            old.delete()
            regular.totals = runs._totals(regular)
            regular.save(update_fields=["totals", "updated_at"])
    runs._audit(
        maker,
        PayrollAction.FINAL_RUN_CREATED,
        run,
        company_id=company.pk,
        member=membership.pk,
        last_day=last_day.isoformat(),
        leave_days=_text(leave_days),
        after_regular=work_paid,
    )
    notify.final_run_prepared(run)
    runs._bump(company.pk, runs.PULSE_RUNS)
    return run


@transaction.atomic
def set_leave_days(run: PayrollRun, *, by: Membership | None, leave_days) -> PayrollRun:
    """Change the unused leave days a draft final run pays out, and calculate it again."""
    runs._require(by, Perm.PAYROLL_MANAGE)
    run = runs._lock(run)
    if not run.is_final:
        raise DomainError(_("Only a final payslip pays out unused leave."))
    if run.status != Status.DRAFT:
        raise DomainError(_("Only a draft payroll can be calculated."))
    before = run.leave_days
    run.leave_days = clean_days(leave_days)
    run.save(update_fields=["leave_days", "updated_at"])
    run = runs._calculate(run, by=by)
    if run.leave_days != before:
        runs._audit(
            by,
            PayrollAction.LEAVE_PAYOUT_CHANGED,
            run,
            company_id=run.company_id,
            before=_text(before),
            after=_text(run.leave_days),
        )
    runs._bump(run.company_id, runs.PULSE_RUNS)
    return run


# member_left -------------------------------------------------------------------------------------


def on_member_left(
    sender, membership, reason=None, by=None, details=None, terminated_on=None, **kwargs
) -> None:
    """The wizard's answer: with "Prepare the final payslip" on, the draft final run."""
    if not membership.company.has_feature(FEATURE):
        return
    answer = (details or {}).get("payroll") or {}
    if not isinstance(answer, dict) or not answer.get("prepare"):
        return
    try:
        days = clean_days(answer.get("leave_days"))
    except DomainError:
        logger.warning("final settlement of %s: unreadable leave days", membership.pk)
        days = ZERO
    try:
        create_final_run(membership, by=None, last_day=terminated_on, leave_days=days, actor=by)
    except DomainError as exc:
        logger.warning("final settlement of %s not prepared: %s", membership.pk, exc)
