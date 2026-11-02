"""How a month's pay is worked out (docs/PLAN-OWNER.md §3.17, §14.11): a plain module.

`gather(company, period, …)` reads everything a run needs in a few queries (pay setups,
employment dates, shifts and attendance, leave, tasks, approved adjustments, advances,
reimbursements); `compute(person, inputs)` turns one person's month into payslip lines. It
writes nothing: `apps.payroll.runs` stores the result.

Money is Decimal all the way. Each line is rounded to the tiyin on its own (half up) and the
payslip's totals are the sums of its lines, so what a payslip shows always adds up; the net is
rounded by `rounding_step` last, as a line of its own.

Scheduled days `S` (§2.7): the days with a published planned or leave shift when the person has
any that month, otherwise the days in `Company.workdays`; holidays never count. A monthly
salary pays `amount / S` per day: days absent, on unpaid leave, outside the employment or
suspended without pay come off, paid leave below 100 % comes off by its missing share. Daily
and hourly earners are paid for what they worked plus paid leave. Overtime, work on a holiday
and night hours earn their multipliers on top, at the hourly rate `amount / (S * daily_hours)`
(monthly), `rate / daily_hours` (daily) or the rate itself (hourly).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.money import quantize
from apps.payroll import periods
from apps.payroll.models import (
    Adjustment,
    Advance,
    Compensation,
    PayrollSettings,
    PayslipLine,
    PayType,
    TaskRate,
)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
MINUTES = Decimal(60)
Kind = PayslipLine.Kind
Proration = Compensation.Proration


# Inputs ---------------------------------------------------------------------------------


@dataclass
class Record:
    """One attendance record, as payroll reads it."""

    day: date
    attended: bool
    absent: bool
    closed: bool
    worked_minutes: int
    overtime_minutes: int
    overtime_approved: bool
    is_late: bool
    late_minutes: int
    early_leave_minutes: int
    check_in_at: datetime | None
    check_out_at: datetime | None
    night_minutes: int = 0

    @property
    def paid_minutes(self) -> int:
        """Worked time, less overtime nobody approved."""
        if self.overtime_minutes and not self.overtime_approved:
            return max(0, self.worked_minutes - self.overtime_minutes)
        return self.worked_minutes


@dataclass
class LeaveDay:
    day: date
    kind: str
    paid: bool
    pay_percent: int


@dataclass
class DoneTask:
    id: int
    title: str
    template_id: int | None
    day: date
    on_time: bool
    reward: Decimal | None


@dataclass
class Reimbursement:
    debt_id: int
    amount: Decimal
    description: str


@dataclass
class Person:
    """Everything about one person's month."""

    member_id: int
    name: str
    position_id: int | None
    employed_from: date | None
    employed_to: date | None
    setups: list[Compensation] = field(default_factory=list)
    planned_days: set[date] = field(default_factory=set)
    records: list[Record] = field(default_factory=list)
    leave: dict[date, LeaveDay] = field(default_factory=dict)
    unpaid_suspension: dict[tuple[date, date], int] = field(default_factory=dict)
    task_stats: dict = field(default_factory=dict)
    done_tasks: list[DoneTask] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    advances: list[tuple[Advance, Decimal]] = field(default_factory=list)  # (advance, due)
    reimbursements: list[Reimbursement] = field(default_factory=list)


@dataclass
class Inputs:
    company: object
    settings: PayrollSettings
    period: date
    start: date
    end: date
    holidays: set[date]
    workdays: set[int]
    task_rates: list[TaskRate]
    usd_rate: Decimal | None
    currency: str

    @property
    def days_in_month(self) -> int:
        return (self.end - self.start).days + 1


# Output ---------------------------------------------------------------------------------


@dataclass
class Line:
    kind: str
    label: str
    amount: Decimal
    params: dict = field(default_factory=dict)
    quantity: Decimal | None = None
    rate: Decimal | None = None
    adjustment_id: int | None = None
    advance_id: int | None = None
    debt_id: int | None = None
    line_id: int | None = None  # a stored hand-made line this one stands for


@dataclass
class Result:
    member_id: int
    pay_type: str
    currency: str
    lines: list[Line]
    scheduled_days: int = 0
    paid_days: Decimal = ZERO
    paid_leave_days: int = 0
    unpaid_leave_days: int = 0
    absent_days: int = 0
    worked_minutes: int = 0
    overtime_minutes: int = 0
    night_minutes: int = 0
    late_arrivals: int = 0
    task_stats: dict = field(default_factory=dict)
    taxes: dict = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)


# Small helpers --------------------------------------------------------------------------


def money(value: Decimal) -> Decimal:
    return quantize(value)


