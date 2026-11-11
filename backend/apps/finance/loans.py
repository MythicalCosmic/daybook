"""Loans and instalments (v12, the owner's feature 5): a loan taken from a bank (or given to
someone), its repayment schedule with interest, payments split into principal and interest, early
repayment, and what is due or overdue.

A loan is an ordinary `Debt` of kind `loan` (payable when taken, receivable when given) plus its
terms (`Loan`). The debt holds the principal, so everything that reads debts (the debts page, the
balance sheet, the payables list) keeps working; its `DebtInstallment`s are the schedule, each with
its principal (`amount`) and `interest`. The schedule is made by `loan_math` from the terms, or
typed from the bank's own schedule, and can be changed freely until the first payment.

Paying an instalment books one payment in two rows on the same account and day:
- the principal: a debt payment (`services.pay_debt`), which only lowers what is owed and is
  never an expense;
- the interest: an expense "Loan interest" (an income "Interest received" on a loan given),
  linked to the loan's debt, so the P&L shows the interest and never the principal, and the
  statements (`apps.finance.statements`) read it as the loan's interest.
Both carry the source `finance.loan` (id: the loan, key "<instalment id>:p<n>" and
"<instalment id>:i<n>", n counting the payments of that instalment). Payments cover the principal
in order, the way every instalment plan works (`queries.installment_schedule`).

An early repayment pays extra principal on a day: it becomes an instalment of its own (marked
`early`), and the payments not yet made are planned again from what is left
(`loan_math.recalculate`): the same number of smaller payments, or the same payment for fewer
months. So the instalments always add up to the loan.

A loan from before the books (no account: the money arrived before Daybook kept them) is an
opening debt of what is still owed, with the payments still to come.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.exceptions import DomainError
from apps.core.money import format_money, quantize
from apps.finance import access, loan_math, queries, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    LIVE_STATUSES,
    Category,
    Counterparty,
    Debt,
    DebtInstallment,
    Loan,
    MoneyAccount,
    Transaction,
)
from apps.finance.sources import Source
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

SOURCE = queries.LOAN_SOURCE  # "finance.loan"
ZERO = Decimal(0)
INTEREST_CODE = {
    Debt.Direction.PAYABLE: "loan_interest",
    Debt.Direction.RECEIVABLE: "interest_income",
}
OVERDUE_EVERY = 7  # days between reminders of the same overdue payment
LINE_STATUSES = ("paid", "partial", "due", "overdue")  # of a payment in the schedule
PAID = "paid"
NOTIFICATION = "finance.loan_due"


def _domain(error: loan_math.ScheduleError) -> DomainError:
    return DomainError(str(error))


# Schedules --------------------------------------------------------------------------------


def plan(
    *,
    amount,
    currency: str,
    annual_rate,
    method: str,
    term_months: int,
    first_due_on: date,
    issued_on: date,
    basis: str = Loan.Basis.MONTHLY,
    grace_months: int = 0,
    rows: list[loan_math.Row] | None = None,
) -> list[loan_math.Row]:
    """The schedule the terms make (or the typed rows, checked). Raises DomainError."""
    amount = Decimal(amount)
    try:
        if method == Loan.Method.CUSTOM:
            return loan_math.check_rows(rows or [], amount, currency)
        if first_due_on <= issued_on:
            raise loan_math.ScheduleError(_("The first payment comes after the loan starts."))
        made = loan_math.schedule(
            principal=amount,
            annual_rate=Decimal(annual_rate),
            months=int(term_months),
            first_due=first_due_on,
            method=method,
            basis=basis,
            grace=int(grace_months or 0),
            start=issued_on,
            currency=currency,
        )
    except loan_math.ScheduleError as error:
        raise _domain(error) from error
    return made


def preview(**terms) -> dict:
    """What a loan's schedule would be, without saving anything (the form's live preview)."""
    fee = Decimal(terms.pop("fee", 0) or 0)
    rows = plan(**terms)
    amount = Decimal(terms["amount"])
    left = loan_math.balances(rows, amount)
    sums = loan_math.totals(rows)
    return {
        "rows": [
            {
                "position": index + 1,
                "due_on": row.due_on,
                "principal": quantize(row.principal),
                "interest": quantize(row.interest),
                "payment": quantize(row.payment),
                "balance": quantize(balance),
            }
            for index, (row, balance) in enumerate(zip(rows, left, strict=True))
        ],
        "totals": {
            "principal": quantize(sums["principal"]),
            "interest": quantize(sums["interest"]),
            "payments": quantize(sums["payments"]),
            "fee": quantize(fee),
            "cost": quantize(sums["interest"] + fee),
        },
        "first_payment": quantize(rows[0].payment) if rows else ZERO,
        "effective_rate": loan_math.effective_rate(amount, rows, terms["issued_on"], fee),
    }


# Recording a loan -------------------------------------------------------------------------


@transaction.atomic
def create(
    company,
    *,
    by: Membership,
    direction: str,
    counterparty: Counterparty,
    amount,
    currency: str,
    issued_on: date,
    annual_rate,
    method: str,
    term_months: int,
    first_due_on: date,
    account: MoneyAccount | None = None,
    basis: str = Loan.Basis.MONTHLY,
    grace_months: int = 0,
    fee=0,
    rows: list[loan_math.Row] | None = None,
    branch=None,
    description: str = "",
    responsible: Membership | None = None,
) -> Loan:
    """Record a loan and its schedule. With `account` the money arrives on it (a loan taken) or
    leaves it (a loan given) today; without, it is a loan from before the books: `amount` is what
    is still owed and the schedule the payments still to come. A fee (loans taken only) is booked
    as a bank fee from the account the day the loan starts."""
    if direction not in Debt.Direction.values:
        raise DomainError(_("Pick whether the loan was taken or given."))
    if counterparty is None:
        raise DomainError(_("Pick the bank or the person of the loan."))
    if method not in Loan.Method.values:
        raise DomainError(_("Pick how the loan is repaid."))
    if basis not in Loan.Basis.values:
        raise DomainError(_("Pick how the interest is counted."))
    fee = services._money(fee, allow_zero=True)
    if fee and direction != Debt.Direction.PAYABLE:
        raise DomainError(_("Only a loan taken has a fee to pay."))
    if fee and account is None:
        raise DomainError(_("A fee is paid from an account: pick where the money arrived."))
    amount = services._money(amount)
    schedule = plan(
        amount=amount,
        currency=currency,
        annual_rate=annual_rate,
        method=method,
        term_months=term_months if method != Loan.Method.CUSTOM else max(len(rows or []), 1),
        first_due_on=first_due_on if method != Loan.Method.CUSTOM else issued_on,
        issued_on=issued_on,
        basis=basis,
        grace_months=grace_months,
        rows=rows,
    )
    if schedule[0].due_on < issued_on:
        raise DomainError(_("A payment can't be before the loan starts."))
    debt = services.open_debt(
        company,
        by=by,
        direction=direction,
        kind=Debt.Kind.LOAN,
        amount=amount,
        currency=currency,
        issued_on=issued_on,
        due_on=schedule[-1].due_on,
        counterparty=counterparty,
        account=account,
        is_opening=account is None,
        branch=branch,
        description=description,
        responsible=responsible,
    )
    loan = Loan.objects.create(
        company=company,
        debt=debt,
        annual_rate=Decimal(annual_rate or 0),
        method=method,
        basis=basis,
        term_months=len(schedule) if method == Loan.Method.CUSTOM else int(term_months),
        first_due_on=schedule[0].due_on,
        grace_months=int(grace_months or 0) if method != Loan.Method.CUSTOM else 0,
        fee=fee,
        account=account,
        created_by=by.user,
    )
    _write_rows(debt, schedule)
    if fee:
        services.record_transaction(
            company,
            by=by,
            kind=Transaction.Kind.EXPENSE,
            amount=fee,
            occurred_on=issued_on,
            account=account,
            category="bank_fees",
            counterparty=counterparty,
            branch=debt.branch,
            debt=debt,
            description=_("Loan fee"),
            source=Source(SOURCE, loan.pk, "fee"),
        )
    services._audit(
        FinanceAction.LOAN_CREATED,
        company,
        by.user,
        debt,
        loan=loan.pk,
        direction=direction,
        amount=str(amount),
        currency=currency,
        annual_rate=str(loan.annual_rate),
        method=method,
        payments=len(schedule),
    )
    return loan


def _write_rows(debt: Debt, rows: list[loan_math.Row], *, early: set[int] = frozenset()) -> None:
    DebtInstallment.objects.bulk_create(
        DebtInstallment(
            debt=debt,
            due_on=row.due_on,
            amount=quantize(row.principal),
            interest=quantize(row.interest),
            early=index in early,
            position=index,
        )
        for index, row in enumerate(rows)
    )


def started(loan: Loan) -> bool:
    """Whether anything was paid on the loan yet (its schedule is then fixed)."""
    debt = loan.debt
    return (
        debt.paid > 0
        or Transaction.objects.filter(debt=debt, status__in=LIVE_STATUSES)
        .filter(
            Q(kind=Transaction.Kind.DEBT_PAYMENT) | Q(source_type=SOURCE, source_key__contains=":")
        )
        .exists()
    )


@transaction.atomic
def replace_schedule(
    loan: Loan,
    *,
    by: Membership,
    annual_rate=None,
    method: str | None = None,
    term_months: int | None = None,
    first_due_on: date | None = None,
    basis: str | None = None,
    grace_months: int | None = None,
    rows: list[loan_math.Row] | None = None,
) -> Loan:
    """New terms or a typed schedule, before the first payment (afterwards the schedule changes
    only through an early repayment)."""
    loan = Loan.objects.select_for_update().select_related("debt", "company").get(pk=loan.pk)
    debt = services._lock_debt(loan.debt_id)
    if debt.status != Debt.Status.OPEN:
        raise DomainError(_("This loan is settled or cancelled."))
    if started(loan):
        raise DomainError(
            _("Payments were made on this loan: its schedule changes only by an early repayment.")
        )
    method = method or loan.method
    terms = {
        "annual_rate": loan.annual_rate if annual_rate is None else Decimal(annual_rate),
        "method": method,
        "term_months": term_months or loan.term_months,
        "first_due_on": first_due_on or loan.first_due_on,
        "basis": basis or loan.basis,
        "grace_months": loan.grace_months if grace_months is None else grace_months,
    }
    if method == Loan.Method.CUSTOM:
        terms["term_months"] = max(len(rows or []), 1)
        terms["first_due_on"] = debt.issued_on
    schedule = plan(
        amount=debt.amount,
        currency=debt.currency,
        issued_on=debt.issued_on,
        rows=rows,
        **terms,
    )
    if schedule[0].due_on < debt.issued_on:
        raise DomainError(_("A payment can't be before the loan starts."))
    debt.installments.all().delete()
    _write_rows(debt, schedule)
    loan.annual_rate = terms["annual_rate"]
    loan.method = method
    loan.basis = terms["basis"]
    loan.term_months = len(schedule) if method == Loan.Method.CUSTOM else terms["term_months"]
    loan.first_due_on = schedule[0].due_on
    loan.grace_months = 0 if method == Loan.Method.CUSTOM else int(terms["grace_months"] or 0)
    loan.save()
    Debt.objects.filter(pk=debt.pk).update(due_on=schedule[-1].due_on)
    services._audit(
        FinanceAction.LOAN_SCHEDULE_SET,
        loan.company,
        by.user,
        debt,
        loan=loan.pk,
        method=method,
        annual_rate=str(loan.annual_rate),
        payments=len(schedule),
    )
    return loan


# Reading a loan ---------------------------------------------------------------------------


def lines(loan: Loan, today: date) -> list[dict]:
    """The schedule with what is paid of each payment and what is owed after it: `principal`,
    `interest`, `payment`, `principal_paid`, `interest_paid`, `rest` (still to pay of it),
    `balance` (principal owed after it), `status` (paid, partial, due, overdue), `early`."""
    debt = loan.debt
    left = debt.amount
    found = []
    for index, row in enumerate(queries.installment_schedule(debt, today)):
        left -= row["amount"]
        rest = (row["amount"] - row["paid"]) + (row["interest"] - row["interest_paid"])
        found.append(
            {
                "id": row["id"],
                "position": index + 1,
                "due_on": row["due_on"],
                "principal": row["amount"],
                "interest": row["interest"],
                "payment": row["amount"] + row["interest"],
                "principal_paid": row["paid"],
                "interest_paid": row["interest_paid"],
                "rest": quantize(rest),
                "balance": quantize(left),
                "status": row["status"],
                "early": row["early"],
            }
        )
    return found


def next_line(rows: list[dict]) -> dict | None:
    return next((row for row in rows if row["status"] != "paid"), None)


def summary(loan: Loan, today: date, rows: list[dict] | None = None) -> dict:
    """The figures a loan's card shows: what is owed, the next payment, what is overdue, the
    interest paid so far and still to pay."""
    rows = rows if rows is not None else lines(loan, today)
    debt = loan.debt
    upcoming = next_line(rows)
    overdue = [row for row in rows if row["status"] == "overdue"]
    interest_paid = paid_interest(debt)
    interest_left = sum((row["interest"] - row["interest_paid"] for row in rows), ZERO)
    return {
        "owed": quantize(debt.amount - debt.paid),
        "principal": debt.amount,
        "paid_principal": debt.paid,
        "interest_paid": quantize(interest_paid),
        "interest_left": quantize(interest_left),
        "next": upcoming,
        "overdue_count": len(overdue),
        "overdue_amount": quantize(sum((row["rest"] for row in overdue), ZERO)),
        "payments_left": sum(1 for row in rows if row["status"] != "paid"),
        "payments": len(rows),
        "ends_on": rows[-1]["due_on"] if rows else debt.due_on,
    }


def paid_interest(debt: Debt) -> Decimal:
    """Every live interest row of the loan (including interest paid above the schedule)."""
    rows = Transaction.objects.filter(
        debt=debt, source_type=SOURCE, source_key__contains=":i", status__in=LIVE_STATUSES
    ).values_list("amount", flat=True)
    return sum((abs(amount) for amount in rows), ZERO)


def payments(loan: Loan) -> list[Transaction]:
    """The ledger rows of the loan: its opening, payments, interest and fee, oldest first."""
    return list(
        Transaction.objects.filter(
            Q(debt=loan.debt) | Q(source_type=SOURCE, source_id=loan.pk),
            company=loan.company,
        )
        .select_related("account", "category", "counterparty", "debt")
        .order_by("occurred_on", "pk")
    )


def visible_loans(member: Membership):
    """The loans whose debt the member may see (finance.view and branch scope)."""
    return (
        Loan.objects.filter(debt__in=access.visible_debts(member))
        .select_related("debt__counterparty", "debt__branch", "debt__company", "account", "company")
        .order_by("debt__due_on", "-pk")
    )


# Paying -------------------------------------------------------------------------------------


def _check_account(debt: Debt, account: MoneyAccount) -> None:
    services._same_company(debt.company, account)
    if account.currency != debt.currency:
        raise DomainError(
            _("The loan is in %(currency)s: pay it from an account in %(currency)s.")
            % {"currency": debt.currency}
        )


def _next_number(loan: Loan, installment_id: int) -> int:
    """The number of this instalment's next payment: one past every row ever booked for it
    (voided ones too: their keys stay used)."""
    keys = Transaction.objects.filter(
        source_type=SOURCE, source_id=loan.pk, source_key__startswith=f"{installment_id}:"
    ).values_list("source_key", flat=True)
    numbers = [
        int(key.rsplit(":", 1)[1][1:]) for key in keys if key.rsplit(":", 1)[1][1:].isdigit()
    ]
    return max(numbers, default=0) + 1


def _book(
    loan: Loan,
    debt: Debt,
    *,
    by: Membership,
    installment_id: int,
    account: MoneyAccount,
    paid_on: date,
    principal: Decimal,
    interest: Decimal,
    description: str,
) -> list[Transaction]:
    number = _next_number(loan, installment_id)
    rows = []
    if principal > 0:
        rows.append(
            services.pay_debt(
                debt,
                by=by,
                amount=principal,
                paid_on=paid_on,
                account=account,
                source=Source(SOURCE, loan.pk, f"{installment_id}:p{number}"),
            )
        )
    if interest > 0:
        receivable = debt.direction == Debt.Direction.RECEIVABLE
        rows.append(
            services.record_transaction(
                loan.company,
                by=by,
                kind=Transaction.Kind.INCOME if receivable else Transaction.Kind.EXPENSE,
                amount=interest,
                occurred_on=paid_on,
                account=account,
                category=INTEREST_CODE[debt.direction],
                counterparty=debt.counterparty,
                branch=debt.branch,
                debt=debt,
                description=description,
                source=Source(SOURCE, loan.pk, f"{installment_id}:i{number}"),
            )
        )
    return rows


@transaction.atomic
def pay(
    installment: DebtInstallment,
    *,
    by: Membership,
    account: MoneyAccount,
    paid_on: date,
    principal=None,
    interest=None,
) -> list[Transaction]:
    """Pay one instalment from `account` (in the loan's currency): by default what is left of its
    principal and interest. The principal can't go past the instalment (use an early repayment
    for more); the interest may (a late fee the bank charged)."""
    debt = services._lock_debt(installment.debt_id)
    loan = Loan.objects.filter(debt=debt).first()
    if loan is None:
        raise DomainError(_("This debt has no loan terms."))
    if debt.status != Debt.Status.OPEN:
        raise DomainError(_("This loan is settled or cancelled."))
    _check_account(debt, account)
    today = queries.local_today(debt.company)
    line = next((row for row in lines(loan, today) if row["id"] == installment.pk), None)
    if line is None:
        raise DomainError(_("This payment isn't in the loan's schedule any more."))
    principal_left = line["principal"] - line["principal_paid"]
    interest_left = line["interest"] - line["interest_paid"]
    principal = principal_left if principal is None else services._money(principal, allow_zero=True)
    interest = (
        max(interest_left, ZERO) if interest is None else services._money(interest, allow_zero=True)
    )
    if principal + interest <= 0:
        raise DomainError(_("Nothing is left to pay on this payment."))
    if principal > principal_left:
        raise DomainError(
            _(
                "That's more than the %(left)s of principal left on this payment: repay the rest "
                "early instead."
            )
            % {"left": format_money(principal_left, debt.currency, translation.get_language())}
        )
    rows = _book(
        loan,
        debt,
        by=by,
        installment_id=installment.pk,
        account=account,
        paid_on=paid_on,
        principal=principal,
        interest=interest,
        description=_("Loan payment %(n)s") % {"n": line["position"]},
    )
    services._audit(
        FinanceAction.LOAN_PAID,
        debt.company,
        by.user,
        debt,
        loan=loan.pk,
        installment=installment.pk,
        principal=str(principal),
        interest=str(interest),
        account=account.pk,
        transactions=[row.pk for row in rows],
    )
    return rows


@transaction.atomic
def repay_early(
    loan: Loan,
    *,
    by: Membership,
    account: MoneyAccount,
    paid_on: date,
    amount,
    interest=0,
    mode: str = loan_math.REDUCE_PAYMENT,
) -> list[Transaction]:
    """Repay `amount` of principal early (with the `interest` the bank charged up to today), and
    plan the payments not yet made again: `mode` "payment" keeps their number and lowers each,
    "term" keeps the payment and ends sooner. Repaying everything left settles the loan."""
    loan = Loan.objects.select_for_update().select_related("company").get(pk=loan.pk)
    debt = services._lock_debt(loan.debt_id)
    if debt.status != Debt.Status.OPEN:
        raise DomainError(_("This loan is settled or cancelled."))
    if mode not in (loan_math.REDUCE_PAYMENT, loan_math.REDUCE_TERM):
        raise DomainError(_("Pick smaller payments or a shorter term."))
    _check_account(debt, account)
    amount = services._money(amount)
    interest = services._money(interest, allow_zero=True)
    left = debt.amount - debt.paid
    if amount > left:
        raise DomainError(
            _("That's more than the %(left)s still owed.")
            % {"left": format_money(left, debt.currency, translation.get_language())}
        )
    today = queries.local_today(loan.company)
    rows = lines(loan, today)
    if any(row["due_on"] <= paid_on and row["status"] != "paid" for row in rows):
        raise DomainError(_("Pay the payments that are already due first."))
    touched = [
        row
        for row in rows
        if row["due_on"] <= paid_on or row["principal_paid"] > 0 or row["interest_paid"] > 0
    ]
    future = [row for row in rows if row not in touched]
    if touched and future and future[0]["position"] < touched[-1]["position"]:
        raise DomainError(_("Pay the payments in their order first."))
    kept = sum((row["principal"] for row in touched), ZERO)
    early = debt.paid + amount - kept
    if early <= 0:
        raise DomainError(_("That only pays a payment ahead: use Pay on that payment."))
    balance = debt.amount - debt.paid - amount
    new_rows: list[loan_math.Row] = []
    if balance > 0:
        if not future:
            raise DomainError(_("No payments are left to plan: pay the last one instead."))
        first = DebtInstallment.objects.get(pk=future[0]["id"])
        # Fewer months keep the whole payment of an annuity, the principal part otherwise.
        annuity = loan.method == Loan.Method.ANNUITY
        keep = first.amount + first.interest if annuity else first.amount
        try:
            new_rows = loan_math.recalculate(
                balance=balance,
                annual_rate=loan.annual_rate,
                method=loan.method,
                basis=loan.basis,
                next_due=first.due_on,
                remaining=len(future),
                since=paid_on,
                mode=mode,
                payment=keep,
                currency=debt.currency,
            )
        except loan_math.ScheduleError as error:
            raise _domain(error) from error
    DebtInstallment.objects.filter(pk__in=[row["id"] for row in future]).delete()
    marker = DebtInstallment.objects.create(
        debt=debt, due_on=paid_on, amount=quantize(early), interest=interest, early=True
    )
    DebtInstallment.objects.bulk_create(
        DebtInstallment(
            debt=debt,
            due_on=row.due_on,
            amount=quantize(row.principal),
            interest=quantize(row.interest),
        )
        for row in new_rows
    )
    _renumber(debt)
    booked = _book(
        loan,
        debt,
        by=by,
        installment_id=marker.pk,
        account=account,
        paid_on=paid_on,
        principal=amount,
        interest=interest,
        description=_("Early repayment of a loan"),
    )
    last = debt.installments.order_by("-due_on", "-position").values_list("due_on", flat=True)
    if new_rows and last:
        Debt.objects.filter(pk=debt.pk).update(due_on=max(last[0], debt.issued_on))
    services._audit(
        FinanceAction.LOAN_REPAID_EARLY,
        loan.company,
        by.user,
        debt,
        loan=loan.pk,
        amount=str(amount),
        interest=str(interest),
        mode=mode,
        payments_left=len(new_rows),
        transactions=[row.pk for row in booked],
    )
    return booked


def _renumber(debt: Debt) -> None:
    ordered = list(debt.installments.order_by("due_on", "-early", "position", "pk"))
    for index, row in enumerate(ordered):
        if row.position != index:
            row.position = index
            row.save(update_fields=["position"])


@transaction.atomic
def undo_payment(loan: Loan, row: Transaction, *, by: Membership, reason: str) -> list[Transaction]:
    """Take back one payment of an instalment (its principal and interest rows together). An
    early repayment is not undone here: its new schedule would no longer match."""
    if row.source_type != SOURCE or row.source_id != loan.pk or ":" not in row.source_key:
        raise DomainError(_("This entry isn't a payment of this loan."))
    installment_id, number = row.source_key.split(":", 1)
    if DebtInstallment.objects.filter(pk=installment_id, early=True).exists():
        raise DomainError(_("An early repayment can't be taken back here."))
    pair = list(
        Transaction.objects.filter(
            source_type=SOURCE,
            source_id=loan.pk,
            source_key__in=[f"{installment_id}:p{number[1:]}", f"{installment_id}:i{number[1:]}"],
            status__in=LIVE_STATUSES,
        ).order_by("pk")
    )
    if not pair:
        raise DomainError(_("This payment was already taken back."))
    for found in pair:
        services.void_transaction(found, by=by, reason=reason)
    services._audit(
        FinanceAction.LOAN_PAYMENT_UNDONE,
        loan.company,
        by.user,
        loan.debt,
        loan=loan.pk,
        transactions=[found.pk for found in pair],
        reason=reason,
    )
    return pair


# What is due ------------------------------------------------------------------------------


def open_loans(company, *, branch_ids=None):
    debts = queries.scoped_debts(company, branch_ids=branch_ids).filter(
        status=Debt.Status.OPEN, kind=Debt.Kind.LOAN
    )
    return (
        Loan.objects.filter(debt__in=debts)
        .select_related("debt__counterparty", "debt__company", "debt__branch", "account", "company")
        .order_by("pk")
    )


def overdue(company, today: date, *, branch_ids=None, direction: str | None = None) -> list[dict]:
    """Each loan payment past its day and not fully paid: {loan, line, days}."""
    found = []
    for loan in open_loans(company, branch_ids=branch_ids):
        if direction and loan.debt.direction != direction:
            continue
        for line in lines(loan, today):
            if line["status"] == "overdue":
                found.append({"loan": loan, "line": line, "days": (today - line["due_on"]).days})
    return found


# Reminders (at the company's morning hour, `deadline_reminders`) --------------------------


def recipients(company, branch_id: int | None) -> list[Membership]:
    """The people who manage the company's money and see the loan's branch."""
    from apps.members.queries import members_with_perm

    people = members_with_perm(company, Perm.FINANCE_MANAGE).select_related("user", "role")
    return [
        person
        for person in people
        if (branches := scope.branch_ids(person)) is None
        or (branch_id is not None and branch_id in branches)
    ]


def due_to_remind(line: dict, today: date, days_before: int) -> bool:
    """On `days_before` days before the payment, on its day, and weekly once it is late."""
    if line["status"] == "paid":
        return False
    late = (today - line["due_on"]).days
    if late > 0:
        return late % OVERDUE_EVERY == 1 or late == 1
    return late == 0 or -late == days_before


def remind(company, today: date) -> int:
    """Owners hear about each loan payment coming (`loan_remind_days` before and on the day) and
    one that is late (the day after, then weekly). Returns how many notifications."""
    from apps.finance import conf
    from apps.inbox.services import NotificationAction, notify

    days_before = conf.get_settings(company).loan_remind_days
    sent = 0
    for loan in open_loans(company):
        debt = loan.debt
        people = None
        for line in lines(loan, today):
            if not due_to_remind(line, today, days_before):
                continue
            people = people if people is not None else recipients(company, debt.branch_id)
            if not people:
                break
            actions = []
            can_pay = (
                loan.account_id is not None
                and loan.account.is_active
                and debt.direction == Debt.Direction.PAYABLE
            )
            if can_pay:
                actions.append(
                    NotificationAction(
                        PAID,
                        lambda person, loan=loan: (
                            _("Paid from %(account)s") % {"account": loan.account.name}
                        ),
                        "primary",
                    )
                )
            made = notify(
                people,
                NOTIFICATION,
                title=lambda person, loan=loan, line=line: reminder_title(
                    loan, line, today, person
                ),
                body=lambda person, loan=loan, line=line: reminder_body(loan, line, person),
                url=f"/c/{company.pk}/finance/loans/{loan.pk}",
                target=debt,
                actions=actions,
                data={"installment": line["id"], "loan": loan.pk},
                dedupe_key=f"finance:loan:{line['id']}:{today.isoformat()}",
                severity="warning" if line["status"] == "overdue" else None,
            )
            sent += len(made)
    return sent


def _money(amount, currency, person: Membership) -> str:
    return format_money(amount, currency, (person.user.language or "uz")[:2])


def reminder_title(loan: Loan, line: dict, today: date, person: Membership) -> str:
    from apps.finance.reminders import due_text

    debt = loan.debt
    with translation.override(person.user.language):
        who = (
            _("Loan payment: %(party)s")
            if debt.direction == Debt.Direction.PAYABLE
            else _("Loan repayment to us: %(party)s")
        ) % {"party": debt.counterparty.name}
        return " · ".join(
            [who, _money(line["rest"], debt.currency, person), due_text(line["due_on"], today)]
        )


def reminder_body(loan: Loan, line: dict, person: Membership) -> str:
    debt = loan.debt
    with translation.override(person.user.language):
        parts = _("Principal %(principal)s, interest %(interest)s.") % {
            "principal": _money(line["principal"] - line["principal_paid"], debt.currency, person),
            "interest": _money(line["interest"] - line["interest_paid"], debt.currency, person),
        }
        owed = _("Still owed after it: %(balance)s.") % {
            "balance": _money(line["balance"], debt.currency, person)
        }
        return f"{parts}\n{owed}"


def paid_action(notification, by: Membership, reason: str) -> str:
    """[Paid from <account>]: pay the reminded payment from the loan's account, today."""
    data = notification.data or {}
    installment = (
        DebtInstallment.objects.filter(
            pk=data.get("installment"), debt__company_id=notification.company_id
        )
        .select_related("debt__company")
        .first()
    )
    loan = Loan.objects.filter(pk=data.get("loan"), company_id=notification.company_id).first()
    if installment is None or loan is None or loan.debt_id != installment.debt_id:
        raise DomainError(_("This isn't available any more."))
    if loan.account_id is None:
        raise DomainError(_("Open the dashboard to pick the account."))
    if not access.recordable_accounts(by).filter(pk=loan.account_id).exists():
        raise DomainError(
            _("You can't record payments on %(account)s.") % {"account": loan.account}
        )
    today = queries.local_today(loan.company)
    line = next((row for row in lines(loan, today) if row["id"] == installment.pk), None)
    if line is None or line["status"] == "paid":
        return str(_("Already paid."))
    pay(installment, by=by, account=loan.account, paid_on=today)
    return str(_("Paid from %(account)s.") % {"account": loan.account.name})


# Labels -----------------------------------------------------------------------------------

DIRECTION_LABELS = {
    Debt.Direction.PAYABLE: gettext_lazy("Loan taken"),
    Debt.Direction.RECEIVABLE: gettext_lazy("Loan given"),
}


def interest_category(company, direction: str) -> Category:
    return services._category(company, INTEREST_CODE[direction])
