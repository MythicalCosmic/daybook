"""The depreciation schedule of one asset: arithmetic over its facts, no database.

    rows = schedule(Facts(cost=…, salvage=…, life_months=60, method="straight_line",
                          start=date(2026, 3, 15), rule="next_month"))

Every month is computed **forward from the net book value it opens with**, over the life that
is left: a month already posted keeps its amount, and anything that changes later months (an
improvement added to the cost, a write-down, a new useful life or residual value, mothballing)
starts a new *basis* from the next month not yet posted. So a change of estimate is always
prospective (NSBU No. 5 and IAS 8), history is never rewritten, and the last month takes
whatever rounding left so the asset ends exactly at its residual value.

Methods (NSBU No. 5): straight line; declining balance at `factor` times the straight-line rate
(double by default), switching to straight line once that is larger, never below the residual
value; sum of the years' digits (a partial last year weighs by its months); units of output.

Rules (the company's accounting policy): `next_month` starts on the 1st of the month after the
asset is put into service and stops after the month it is disposed of; `daily` starts on the
day it is put into service and stops on the day it is disposed of, with the first and last
months prorated by days, so the life is used up exactly.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")

STRAIGHT_LINE, DECLINING, SUM_OF_YEARS, UNITS, NONE = (
    "straight_line",
    "declining",
    "sum_of_years",
    "units",
    "none",
)
NEXT_MONTH, DAILY = "next_month", "daily"


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def first_of(day: date) -> date:
    return day.replace(day=1)


def add_months(month: date, count: int) -> date:
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def months_between(start: date, end: date) -> int:
    """Whole months from `start`'s month to `end`'s month (end not included)."""
    return (end.year - start.year) * 12 + end.month - start.month


def days_in(month: date) -> int:
    return calendar.monthrange(month.year, month.month)[1]


@dataclass(frozen=True)
class Change:
    """Something that changes the months after it.

    - `addition` / `impairment`: `amount` added to / taken off the book value at the end of
      `on`'s month (its depreciation starts the month after);
    - `estimate`: a new total useful life (`life_months`), residual value (`salvage`) and/or
      method, from `on`'s month (or the first month not yet posted, if that is later);
    - `suspend` / `resume`: no depreciation from the month after `on` (mothballed) until the
      month after the resume; the life left waits too;
    - `usage`: units of output in `on`'s month (units method).
    """

    kind: str
    on: date
    amount: Decimal = ZERO
    life_months: int | None = None
    salvage: Decimal | None = None
    method: str | None = None
    units: Decimal | None = None


@dataclass(frozen=True)
class Facts:
    cost: Decimal
    life_months: int | None
    method: str
    start: date | None  # put into service
    rule: str = NEXT_MONTH
    salvage: Decimal = ZERO
    factor: Decimal = Decimal("2")
    total_units: Decimal | None = None
    disposed_on: date | None = None
    changes: tuple[Change, ...] = ()
    # Months already posted: their amounts are history.
    posted: dict[date, Decimal] = field(default_factory=dict)
    # Depreciation before the asset was entered here, up to the end of the month before
    # `opening_month`: one sum instead of those months.
    opening_accumulated: Decimal | None = None
    opening_month: date | None = None


@dataclass
class Month:
    month: date
    opening: Decimal  # book value the month opens with
    amount: Decimal
    closing: Decimal  # book value after the month (and its additions or write-downs)
    accumulated: Decimal
    posted: bool
    fraction: Decimal  # how much of the month it was in service and depreciating
    notes: list[str] = field(default_factory=list)


@dataclass
class _Basis:
    """What the months from `start` on depreciate: `amount` over `life` (month units)."""

    start: date
    amount: Decimal  # book value minus residual value when the basis began
    life: Decimal  # months of life left when it began
    units: Decimal | None  # units left (units method)


def first_month(facts: Facts) -> date | None:
    """The first month that depreciates, or None when it never will."""
    if facts.start is None:
        return None
    month = first_of(facts.start)
    return month if facts.rule == DAILY else add_months(month, 1)


def last_month(facts: Facts) -> date | None:
    """The last month that may depreciate (the disposal month), or None while it is kept."""
    if facts.disposed_on is None:
        return None
    return first_of(facts.disposed_on)


def _fraction(facts: Facts, month: date) -> Decimal:
    """How much of `month` the asset depreciates: 1, or by days under the daily rule."""
    if facts.rule != DAILY:
        return ONE
    days = Decimal(days_in(month))
    begin, end = 1, days_in(month)
    if facts.start and first_of(facts.start) == month:
        begin = facts.start.day
    if facts.disposed_on and first_of(facts.disposed_on) == month:
        end = facts.disposed_on.day
    if end < begin:
        return ZERO
    return Decimal(end - begin + 1) / days


def depreciates(facts: Facts) -> bool:
    return (
        facts.method != NONE
        and facts.start is not None
        and (facts.method == UNITS or bool(facts.life_months))
        and facts.cost > 0
    )


def schedule(
    facts: Facts, *, until: date | None = None, actual_until: date | None = None
) -> list[Month]:
    """Every depreciating month from the first to the last (the end of the life, the disposal,
    or `until`, whichever comes first), with the posted ones as they were posted.

    Units of output: months up to `actual_until` use the units recorded (none recorded = no
    depreciation); later months use the average of the last three recorded months. Without
    `until`, a kept asset runs to the end of its life (the units method to its last recorded
    month), and a mothballed one stops at its first mothballed month."""
    if not depreciates(facts):
        return []
    begin = first_month(facts)
    stop = last_month(facts)
    if stop is not None and stop < begin:
        return []
    changes = sorted(facts.changes, key=lambda change: (change.on, change.kind))
    usage: dict[date, Decimal] = {}
    for change in changes:
        if change.kind == "usage" and change.units is not None:
            key = first_of(change.on)
            usage[key] = usage.get(key, ZERO) + Decimal(change.units)
    last_posted = max(facts.posted) if facts.posted else None
    horizon = first_of(until) if until is not None else None
    if horizon is None and facts.method == UNITS:
        horizon = max(usage) if usage else begin

    state = _State(facts)
    month = begin
    if facts.opening_accumulated is not None and facts.opening_month is not None:
        month = max(first_of(facts.opening_month), begin)
        skipped = months_between(begin, month)
        if skipped > 0:
            state.used = Decimal(skipped) - ONE + _fraction(facts, begin)
        state.accumulated = money(facts.opening_accumulated)
        state.book = money(state.book - state.accumulated)
        state.units_used = sum((units for key, units in usage.items() if key < month), ZERO)
    applied: set[int] = set()

    def effective(change: Change) -> date:
        when = first_of(change.on)
        if change.kind == "estimate" and last_posted is not None and when <= last_posted:
            return add_months(last_posted, 1)
        return when

    # What happened before the first month counted (an improvement bought with it, a new
    # estimate, mothballing) applies from the start.
    for index, change in enumerate(changes):
        if change.kind in ("addition", "impairment") and first_of(change.on) < month:
            state.adjust(change)
            applied.add(index)
        elif change.kind == "estimate" and effective(change) < month:
            state.estimate(change)
            applied.add(index)
        elif change.kind in ("suspend", "resume") and add_months(first_of(change.on), 1) <= month:
            state.suspended = change.kind == "suspend"
            applied.add(index)
    state.rebase(month)

    rows: list[Month] = []
    for _guard in range(1200):  # a hundred years: anything longer means broken facts
        if (stop is not None and month > stop) or (horizon is not None and month > horizon):
            break
        notes: list[str] = []
        for index, change in enumerate(changes):
            if index in applied:
                continue
            if change.kind == "estimate" and effective(change) == month:
                state.estimate(change)
                state.rebase(month)
                applied.add(index)
                notes.append("estimate")
            elif change.kind in ("suspend", "resume") and (
                add_months(first_of(change.on), 1) == month
            ):
                state.suspended = change.kind == "suspend"
                if not state.suspended:
                    state.rebase(month)
                applied.add(index)
                notes.append(change.kind)

        opening = state.book
        is_posted = month in facts.posted
        fraction = ZERO if state.suspended else _fraction(facts, month)
        left = state.life - state.used
        if state.method != UNITS and fraction > max(left, ZERO):
            fraction = max(left, ZERO)
        if is_posted:
            amount = money(facts.posted[month])
        elif state.suspended:
            amount = ZERO
        elif state.method != UNITS and left <= 0:
            amount = max(state.book - state.salvage, ZERO)  # life used up: what is left
        else:
            future = actual_until is not None and month > first_of(actual_until)
            units = _projected(usage, month) if future else usage.get(month, ZERO)
            amount = _amount(
                state.method,
                basis=state.basis,
                book=state.book,
                salvage=state.salvage,
                left=left,
                used_since=state.used - state.basis_used,
                fraction=fraction,
                factor=Decimal(facts.factor),
                units=units,
            )
            amount = min(max(amount, ZERO), max(state.book - state.salvage, ZERO))
        state.book = money(state.book - amount)
        state.accumulated = money(state.accumulated + amount)
        state.used += fraction
        if state.method == UNITS and not state.suspended:
            state.units_used += usage.get(month, ZERO)
        if state.suspended:
            notes.append("suspended")

        rebase = False
        for index, change in enumerate(changes):
            if index in applied or change.kind not in ("addition", "impairment"):
                continue
            if first_of(change.on) == month:
                state.adjust(change)
                applied.add(index)
                rebase = True
                notes.append(change.kind)
        if stop is not None and month == stop:
            notes.append("disposed")
        row = Month(
            month, opening, amount, state.book, state.accumulated, is_posted, fraction, notes
        )
        rows.append(row)
        month = add_months(month, 1)
        if rebase:
            state.rebase(month)
            continue
        done = state.book <= state.salvage
        if state.method != UNITS:
            done = done or (state.used >= state.life and state.book <= state.salvage)
        if done:
            row.notes.append("final")
            break
        if state.suspended and until is None and stop is None:
            resumes = any(
                change.kind == "resume" and index not in applied
                for index, change in enumerate(changes)
            )
            if not resumes:
                break  # mothballed for good: its future is unknown
    return rows


class _State:
    """Where the schedule stands: book value, life used, the method and residual value in force,
    and the basis the coming months depreciate."""

    def __init__(self, facts: Facts):
        self.facts = facts
        self.method = facts.method
        self.salvage = money(facts.salvage)
        self.life = Decimal(facts.life_months or 0)
        self.book = money(facts.cost)
        self.accumulated = ZERO
        self.used = ZERO
        self.units_used = ZERO
        self.suspended = False
        self.basis = _Basis(date.min, ZERO, ZERO, None)
        self.basis_used = ZERO

    def rebase(self, month: date) -> None:
        units = None
        if self.facts.total_units is not None:
            units = max(Decimal(self.facts.total_units) - self.units_used, ZERO)
        depreciable = max(self.book - self.salvage, ZERO)
        self.basis = _Basis(month, depreciable, max(self.life - self.used, ZERO), units)
        self.basis_used = self.used

    def estimate(self, change: Change) -> None:
        if change.life_months is not None:
            self.life = Decimal(change.life_months)
        if change.salvage is not None:
            self.salvage = money(change.salvage)
        if change.method is not None:
            self.method = change.method

    def adjust(self, change: Change) -> None:
        if change.kind == "addition":
            self.book = money(self.book + Decimal(change.amount))
        elif change.kind == "impairment":
            self.book = money(max(self.book - Decimal(change.amount), ZERO))
            self.salvage = min(self.salvage, self.book)


def _suspended_before(changes, month: date) -> bool:
    """Mothballed before `month` (the opening of the schedule)?"""
    state = False
    for change in changes:
        if change.kind in ("suspend", "resume") and add_months(first_of(change.on), 1) < month:
            state = change.kind == "suspend"
    return state


def _projected(usage: dict[date, Decimal], month: date) -> Decimal:
    """A future month's units: the average of the last three months recorded before it."""
    known = [usage[key] for key in sorted(usage) if key < month][-3:]
    if not known:
        return ZERO
    return sum(known, ZERO) / len(known)


