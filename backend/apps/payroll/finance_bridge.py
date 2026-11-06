"""How payroll books into the finance ledger (docs/PLAN-OWNER.md §3.13), through the finance
contract only (`open_debt`, `pay_debt`, `lock_debt`, `unlock_debt`, `cancel_debt`,
`void_transaction`). A plain module `apps.payroll.runs` calls.

Finalizing a payslip:
- the pay it earned (everything but the advances it takes back and the expenses it pays back)
  is accrued: a payable `salary` debt to the person, booked as a "salaries" expense
  (source `("payroll.payslip", id, "accrued")`);
- each advance it takes back is an offset on both debts, moving no money: the advance
  receivable is settled (`"adv<id>"`) and the salary payable by the same amount (`"off<id>"`);
- each reimbursement it pays back is reserved for it (`lock_debt`).
Taxes (when switched on) are payables to the tax office, per run (`("payroll.run", id, …)`).
Marking a payslip paid pays what is left of its salary debt and its reserved reimbursements
from one account. Reopening voids every row the run booked and releases its reservations, so
finalizing again books exactly the same rows once more (voided rows free their sources).
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.finance import services as finance
from apps.finance.models import Counterparty, Debt, Transaction
from apps.finance.sources import Source
from apps.payroll import periods, queries
from apps.payroll.models import PayrollRun, Payslip, PayslipLine

PAYSLIP = "payroll.payslip"
RUN = "payroll.run"
ZERO = Decimal(0)
Kind = PayslipLine.Kind
OUTSIDE_ACCRUAL = (Kind.ADVANCE, Kind.REIMBURSEMENT)


def accrued_amount(payslip: Payslip, lines=None) -> Decimal:
    """What the month's work is worth after fines and withheld taxes: the salary payable."""
    lines = lines if lines is not None else list(payslip.lines.all())
    return sum((line.amount for line in lines if line.kind not in OUTSIDE_ACCRUAL), ZERO)


def advance_offsets(payslip: Payslip, lines=None) -> list[tuple[PayslipLine, Decimal]]:
    """(advance line, what it really takes back) in line order: everything the payslip owes the
    person (the salary payable, then the expenses it pays back) covers the advances. A regular
    payslip always covers them in full; a final one deducts every advance left in full, and
    what its pay can't cover stays owed on the advance (the negative net, a receivable)."""
    lines = lines if lines is not None else list(payslip.lines.all())
    cover = max(accrued_amount(payslip, lines), ZERO) + sum(
        (line.amount for line in lines if line.kind == Kind.REIMBURSEMENT), ZERO
    )
    found = []
    for line in lines:
        if line.kind == Kind.ADVANCE and line.advance_id is not None:
            taken = min(-line.amount, max(cover, ZERO))
            cover -= taken
            found.append((line, taken))
    return found


def booked_on(run: PayrollRun) -> date:
    """The day a run's pay is accrued: the month's last day, a final settlement's last day."""
    if run.kind == PayrollRun.Kind.FINAL and run.last_day is not None:
        return run.last_day
    return periods.last_day(run.period)