def text(value: Decimal) -> str:
    return f"{value:.2f}" if isinstance(value, Decimal) else str(value)


def round_to_step(amount: Decimal, step: Decimal) -> Decimal:
    """`amount` rounded to the nearest multiple of `step` (half up); unchanged without a step."""
    if step is None or step <= Decimal("0.01"):
        return amount
    return (amount / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


def night_minutes(start: datetime, end: datetime, tz, starts_at, ends_at) -> int:
    """Minutes of [start, end] inside the night window (22:00 to 06:00 by default) of any night."""
    if start is None or end is None or end <= start:
        return 0
    local_start = timezone.localtime(start, tz)
    local_end = timezone.localtime(end, tz)
    total = 0
    for day in periods.days(local_start.date() - timedelta(days=1), local_end.date()):
        window_start = datetime.combine(day, starts_at, tzinfo=tz)
        window_end = datetime.combine(day, ends_at, tzinfo=tz)
        if window_end <= window_start:
            window_end = datetime.combine(day + timedelta(days=1), ends_at, tzinfo=tz)
        overlap = min(window_end, end) - max(window_start, start)
        if overlap.total_seconds() > 0:
            total += int(overlap.total_seconds() // 60)
    return total


def scheduled_days(person: Person, inputs: Inputs) -> set[date]:
    """`S` as days (§2.7, §3.17)."""
    if person.planned_days:
        base = person.planned_days
    else:
        base = {
            day
            for day in periods.days(inputs.start, inputs.end)
            if day.weekday() in inputs.workdays
        }
    return {day for day in base if day not in inputs.holidays}


def employed(person: Person, day: date) -> bool:
    if person.employed_from is None or day < person.employed_from:
        return False
    return person.employed_to is None or day <= person.employed_to


def segments(person: Person, inputs: Inputs) -> list[tuple[Compensation, date, date]]:
    """(setup, first day, last day) for each setup in force during the month, in order."""
    found = []
    setups = sorted(person.setups, key=lambda row: row.effective_from)
    for index, setup in enumerate(setups):
        first = max(setup.effective_from, inputs.start)
        following = setups[index + 1].effective_from if index + 1 < len(setups) else None
        last = inputs.end if following is None else min(inputs.end, following - timedelta(days=1))
        if first <= last:
            found.append((setup, first, last))
    return found


def _between(days, first: date, last: date) -> set[date]:
    return {day for day in days if first <= day <= last}


# The month of one person -----------------------------------------------------------------


def compute(person: Person, inputs: Inputs, manual_lines=()) -> Result | None:
    """One person's payslip lines for the month; None when no pay setup covers any of it."""
    parts = segments(person, inputs)
    if not parts:
        return None
    settings = inputs.settings
    result = Result(
        member_id=person.member_id,
        pay_type=parts[-1][0].pay_type,
        currency=inputs.currency,
        lines=[],
    )
    scheduled = scheduled_days(person, inputs)
    in_job = {day for day in periods.days(inputs.start, inputs.end) if employed(person, day)}
    attended_days = {record.day for record in person.records if record.attended}
    absent = {
        record.day
        for record in person.records
        if record.absent and record.day in scheduled and record.day not in person.leave
    } - attended_days
    result.scheduled_days = len(scheduled)
    result.task_stats = person.task_stats

    earnings: list[Line] = []
    unpaid_total = ZERO
    for setup, first, last in parts:
        amount = _in_payroll_currency(setup, inputs, result)
        if amount is None:
            continue
        seg_scheduled = _between(scheduled, first, last)
        seg_in_job = _between(in_job, first, last)
        seg_records = [r for r in person.records if first <= r.day <= last and r.day in seg_in_job]
        whole = first == inputs.start and last == inputs.end
        context = SegmentContext(
            person=person,
            inputs=inputs,
            setup=setup,
            amount=amount,
            first=first,
            last=last,
            whole=whole,
            scheduled=scheduled,
            seg_scheduled=seg_scheduled,
            seg_in_job=seg_in_job,
            seg_records=seg_records,
            absent=_between(absent, first, last) & seg_in_job,
            result=result,
        )
        if setup.pay_type == PayType.MONTHLY:
            earnings += _monthly(context)
        elif setup.pay_type == PayType.DAILY:
            earnings += _daily(context)
        elif setup.pay_type == PayType.HOURLY:
            earnings += _hourly(context)
        if setup.pay_type == PayType.PER_TASK or setup.pays_task_rates:
            earnings += _pieces(context)
        unpaid_total += context.unpaid_days

    # Who did what this month (for the payslip header), whatever the pay type.
    month_records = [r for r in person.records if r.day in in_job]
    result.worked_minutes = sum(r.worked_minutes for r in month_records if r.attended)
    result.overtime_minutes = sum(
        r.overtime_minutes for r in month_records if r.attended and r.overtime_approved
    )
    result.night_minutes = sum(r.night_minutes for r in month_records if r.closed)
    result.late_arrivals = sum(1 for r in month_records if r.attended and r.is_late)
    paid_leave = {
        day
        for day, leave in person.leave.items()
        if leave.paid and day in scheduled and day in in_job
    }
    unpaid_leave = {
        day
        for day, leave in person.leave.items()
        if not leave.paid and day in scheduled and day in in_job
    }
    result.paid_leave_days = len(paid_leave)
    result.unpaid_leave_days = len(unpaid_leave)
    result.absent_days = len(absent & in_job)
    not_in_job = len(scheduled - in_job)
    result.paid_days = Decimal(
        max(0, len(scheduled) - not_in_job - result.absent_days - len(unpaid_leave) - unpaid_total)
    )

    earnings += _rewards(person, inputs, in_job)
    lines = list(earnings)
    lines += _adjustment_lines(person, positive=True)
    lines += [_manual(line) for line in manual_lines]
    gross = sum((line.amount for line in lines), ZERO)
    lines += _capped_deductions(person, inputs, gross, result)
    lines += _taxes(gross, inputs, result)
    before_advances = sum((line.amount for line in lines), ZERO)
    lines += _advance_lines(person, before_advances, result)
    lines += [
        Line(
            kind=Kind.REIMBURSEMENT,
            label=_("Expenses paid back: %(what)s") % {"what": item.description}
            if item.description
            else str(Kind.REIMBURSEMENT.label),
            amount=money(item.amount),
            params={"code": "reimbursement", "what": item.description},
            debt_id=item.debt_id,
        )
        for item in person.reimbursements
    ]
    net = sum((line.amount for line in lines), ZERO)
    taken = -sum((line.amount for line in lines if line.kind == Kind.ADVANCE), ZERO)
    if net > 0:
        rounded = round_to_step(net, settings.rounding_step)
        # Rounding down never eats into what an advance takes back: the pay for the month
        # (the salary payable) must still cover the advance offsets.
        if rounded != net and before_advances - taken + (rounded - net) >= 0:
            lines.append(
                Line(
                    kind=Kind.ROUNDING,
                    label=str(Kind.ROUNDING.label),
                    amount=money(rounded - net),
                    params={"code": "rounding", "step": text(settings.rounding_step)},
                )
            )
    result.lines = lines
    return result


@dataclass
class SegmentContext:
    person: Person
    inputs: Inputs
    setup: Compensation
    amount: Decimal  # in the payroll currency
    first: date
    last: date
    whole: bool
    scheduled: set[date]
    seg_scheduled: set[date]
    seg_in_job: set[date]
    seg_records: list[Record]
    absent: set[date]
    result: Result
    unpaid_days: int = 0

    @property
    def settings(self) -> PayrollSettings:
        return self.inputs.settings

    def range_params(self) -> dict:
        if self.whole:
            return {}
        return {"from": self.first.isoformat(), "to": self.last.isoformat()}


def _in_payroll_currency(setup: Compensation, inputs: Inputs, result: Result) -> Decimal | None:
    if setup.currency == inputs.currency:
        return setup.amount
    if inputs.usd_rate is None:
        result.warnings.append({"code": "no_usd_rate", "currency": setup.currency})
        return None
    if inputs.currency == "UZS":
        return money(setup.amount * inputs.usd_rate)
    return money(setup.amount / inputs.usd_rate)


def _hours_rate(context: SegmentContext) -> tuple[Decimal, Decimal]:
    """(numerator, denominator) of the hourly rate, kept apart so lines round only once."""
    daily_hours = context.settings.daily_hours
    pay_type = context.setup.pay_type
    if pay_type == PayType.MONTHLY:
        days = Decimal(len(context.scheduled))
        if not days:
            return ZERO, Decimal(1)
        return context.amount, days * daily_hours
    if pay_type == PayType.DAILY:
        return context.amount, daily_hours
    return context.amount, Decimal(1)


def _extras(context: SegmentContext, *, base_includes_hours: bool) -> list[Line]:
    """Overtime, night work and holiday work: what every pay type earns on top."""
    settings = context.settings
    lines = []
    numerator, denominator = _hours_rate(context)
    if not numerator:
        return lines
    records = [r for r in context.seg_records if r.attended]
    overtime = sum(r.overtime_minutes for r in records if r.overtime_approved)
    if overtime and context.setup.overtime_eligible:
        multiplier = settings.overtime_multiplier - (1 if base_includes_hours else 0)
        if multiplier > 0:
            amount = money(numerator * multiplier * overtime / (MINUTES * denominator))
            lines.append(
                Line(
                    kind=Kind.OVERTIME,
                    label=str(Kind.OVERTIME.label),
                    amount=amount,
                    quantity=money(Decimal(overtime) / MINUTES),
                    rate=money(numerator / denominator),
                    params={
                        "code": "overtime",
                        "minutes": overtime,
                        "multiplier": text(settings.overtime_multiplier),
                        "premium_only": base_includes_hours,
                        **context.range_params(),
                    },
                )
            )
    night = sum(r.night_minutes for r in context.seg_records if r.closed)
    if night and settings.night_multiplier > 1:
        amount = money(
            numerator * (settings.night_multiplier - 1) * night / (MINUTES * denominator)
        )
        lines.append(
            Line(
                kind=Kind.NIGHT_WORK,
                label=str(Kind.NIGHT_WORK.label),
                amount=amount,
                quantity=money(Decimal(night) / MINUTES),
                rate=money(numerator / denominator),
                params={
                    "code": "night_work",
                    "minutes": night,
                    "multiplier": text(settings.night_multiplier),
                    **context.range_params(),
                },
            )
        )
    holidays = context.inputs.holidays
    on_holidays = [r for r in records if r.day in holidays]
    if on_holidays and settings.holiday_work_multiplier > 0:
        pay_type = context.setup.pay_type
        multiplier = settings.holiday_work_multiplier
        if pay_type == PayType.MONTHLY:
            days = Decimal(len({r.day for r in on_holidays}))
            scheduled = Decimal(len(context.scheduled)) or Decimal(1)
            amount = money(context.amount * multiplier * days / scheduled)
            quantity, rate = days, money(context.amount / scheduled)
        elif pay_type == PayType.DAILY:
            days = Decimal(len({r.day for r in on_holidays}))
            amount = money(context.amount * (multiplier - 1) * days)
            quantity, rate = days, context.amount
        else:
            minutes = sum(r.paid_minutes for r in on_holidays)
            amount = money(context.amount * (multiplier - 1) * minutes / MINUTES)
            quantity, rate = money(Decimal(minutes) / MINUTES), context.amount
        if amount:
            lines.append(
                Line(
                    kind=Kind.HOLIDAY_WORK,
                    label=str(Kind.HOLIDAY_WORK.label),
                    amount=amount,
                    quantity=quantity,
                    rate=rate,
                    params={
                        "code": "holiday_work",
                        "pay_type": pay_type,
                        "multiplier": text(multiplier),
                        **context.range_params(),
                    },
                )
            )
    return lines


def _base_params(context: SegmentContext, **extra) -> dict:
    params = {
        "code": "base",
        "pay_type": context.setup.pay_type,
        "proration": context.setup.proration,
        "setup": context.setup.pk,
        **context.range_params(),
        **extra,
    }
    if context.setup.currency != context.inputs.currency:
        params.update(
            original=text(context.setup.amount),
            original_currency=context.setup.currency,
            usd_rate=text(context.inputs.usd_rate),
        )
    return params


def _monthly(context: SegmentContext) -> list[Line]:
    amount = context.amount
    setup = context.setup
    inputs = context.inputs
    lines: list[Line] = []
    scheduled_total = len(context.scheduled)
    seg_days = len(context.seg_scheduled)
    if setup.proration == Proration.ATTENDANCE and scheduled_total:
        base = amount if context.whole else money(amount * seg_days / scheduled_total)
        lines.append(
            Line(
                kind=Kind.BASE,
                label=str(Kind.BASE.label),
                amount=base,
                quantity=None if context.whole else Decimal(seg_days),
                rate=None if context.whole else money(amount / scheduled_total),
                params=_base_params(context, days=seg_days, scheduled=scheduled_total),
            )
        )
        lines += _attendance_deductions(context, scheduled_total)
    elif setup.proration in (Proration.ATTENDANCE, Proration.CALENDAR):
        # Calendar days (or no scheduled day at all to divide by).
        employed_days = len(context.seg_in_job)
        whole_job = context.whole and employed_days == inputs.days_in_month
        base = amount if whole_job else money(amount * employed_days / inputs.days_in_month)
        lines.append(
            Line(
                kind=Kind.BASE,
                label=str(Kind.BASE.label),
                amount=base,
                quantity=None if whole_job else Decimal(employed_days),
                rate=None if whole_job else money(amount / inputs.days_in_month),
                params=_base_params(
                    context, days=employed_days, calendar_days=inputs.days_in_month
                ),
            )
        )
        if setup.proration == Proration.ATTENDANCE:
            context.result.warnings.append({"code": "no_scheduled_days"})
    else:
        if not context.seg_in_job:
            return lines
        calendar = (context.last - context.first).days + 1
        base = amount if context.whole else money(amount * calendar / inputs.days_in_month)
        lines.append(
            Line(
                kind=Kind.BASE,
                label=str(Kind.BASE.label),
                amount=base,
                params=_base_params(context, calendar_days=calendar),
            )
        )
    lines += _extras(context, base_includes_hours=False)
    return lines


def _attendance_deductions(context: SegmentContext, scheduled_total: int) -> list[Line]:
    """The days of `S` a monthly salary doesn't pay, at `amount / S` each."""
    amount = context.amount
    person = context.person
    lines = []
    seg = context.seg_scheduled
    in_job = context.seg_in_job
    rate = money(amount / scheduled_total)

    def unpaid(code: str, days: int, **params) -> None:
        if days <= 0:
            return
        lines.append(
            Line(
                kind=Kind.PRORATION,
                label=str(Kind.PRORATION.label),
                amount=-money(amount * days / scheduled_total),
                quantity=Decimal(days),
                rate=rate,
                params={"code": code, "days": days, **params, **context.range_params()},
            )
        )

    outside = sorted(seg - in_job)
    unpaid("not_employed", len(outside))
    unpaid("absent", len(context.absent))
    leave_unpaid = sorted(
        day for day in seg & in_job if (leave := person.leave.get(day)) and not leave.paid
    )
    unpaid("unpaid_leave", len(leave_unpaid))
    suspended = person.unpaid_suspension.get((context.first, context.last), 0)
    paid_here = len(seg & in_job) - len(context.absent) - len(leave_unpaid)
    suspended = max(0, min(suspended, paid_here))
    unpaid("suspended", suspended)
    context.unpaid_days = suspended
    # Paid leave below 100 %: the missing share of each day, grouped by kind and percent.
    partial: dict[tuple[str, int], int] = defaultdict(int)
    for day in sorted(seg & in_job):
        leave = person.leave.get(day)
        if leave is not None and leave.paid and leave.pay_percent < 100:
            partial[(leave.kind, leave.pay_percent)] += 1
    for (kind, percent), days in sorted(partial.items()):
        share = (HUNDRED - percent) / HUNDRED
        lines.append(
            Line(
                kind=Kind.PRORATION,
                label=str(Kind.PRORATION.label),
                amount=-money(amount * days * share / scheduled_total),
                quantity=Decimal(days),
                rate=money(amount * share / scheduled_total),
                params={
                    "code": "partial_leave",
                    "leave_kind": kind,
                    "percent": percent,
                    "days": days,
                    **context.range_params(),
                },
            )
        )
    return lines


def _daily(context: SegmentContext) -> list[Line]:
    rate = context.amount
    attended = {r.day for r in context.seg_records if r.attended}
    lines = []
    if attended:
        lines.append(
            Line(
                kind=Kind.BASE,
                label=str(Kind.BASE.label),
                amount=money(rate * len(attended)),
                quantity=Decimal(len(attended)),
                rate=rate,
                params=_base_params(context, days=len(attended)),
            )
        )
    lines += _paid_leave(context, day_value=rate, attended=attended)
    lines += _extras(context, base_includes_hours=True)
    return lines


def _hourly(context: SegmentContext) -> list[Line]:
    rate = context.amount
    minutes = sum(r.paid_minutes for r in context.seg_records if r.attended)
    attended = {r.day for r in context.seg_records if r.attended}
    lines = []
    if minutes:
        lines.append(
            Line(
                kind=Kind.BASE,
                label=str(Kind.BASE.label),
                amount=money(rate * minutes / MINUTES),
                quantity=money(Decimal(minutes) / MINUTES),
                rate=rate,
                params=_base_params(context, minutes=minutes),
            )
        )
    lines += _paid_leave(context, day_value=rate * context.settings.daily_hours, attended=attended)
    lines += _extras(context, base_includes_hours=True)
    return lines


def _paid_leave(context: SegmentContext, *, day_value: Decimal, attended: set[date]) -> list[Line]:
    """Daily and hourly earners: paid leave on scheduled days, at its pay percent."""
    groups: dict[tuple[str, int], int] = defaultdict(int)
    for day in sorted(context.seg_scheduled & context.seg_in_job):
        leave = context.person.leave.get(day)
        if leave is not None and leave.paid and leave.pay_percent > 0 and day not in attended:
            groups[(leave.kind, leave.pay_percent)] += 1
    lines = []
    for (kind, percent), days in sorted(groups.items()):
        value = day_value * Decimal(percent) / HUNDRED
        lines.append(
            Line(
                kind=Kind.LEAVE_COMPENSATION,
                label=str(Kind.LEAVE_COMPENSATION.label),
                amount=money(value * days),
                quantity=Decimal(days),
                rate=money(value),
                params={
                    "code": "paid_leave",
                    "leave_kind": kind,
                    "percent": percent,
                    "days": days,
                    **context.range_params(),
                },
            )
        )
    return lines


def best_rate(rates: list[TaskRate], template_id: int | None, position_id: int | None):
    """The most specific active rate: routine and position, routine, position, any."""
    ranked = []
    for rate in rates:
        if not rate.is_active:
            continue
        if rate.template_id is not None and rate.template_id != template_id:
            continue
        if rate.position_id is not None and rate.position_id != position_id:
            continue
        rank = (rate.template_id is None) * 2 + (rate.position_id is None)
        ranked.append((rank, rate.pk, rate))
    return min(ranked)[2] if ranked else None


def _pieces(context: SegmentContext) -> list[Line]:
    """Finished shared tasks of the segment at their task rate (per-task pay)."""
    person = context.person
    setup = context.setup
    groups: dict[object, list[DoneTask]] = defaultdict(list)
    rates: dict[object, tuple[Decimal, str]] = {}
    for task in person.done_tasks:
        if not (context.first <= task.day <= context.last) or task.day not in context.seg_in_job:
            continue
        rate = best_rate(context.inputs.task_rates, task.template_id, person.position_id)
        if rate is not None:
            if rate.on_time_only and not task.on_time:
                continue
            key = rate.pk
            rates[key] = (rate.amount, rate.template.title if rate.template_id else "")
        elif setup.pay_type == PayType.PER_TASK and setup.amount > 0:
            key = "default"
            rates[key] = (context.amount, "")
        else:
            continue
        groups[key].append(task)
    lines = []
    for key, tasks in sorted(groups.items(), key=lambda item: str(item[0])):
        amount, title = rates[key]
        lines.append(
            Line(
                kind=Kind.PIECE,
                label=str(Kind.PIECE.label),
                amount=money(amount * len(tasks)),
                quantity=Decimal(len(tasks)),
                rate=amount,
                params={
                    "code": "piece",
                    "rate": key if key != "default" else None,
                    "routine": title,
                    "tasks": len(tasks),
                    **context.range_params(),
                },
            )
        )
    return lines


def _rewards(person: Person, inputs: Inputs, in_job: set[date]) -> list[Line]:
    """The reward promised on a task, once it is accepted."""
    return [
        Line(
            kind=Kind.TASK_REWARD,
            label=str(Kind.TASK_REWARD.label),
            amount=money(task.reward),
            params={"code": "task_reward", "task": task.id, "title": task.title},
        )
        for task in person.done_tasks
        if task.reward and task.reward > 0 and task.day in in_job
    ]


def _adjustment_line(row: Adjustment, amount: Decimal, **params) -> Line:
    kind = {
        Adjustment.Kind.BONUS: Kind.BONUS,
        Adjustment.Kind.ALLOWANCE: Kind.ALLOWANCE,
        Adjustment.Kind.FINE: Kind.FINE,
        Adjustment.Kind.DEDUCTION: Kind.DEDUCTION,
    }[row.kind]
    return Line(
        kind=kind,
        label=row.reason,
        amount=amount,
        params={"code": "adjustment", "source": row.source, "reason": row.reason, **params},
        adjustment_id=row.pk,
    )


def _adjustment_lines(person: Person, *, positive: bool) -> list[Line]:
    wanted = Adjustment.POSITIVE if positive else Adjustment.NEGATIVE
    return [
        _adjustment_line(row, money(row.amount))
        for row in sorted(person.adjustments, key=lambda r: (r.created_at, r.pk))
        if row.kind in wanted
    ]


def _manual(line) -> Line:
    return Line(
        kind=Kind.MANUAL,
        label=line.label,
        amount=line.amount,
        params=dict(line.params or {}, code="manual"),
        line_id=line.pk,
    )


def _capped_deductions(
    person: Person, inputs: Inputs, gross: Decimal, result: Result
) -> list[Line]:
    """Fines and deductions, together at most `deductions_cap_percent` of the pay before them
    (oldest first); what goes beyond is not deducted and the run says so."""
    cap = money(max(gross, ZERO) * inputs.settings.deductions_cap_percent / HUNDRED)
    room = cap
    lines = []
    for row in sorted(person.adjustments, key=lambda r: (r.created_at, r.pk)):
        if row.kind not in Adjustment.NEGATIVE:
            continue
        taken = min(row.amount, room)
        room -= taken
        if taken < row.amount:
            lines.append(_adjustment_line(row, -taken, full=text(row.amount), capped=True))
        else:
            lines.append(_adjustment_line(row, -taken))
    capped = sum(
        (row.amount for row in person.adjustments if row.kind in Adjustment.NEGATIVE), ZERO
    )
    if capped > cap:
        result.warnings.append(
            {
                "code": "deductions_capped",
                "cap": text(cap),
                "asked": text(capped),
                "percent": text(inputs.settings.deductions_cap_percent),
            }
        )
    return lines


def _taxes(gross: Decimal, inputs: Inputs, result: Result) -> list[Line]:
    """Income tax and the pension contribution: withheld from gross amounts, or worked out on
    top of net ones (an estimate for the accountant); the employer's social tax on top."""
    settings = inputs.settings
    if not settings.taxes_enabled or gross <= 0:
        return []
    income = settings.income_tax_percent / HUNDRED
    pension = settings.inps_percent / HUNDRED
    social = settings.social_tax_percent / HUNDRED
    withheld = not settings.amounts_are_net
    taxable = gross if withheld else gross / (1 - income - pension)
    taxes = {
        "withheld": withheld,
        "taxable": text(money(taxable)),
        "income_tax": text(money(taxable * income)),
        "inps": text(money(taxable * pension)),
        "social_tax": text(money(taxable * social)),
    }
    result.taxes = taxes
    if not withheld:
        return []
    return [
        Line(
            kind=Kind.INCOME_TAX,
            label=str(Kind.INCOME_TAX.label),
            amount=-Decimal(taxes["income_tax"]),
            rate=None,
            params={"code": "income_tax", "percent": text(settings.income_tax_percent)},
        ),
        Line(
            kind=Kind.INPS,
            label=str(Kind.INPS.label),
            amount=-Decimal(taxes["inps"]),
            params={"code": "inps", "percent": text(settings.inps_percent)},
        ),
    ]


def _advance_lines(person: Person, available: Decimal, result: Result) -> list[Line]:
    """This month's share of each paid advance, never taking the pay below zero."""
    lines = []
    room = max(available, ZERO)
    for advance, due in person.advances:
        taken = min(due, room)
        room -= taken
        if taken < due:
            result.warnings.append(
                {
                    "code": "advance_reduced",
                    "advance": advance.pk,
                    "due": text(due),
                    "taken": text(taken),
                }
            )
        if taken > 0:
            lines.append(
                Line(
                    kind=Kind.ADVANCE,
                    label=str(Kind.ADVANCE.label),
                    amount=-taken,
                    params={
                        "code": "advance",
                        "advance": advance.pk,
                        "total": text(advance.amount),
                        "installments": advance.installments,
                    },
                    advance_id=advance.pk,
                )
            )
    return lines


# Gathering ------------------------------------------------------------------------------


def gather(
    company,
    period: date,
    *,
    member_ids=None,
    usd_rate: Decimal | None = None,
    now: datetime | None = None,
) -> tuple[Inputs, list[Person]]:
    """Everything `compute` needs for `period`, for everyone with a pay setup in force during
    it and employed at least one day of it (or only `member_ids`)."""
    from apps.attendance import queries as attendance
    from apps.attendance.models import AttendanceRecord, WorkShift
    from apps.finance import conf as finance_conf
    from apps.finance import queries as finance_queries
    from apps.hr.queries import employment_dates
    from apps.lifecycle.contracts import unpaid_days
    from apps.members.models import Membership
    from apps.payroll import conf, queries
    from apps.reports import kpis
    from apps.tasks.models import Task
    from apps.timeoff.queries import leave_summary

    now = now or timezone.now()
    settings = conf.get_settings(company)
    start, end = periods.bounds(period)
    inputs = Inputs(
        company=company,
        settings=settings,
        period=start,
        start=start,
        end=end,
        holidays=set(attendance.holidays(company, start, end)),
        workdays=set(company.workdays or []),
        task_rates=list(
            TaskRate.objects.for_company(company).filter(is_active=True).select_related("template")
        ),
        usd_rate=usd_rate,
        currency=settings.currency,
    )
    candidates = Membership.objects.for_company(company)
    if member_ids is not None:
        candidates = candidates.filter(pk__in=list(member_ids))
    setups = queries.in_force(candidates.values_list("pk", flat=True), start, end)
    ids = list(setups)
    dates = employment_dates(company, ids)
    members = {
        member.pk: member
        for member in Membership.objects.filter(pk__in=ids).select_related("user", "position")
    }
    people: dict[int, Person] = {}
    for member_id in ids:
        first, last = dates.get(member_id, (None, None))
        if first is None or first > end or (last is not None and last < start):
            continue
        member = members[member_id]
        people[member_id] = Person(
            member_id=member_id,
            name=str(member),
            position_id=member.position_id,
            employed_from=first,
            employed_to=last,
            setups=setups[member_id],
        )
    ids = list(people)
    if not ids:
        return inputs, []

    for member_id, day in (
        attendance.shifts_between(company, start, end, branch_ids=None, drafts=False)
        .filter(
            membership_id__in=ids,
            status__in=(WorkShift.Status.PLANNED, WorkShift.Status.LEAVE),
        )
        .values_list("membership_id", "date")
    ):
        people[member_id].planned_days.add(day)

    tz = periods.zone(company)
    closed = (AttendanceRecord.Status.CLOSED, AttendanceRecord.Status.AUTO_CLOSED)
    records = attendance.records_between(company, start, end, branch_ids=None).filter(
        membership_id__in=ids
    )
    for row in records.order_by("date", "pk"):
        record = Record(
            day=row.date,
            attended=row.status in AttendanceRecord.ATTENDED,
            absent=row.status == AttendanceRecord.Status.ABSENT,
            closed=row.status in closed and row.check_out_at is not None,
            worked_minutes=row.worked_minutes,
            overtime_minutes=row.overtime_minutes,
            overtime_approved=row.overtime_status == AttendanceRecord.Overtime.APPROVED,
            is_late=row.is_late,
            late_minutes=row.late_minutes,
            early_leave_minutes=row.early_leave_minutes,
            check_in_at=row.check_in_at,
            check_out_at=row.check_out_at,
        )
        if record.closed:
            record.night_minutes = night_minutes(
                row.check_in_at,
                row.check_out_at,
                tz,
                settings.night_starts_at,
                settings.night_ends_at,
            )
        people[row.membership_id].records.append(record)

    for member_id, summary in leave_summary(company, start, end, member_ids=ids).items():
        if member_id not in people:
            continue
        for leave in summary.days:
            people[member_id].leave[leave.day] = LeaveDay(
                leave.day, leave.kind, leave.paid, int(leave.pay_percent)
            )

    for member_id, person in people.items():
        member = members[member_id]
        for _setup, first, last in segments(person, inputs):
            seg_first = max(first, person.employed_from or first)
            seg_last = min(last, person.employed_to or last)
            if seg_first <= seg_last:
                person.unpaid_suspension[(first, last)] = int(
                    unpaid_days(member, seg_first, seg_last) or 0
                )

    report = kpis.team(company, start, end + timedelta(days=1), now, branch_ids=None)
    for member, score in report.rows:
        if member.pk in people:
            people[member.pk].task_stats = score.as_dict()

    since = datetime.combine(start, datetime.min.time(), tzinfo=tz)
    until = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    done = Task.objects.filter(
        company=company,
        assignee_id__in=ids,
        status=Task.Status.DONE,
        kind__in=(Task.Kind.DAILY, Task.Kind.ASSIGNED),
        completed_at__gte=since,
        completed_at__lt=until,
    ).values_list("pk", "assignee_id", "title", "template_id", "completed_at", "due_at", "reward")
    for pk, assignee_id, title, template_id, completed_at, due_at, reward in done.order_by(
        "completed_at", "pk"
    ):
        people[assignee_id].done_tasks.append(
            DoneTask(
                id=pk,
                title=title,
                template_id=template_id,
                day=timezone.localtime(completed_at, tz).date(),
                on_time=due_at is None or completed_at <= due_at,
                reward=reward,
            )
        )

    for row in Adjustment.objects.filter(
        company=company,
        membership_id__in=ids,
        period=start,
        status=Adjustment.Status.APPROVED,
    ).order_by("created_at", "pk"):
        people[row.membership_id].adjustments.append(row)

    advances = (
        Advance.objects.filter(
            company=company,
            membership_id__in=ids,
            status=Advance.Status.PAID,
            first_period__lte=start,
        )
        .prefetch_related("repayments")
        .order_by("first_period", "pk")
    )
    for advance in advances:
        due = queries.repayment_due(advance, start)
        if due > 0 and advance.currency == inputs.currency:
            people[advance.membership_id].advances.append((advance, due))

    if finance_conf.get_settings(company).reimburse_via == "payroll":
        debts = finance_queries.open_debts(
            company, kind="reimbursement", direction="payable"
        ).filter(membership_id__in=ids, locked_by_type="", currency=inputs.currency)
        for debt in debts:
            people[debt.membership_id].reimbursements.append(
                Reimbursement(debt.pk, debt.amount - debt.paid, debt.description)
            )
    return inputs, list(people.values())