def _amount(
    method: str,
    *,
    basis: _Basis,
    book: Decimal,
    salvage: Decimal,
    left: Decimal,
    used_since: Decimal,
    fraction: Decimal,
    factor: Decimal,
    units: Decimal,
) -> Decimal:
    depreciable = max(book - salvage, ZERO)
    if depreciable == 0 or fraction == 0:
        return ZERO
    if method == UNITS:
        if not basis.units:
            return ZERO
        return money(min(basis.amount * units / basis.units, depreciable))
    if left <= fraction:
        return depreciable  # the last month takes what is left
    straight = depreciable * fraction / left
    if method == STRAIGHT_LINE:
        return money(straight)
    if method == DECLINING:
        life = basis.life if basis.life > 0 else left
        declining = book * factor / life * fraction
        return money(min(max(declining, straight), depreciable))
    if method == SUM_OF_YEARS:
        return money(min(_sum_of_years(basis, used_since, fraction), depreciable))
    return ZERO


def _sum_of_years(basis: _Basis, used_since: Decimal, fraction: Decimal) -> Decimal:
    """The month's share of the basis by the sum of the years' digits: year y of n weighs
    n - y + 1 (a partial last year by its months). Rounded on the running total, so every
    year's sum is exact."""
    return money(_years_share(basis, used_since + fraction)) - money(
        _years_share(basis, used_since)
    )