def book_payslip(payslip: Payslip, *, by) -> None:
    lines = list(payslip.lines.select_related("advance__debt", "debt").order_by("order", "pk"))
    company = payslip.company
    member = payslip.membership
    run = payslip.run
    month = queries.month_label(run.period)
    issued_on = booked_on(run)
    accrued = accrued_amount(payslip, lines)
    if accrued < 0:
        raise DomainError(
            _("The pay of %(name)s is below zero: lower a deduction first.") % {"name": member}
        )
    if run.kind == PayrollRun.Kind.FINAL:
        description = _("Final settlement for %(month)s: %(name)s")
    else:
        description = _("Salary for %(month)s: %(name)s")
    salary = None
    if accrued > 0:
        salary = finance.open_debt(
            company,
            by=by,
            direction=Debt.Direction.PAYABLE,
            kind=Debt.Kind.SALARY,
            amount=accrued,
            currency=payslip.currency,
            issued_on=issued_on,
            membership=member,
            category="salaries",
            branch=member.home_branch,
            description=description % {"month": month, "name": member},
            source=Source(PAYSLIP, payslip.pk, "accrued"),
        )
    payslip.salary_debt = salary
    payslip.save(update_fields=["salary_debt", "updated_at"])
    # Expenses paid back are reserved first: a final payslip may offset an advance against them.
    reimbursements = []
    for line in lines:
        if line.kind == Kind.REIMBURSEMENT and line.debt_id is not None:
            debt = line.debt
            if debt.status != Debt.Status.OPEN or debt.amount - debt.paid != line.amount:
                raise DomainError(
                    _(
                        "An expense of %(name)s was paid back another way meanwhile: "
                        "calculate the run again."
                    )
                    % {"name": member}
                )
            finance.lock_debt(debt, source=Source(PAYSLIP, payslip.pk))
            reimbursements.append([debt, line.amount])
    salary_left = accrued
    for line, taken in advance_offsets(payslip, lines):
        if taken <= 0:
            continue
        debt = line.advance.debt
        paid_on = max(issued_on, debt.issued_on)
        finance.pay_debt(
            debt,
            by=by,
            amount=taken,
            paid_on=paid_on,
            source=Source(PAYSLIP, payslip.pk, f"adv{line.advance_id}"),
        )
        from_salary = min(taken, salary_left)
        if from_salary > 0:
            finance.pay_debt(
                salary,
                by=by,
                amount=from_salary,
                paid_on=max(paid_on, salary.issued_on),
                source=Source(PAYSLIP, payslip.pk, f"off{line.advance_id}"),
            )
            salary_left -= from_salary
        rest = taken - from_salary
        for item in reimbursements:
            if rest <= 0:
                break
            expense, left = item
            share = min(rest, left)
            if share <= 0:
                continue
            finance.pay_debt(
                expense,
                by=by,
                amount=share,
                paid_on=max(paid_on, expense.issued_on),
                source=Source(PAYSLIP, payslip.pk, f"rof{line.advance_id}-{expense.pk}"),
            )
            item[1] = left - share
            rest -= share
        if rest > 0:
            raise DomainError(_("The pay of %(name)s can't cover the advance.") % {"name": member})


def _tax_office(company, by) -> Counterparty:
    with translation.override(company.default_language or "uz"):
        name = _("Tax office")
    found = (
        Counterparty.objects.for_company(company)
        .filter(kind=Counterparty.Kind.STATE, name=name)
        .first()
    )
    if found is not None:
        return found
    if by is None:
        raise DomainError(_("Add the tax office to the counterparties first."))
    return finance.create_counterparty(company, by=by, name=name, kind=Counterparty.Kind.STATE)


def tax_totals(run: PayrollRun) -> dict:
    """Taxes of a run's payslips: what was withheld (gross pay) or is paid on top (net pay)
    for income tax and the pension contribution, and the employer's social tax."""
    withheld = employee = social = ZERO
    for payslip in run.payslips.all():
        taxes = payslip.taxes or {}
        if not taxes:
            continue
        own = Decimal(taxes.get("income_tax", "0")) + Decimal(taxes.get("inps", "0"))
        if taxes.get("withheld"):
            withheld += own
        else:
            employee += own
        social += Decimal(taxes.get("social_tax", "0"))
    return {"withheld": withheld, "on_top": employee, "social": social}


def book_taxes(run: PayrollRun, *, by) -> None:
    totals = tax_totals(run)
    if not any(totals.values()):
        return
    company = run.company
    office = _tax_office(company, by)
    issued_on = booked_on(run)
    month = queries.month_label(run.period)
    currency = run.payslips.values_list("currency", flat=True).first()
    parts = (
        ("withheld", totals["withheld"], "salaries", _("Income tax and pension withheld")),
        ("on_top", totals["on_top"], "payroll_taxes", _("Income tax and pension on pay")),
        ("social", totals["social"], "payroll_taxes", _("Social tax")),
    )
    for key, amount, category, label in parts:
        if amount <= 0:
            continue
        finance.open_debt(
            company,
            by=by,
            direction=Debt.Direction.PAYABLE,
            kind=Debt.Kind.TAX,
            amount=amount,
            currency=currency,
            issued_on=issued_on,
            counterparty=office,
            category=category,
            description=f"{label}: {month}",
            source=Source(RUN, run.pk, f"tax_{key}"),
        )


