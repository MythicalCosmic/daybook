"""Loan schedules (v12): the repayment plan of a loan, principal, interest and balance per payment.
Pure arithmetic on `Decimal`, no database (its errors are translated texts); `apps.finance.loans`
stores what it returns as the debt's instalments.

Methods
    annuity          equal payments: A = P · i / (1 - (1 + i)^-n), i the monthly rate (the annual
                     rate / 12), n the payments after the grace months. Each payment's interest is
                     the rate on what is still owed; the rest of A is principal.
    equal_principal  the same principal each time (P / n), interest on what is still owed, so the
                     payments fall ("kamayib boruvchi" / дифференцированный платёж).
    custom           the bank's own rows, typed by hand (`check_rows`).
A rate of 0 makes both methods equal parts with no interest.

Interest of a period
    monthly   balance x annual rate / 12 (every month the same twelfth);
    actual    balance x annual rate x days since the previous payment / 365 (the first period
              runs from the day the loan started). Many banks in Uzbekistan accrue this way;
              their printed schedule always wins: type it as a custom schedule when it differs.

Grace months: the first `grace` payments pay interest only; the principal is spread over the rest.

Rounding: every principal and interest part is rounded to the currency's unit (whole so‘m for
UZS, cents otherwise), half up. The last payment takes exactly what is left of the principal, so
the principal parts always add up to the loan: nothing is lost or made up by rounding.

Early repayment (`recalculate`): what is left after an extra payment is planned again from the
next payment day, either with the same number of payments (smaller payments) or with the same
payment (fewer payments).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.utils.translation import gettext as _

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
YEAR_DAYS = Decimal(365)
MAX_MONTHS = 600

ANNUITY = "annuity"
EQUAL_PRINCIPAL = "equal_principal"
CUSTOM = "custom"
METHODS = (ANNUITY, EQUAL_PRINCIPAL, CUSTOM)
MONTHLY = "monthly"
ACTUAL = "actual"
REDUCE_PAYMENT = "payment"
REDUCE_TERM = "term"


class ScheduleError(ValueError):
    """Terms that make no schedule (the service turns it into a DomainError)."""


@dataclass(frozen=True)
class Row:
    due_on: date
    principal: Decimal
    interest: Decimal

    @property
    def payment(self) -> Decimal:
        return self.principal + self.interest


def unit(currency: str) -> Decimal:
    """The smallest amount a payment is rounded to: a whole so‘m, or a cent."""
    return ONE if currency == "UZS" else Decimal("0.01")


def money(amount: Decimal, currency: str, rounding=ROUND_HALF_UP) -> Decimal:
    return Decimal(amount).quantize(unit(currency), rounding=rounding).quantize(Decimal("0.01"))


def add_months(day: date, months: int, anchor: int | None = None) -> date:
    """`day` moved by `months` months on day `anchor` (default its own day), the month's last day
    when the month is shorter (31 January + 1 month = 28 or 29 February)."""
    anchor = anchor or day.day
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


def due_days(first: date, count: int) -> list[date]:
    """`count` monthly payment days from `first`, on its day of the month."""
    return [add_months(first, step, first.day) for step in range(count)]


def monthly_rate(annual_rate: Decimal) -> Decimal:
    return Decimal(annual_rate) / HUNDRED / 12


def period_interest(
    balance: Decimal, annual_rate: Decimal, basis: str, start: date, end: date
) -> Decimal:
    """The interest of one period, unrounded."""
    if basis == ACTUAL:
        days = max((end - start).days, 0)
        return balance * Decimal(annual_rate) / HUNDRED * days / YEAR_DAYS
    return balance * monthly_rate(annual_rate)


def annuity_payment(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """A = P · i / (1 - (1 + i)^-n); P / n without interest. Unrounded."""
    if months <= 0:
        raise ScheduleError(_("No payments to spread the loan over."))
    rate = monthly_rate(annual_rate)
    if rate == 0:
        return Decimal(principal) / months
    return Decimal(principal) * rate / (ONE - (ONE + rate) ** -months)


def schedule(
    *,
    principal: Decimal,
    annual_rate: Decimal,
    months: int,
    first_due: date,
    method: str = ANNUITY,
    basis: str = MONTHLY,
    grace: int = 0,
    start: date | None = None,
    currency: str = "UZS",
) -> list[Row]:
    """The payments of a loan of `principal` over `months` monthly payments from `first_due`.

    `start` is the day the money was taken (for interest by actual days; default a month before
    the first payment). Raises ScheduleError on terms that make no schedule."""
    principal = Decimal(principal)
    annual_rate = Decimal(annual_rate)
    if principal <= 0:
        raise ScheduleError(_("The amount must be more than zero."))
    if not 1 <= months <= MAX_MONTHS:
        raise ScheduleError(_("The term is 1 to 600 months."))
    if not 0 <= grace < months:
        raise ScheduleError(_("The grace months must be fewer than the payments."))
    if annual_rate < 0 or annual_rate > HUNDRED:
        raise ScheduleError(_("The annual rate is 0 to 100 per cent."))
    if method not in (ANNUITY, EQUAL_PRINCIPAL):
        raise ScheduleError(_("Pick how the loan is repaid."))
    days = due_days(first_due, months)
    previous = start or add_months(first_due, -1)
    if previous > first_due:
        raise ScheduleError(_("The first payment comes after the loan starts."))
    paying = months - grace
    payment = money(annuity_payment(principal, annual_rate, paying), currency)
    share = money(principal / paying, currency)
    rows: list[Row] = []
    left = principal
    for index, due in enumerate(days):
        interest = money(period_interest(left, annual_rate, basis, previous, due), currency)
        last = index == months - 1
        if index < grace:
            part = ZERO
        elif last:
            part = left
        elif method == ANNUITY:
            part = min(max(payment - interest, ZERO), left)
        else:
            part = min(share, left)
        rows.append(Row(due, part, interest))
        left -= part
        previous = due
    # An interest-free grace month pays nothing: it is no payment at all.
    return [row for row in rows if row.payment > 0]


def recalculate(
    *,
    balance: Decimal,
    annual_rate: Decimal,
    method: str,
    basis: str,
    next_due: date,
    remaining: int,
    since: date,
    mode: str = REDUCE_PAYMENT,
    payment: Decimal | None = None,
    currency: str = "UZS",
) -> list[Row]:
    """What is left after an early repayment, planned again from `next_due`.

    `remaining` is how many payments the old plan still had; `since` the day of the early
    repayment (interest by actual days runs from it). `mode` "payment" keeps the number of
    payments and lowers each; "term" keeps the payment (`payment`, the old plan's next one: the
    whole payment for an annuity, the principal part for equal principal) and ends sooner."""
    balance = Decimal(balance)
    if balance <= 0:
        return []
    if remaining <= 0:
        raise ScheduleError(_("No payments are left to plan: pay the last one instead."))
    if method == CUSTOM:
        method = EQUAL_PRINCIPAL  # a typed schedule is spread evenly after an early repayment
    if mode == REDUCE_PAYMENT or payment is None or payment <= 0:
        return schedule(
            principal=balance,
            annual_rate=annual_rate,
            months=remaining,
            first_due=next_due,
            method=method,
            basis=basis,
            start=since,
            currency=currency,
        )
    rows: list[Row] = []
    left = balance
    previous = since
    for due in due_days(next_due, remaining):
        interest = money(period_interest(left, annual_rate, basis, previous, due), currency)
        if method == ANNUITY:
            part = payment - interest
            if part <= 0:  # the old payment no longer covers the interest: keep the term instead
                return recalculate(
                    balance=balance,
                    annual_rate=annual_rate,
                    method=method,
                    basis=basis,
                    next_due=next_due,
                    remaining=remaining,
                    since=since,
                    currency=currency,
                )
        else:
            part = payment
        part = min(part, left)
        rows.append(Row(due, part, interest))
        left -= part
        previous = due
        if left <= 0:
            break
    if left > 0:  # rounding left a tail: the last payment takes it
        last = rows[-1]
        rows[-1] = Row(last.due_on, last.principal + left, last.interest)
    return rows


def balances(rows: list[Row], principal: Decimal) -> list[Decimal]:
    """What is still owed after each row."""
    left = Decimal(principal)
    found = []
    for row in rows:
        left -= row.principal
        found.append(left)
    return found


def totals(rows: list[Row]) -> dict:
    return {
        "principal": sum((row.principal for row in rows), ZERO),
        "interest": sum((row.interest for row in rows), ZERO),
        "payments": sum((row.payment for row in rows), ZERO),
    }


def check_rows(rows: list[Row], principal: Decimal, currency: str = "UZS") -> list[Row]:
    """A typed schedule: days in order, no negative parts, each payment more than zero, and the
    principal parts adding up to the loan exactly. Returns the rows rounded to the currency."""
    if not rows:
        raise ScheduleError(_("Add at least one payment."))
    clean = []
    for row in rows:
        part = Decimal(row.principal).quantize(Decimal("0.01"))
        interest = Decimal(row.interest).quantize(Decimal("0.01"))
        if part < 0 or interest < 0:
            raise ScheduleError(_("A payment's parts can't be negative."))
        if part == 0 and interest == 0:
            raise ScheduleError(_("Every payment must be more than zero."))
        clean.append(Row(row.due_on, part, interest))
    days = [row.due_on for row in clean]
    if days != sorted(days):
        raise ScheduleError(_("The payments must be in date order."))
    total = sum((row.principal for row in clean), ZERO)
    if total != Decimal(principal).quantize(Decimal("0.01")):
        raise ScheduleError(_("The principal parts must add up to the loan."))
    return clean


def effective_rate(
    principal: Decimal, rows: list[Row], start: date, fee: Decimal = ZERO
) -> Decimal:
    """The interest and fee as a share of the principal per year of the loan's average life
    (a simple, honest "what it really costs" figure; not the bank's APR). In per cent."""
    principal = Decimal(principal)
    if principal <= 0 or not rows:
        return ZERO
    cost = totals(rows)["interest"] + Decimal(fee)
    weighted = sum((row.principal * Decimal((row.due_on - start).days) for row in rows), ZERO)
    years = weighted / principal / YEAR_DAYS
    if years <= 0:
        return ZERO
    return (cost / principal / years * HUNDRED).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