def _years_share(basis: _Basis, used: Decimal) -> Decimal:
    """How much of the basis is used up after `used` months of it."""
    months = basis.life
    if months <= 0:
        return ZERO
    years = int((months / 12).to_integral_value(rounding=ROUND_CEILING))
    last = months - 12 * (years - 1)
    sizes = [Decimal(12)] * (years - 1) + [last]
    weights = [Decimal(years - index) * sizes[index] / 12 for index in range(years)]
    total = sum(weights, ZERO)
    share = ZERO
    left = min(max(used, ZERO), months)
    for index in range(years):
        part = min(left, sizes[index])
        share += Decimal(years - index) * part / 12
        left -= part
        if left <= 0:
            break
    return basis.amount * share / total


def tax_schedule(
    cost: Decimal,
    annual_rate: Decimal | None,
    start: date | None,
    *,
    until: date,
    rule: str = NEXT_MONTH,
) -> list[tuple[date, Decimal]]:
    """The tax book: straight line at the Tax Code's annual rate on the cost, from the same
    first month, to `until` or until the cost is used up."""
    if not annual_rate or start is None or cost <= 0:
        return []
    month = first_of(start) if rule == DAILY else add_months(first_of(start), 1)
    monthly = money(Decimal(cost) * Decimal(annual_rate) / 100 / 12)
    left = money(cost)
    rows: list[tuple[date, Decimal]] = []
    while left > 0 and month <= first_of(until):
        amount = min(monthly, left)
        rows.append((month, amount))
        left -= amount
        month = add_months(month, 1)
    return rows