def paid_elsewhere(run: PayrollRun):
    """Live rows on the run's salary debts that payroll didn't book: money paid out (or
    written off) in Finance, Debts. Cancelling the debts would void them, as if that money
    never left the till."""
    debts = [debt for debt in run.payslips.values_list("salary_debt_id", flat=True) if debt]
    return Transaction.objects.filter(
        company_id=run.company_id, debt_id__in=debts, status__in=("posted", "pending")
    ).exclude(source_type=PAYSLIP)


def unbook_run(run: PayrollRun, *, by) -> None:
    """Void every ledger row the run booked and release what it reserved. Refused while part
    of a salary was paid or written off in Finance: that has to be voided there first."""
    if paid_elsewhere(run).exists():
        raise DomainError(
            _(
                "Part of this pay was already paid or written off in Finance. Void that "
                "payment first, then reopen the payroll."
            )
        )
    reason = _("Payroll for %(month)s reopened") % {"month": queries.month_label(run.period)}
    payslips = list(run.payslips.select_related("salary_debt"))
    for payslip in payslips:
        # Advance offsets settle the advances' receivables (and, on a final payslip, part of
        # the expenses it paid back): voiding reopens them.
        offsets = Transaction.objects.filter(
            Q(source_key__startswith="adv") | Q(source_key__startswith="rof"),
            company_id=run.company_id,
            source_type=PAYSLIP,
            source_id=payslip.pk,
            status__in=("posted", "pending"),
        )
        for row in offsets.order_by("pk"):
            finance.void_transaction(row, by=by, reason=reason)
        if payslip.salary_debt is not None and payslip.salary_debt.status != Debt.Status.CANCELLED:
            finance.cancel_debt(payslip.salary_debt, by=by, reason=reason)
        for debt in Debt.objects.filter(
            company_id=run.company_id, locked_by_type=PAYSLIP, locked_by_id=payslip.pk
        ):
            finance.unlock_debt(debt, source=Source(PAYSLIP, payslip.pk))
        payslip.salary_debt = None
        payslip.save(update_fields=["salary_debt", "updated_at"])
    for debt in Debt.objects.filter(
        company_id=run.company_id, source_type=RUN, source_id=run.pk
    ).exclude(status=Debt.Status.CANCELLED):
        if debt.paid:
            raise DomainError(
                _("Taxes of this payroll were already paid: void that payment first.")
            )
        finance.cancel_debt(debt, by=by, reason=reason)


def pay_payslip(payslip: Payslip, *, by, account, paid_on: date) -> None:
    """Pay what is left of the salary debt and the reserved reimbursements from `account`."""
    if account.currency != payslip.currency:
        raise DomainError(
            _("%(account)s holds %(currency)s.")
            % {"account": account, "currency": account.currency}
        )
    salary = payslip.salary_debt
    if salary is not None:
        salary.refresh_from_db()
        left = salary.amount - salary.paid
        if left > 0:
            finance.pay_debt(
                salary,
                by=by,
                amount=left,
                paid_on=max(paid_on, salary.issued_on),
                account=account,
                source=Source(PAYSLIP, payslip.pk, "paid"),
            )
    for line in payslip.lines.filter(kind=Kind.REIMBURSEMENT, debt__isnull=False).select_related(
        "debt"
    ):
        debt = line.debt
        if debt.status != Debt.Status.OPEN:
            continue
        finance.pay_debt(
            debt,
            by=by,
            amount=debt.amount - debt.paid,
            paid_on=max(paid_on, debt.issued_on),
            account=account,
            source=Source(PAYSLIP, payslip.pk, f"r{debt.pk}"),
        )


def live_rows(run: PayrollRun):
    """The run's ledger rows still standing (for checks and tests)."""
    ids = list(run.payslips.values_list("pk", flat=True))
    return Transaction.objects.filter(
        Q(source_type=PAYSLIP, source_id__in=ids) | Q(source_type=RUN, source_id=run.pk),
        company_id=run.company_id,
        status__in=("posted", "pending"),
    )


def booked_total(run: PayrollRun) -> Decimal:
    return live_rows(run).aggregate(total=Sum("base_amount"))["total"] or ZERO
