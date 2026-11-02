"""Read functions of payroll, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`); payroll
rows are bound to people, and a person to their branches (§2.6).

Contracts (docs/PLAN-OWNER.md §11.4): `compensation(membership)`, `run_summary(company, period)`,
`projected_cost(company, period)`.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Q, QuerySet, Sum
from django.utils import formats, translation

from apps.core.exceptions import DomainError
from apps.core.money import format_money, quantize
from apps.members import scope
from apps.members.models import Membership
from apps.payroll import conf, periods
from apps.payroll.models import (
    Adjustment,
    Advance,
    Compensation,
    PayrollRun,
    Payslip,
    PayslipLine,
    PayType,
)

ZERO = Decimal(0)


# Words ----------------------------------------------------------------------------------


def month_label(period: date) -> str:
    """ "Oktabr 2026", "Октябрь 2026", "October 2026" in the active language."""
    return formats.date_format(period, "F Y")


def money_text(amount: Decimal, currency: str, language: str | None = None) -> str:
    language = (language or translation.get_language() or "en")[:2]
    return format_money(amount, currency, language)


# Pay setups -----------------------------------------------------------------------------


def compensation(membership: Membership, *, on: date | None = None) -> Compensation | None:
    """The pay setup in force for `membership` on `on` (today in the company by default)."""
    on = on or periods.today(membership.company)
    return (
        Compensation.objects.filter(membership=membership, effective_from__lte=on)
        .order_by("-effective_from")
        .first()
    )


def in_force(member_ids, start: date, end: date) -> dict[int, list[Compensation]]:
    """{member id: the setups in force on some day from `start` to `end`, oldest first}: the
    last one starting on or before `start`, and every one starting inside the range."""
    rows = Compensation.objects.filter(membership_id__in=list(member_ids), effective_from__lte=end)
    found: dict[int, list[Compensation]] = defaultdict(list)
    for row in rows.order_by("membership_id", "effective_from"):
        found[row.membership_id].append(row)
    result = {}
    for member_id, items in found.items():
        before = [row for row in items if row.effective_from <= start]
        inside = [row for row in items if row.effective_from > start]
        result[member_id] = before[-1:] + inside
    return result


def compensation_ids_between(membership: Membership, start: date, end: date) -> set[int]:
    return {row.pk for row in in_force([membership.pk], start, end).get(membership.pk, [])}


def current_compensations(member_ids, on: date) -> dict[int, Compensation]:
    rows = (
        Compensation.objects.filter(membership_id__in=list(member_ids), effective_from__lte=on)
        .order_by("membership_id", "-effective_from")
        .distinct("membership_id")
    )
    return {row.membership_id: row for row in rows}


def next_compensations(member_ids, on: date) -> dict[int, Compensation]:
    """The next setup starting after `on` (a raise already planned)."""
    rows = (
        Compensation.objects.filter(membership_id__in=list(member_ids), effective_from__gt=on)
        .order_by("membership_id", "effective_from")
        .distinct("membership_id")
    )
    return {row.membership_id: row for row in rows}


def plain_scheduled_days(company, period: date) -> int:
    """The month's days in `Company.workdays` minus holidays (the §3.17 rule for people
    without planned shifts)."""
    from apps.attendance.queries import holidays

    start, end = periods.bounds(period)
    off = holidays(company, start, end)
    workdays = set(company.workdays or [])
    return sum(
        1 for day in periods.days(start, end) if day.weekday() in workdays and day not in off
    )


def in_payroll_currency(company, amount: Decimal, currency: str, day: date) -> Decimal | None:
    """`amount` in the payroll currency at the company's rate for `day`; None without a rate."""
    from apps.finance.rates import convert, rate_for

    target = conf.get_settings(company).currency
    if currency == target:
        return quantize(amount)
    try:
        rate = rate_for(company, "USD", day).rate
    except DomainError:
        return None
    return convert(amount, currency, target, rate)


def monthly_pay(membership: Membership, *, on: date | None = None) -> Decimal | None:
    """About what a month of work pays `membership` in the payroll currency: the monthly
    amount, a daily rate times the month's working days, an hourly rate times those days'
    hours, or the last payslip's gross for task pay. None when unknown."""
    company = membership.company
    on = on or periods.today(company)
    row = compensation(membership, on=on)
    if row is None:
        return None
    period = periods.first_day(on)
    if row.pay_type == PayType.MONTHLY:
        amount = row.amount
    elif row.pay_type == PayType.DAILY:
        amount = row.amount * plain_scheduled_days(company, period)
    elif row.pay_type == PayType.HOURLY:
        settings_row = conf.get_settings(company)
        amount = row.amount * plain_scheduled_days(company, period) * settings_row.daily_hours
    else:
        last = (
            Payslip.objects.filter(
                membership=membership,
                run__status__in=(PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID),
            )
            .order_by("-run__period")
            .values_list("gross", flat=True)
            .first()
        )
        return last
    return in_payroll_currency(company, amount, row.currency, on)


# Advances -------------------------------------------------------------------------------


def advance_left(advance: Advance) -> Decimal:
    """What is still owed on a paid advance."""
    repaid = advance.repayments.aggregate(total=Sum("amount"))["total"] or ZERO
    return advance.amount - repaid


def advance_cap(membership: Membership, *, on: date | None = None) -> dict:
    """How much of an advance the person may still ask for: `advance_cap_percent` of a
    month's pay, less what is asked, approved or paid and not yet paid back."""
    company = membership.company
    settings_row = conf.get_settings(company)
    base = monthly_pay(membership, on=on)
    percent = settings_row.advance_cap_percent
    cap = quantize((base or ZERO) * Decimal(percent) / Decimal(100))
    used = ZERO
    for advance in Advance.objects.filter(
        membership=membership, status__in=Advance.OPEN_STATUSES
    ).prefetch_related("repayments"):
        if advance.status == Advance.Status.PAID:
            used += advance.amount - sum((r.amount for r in advance.repayments.all()), ZERO)
        else:
            used += advance.amount
    return {
        "currency": settings_row.currency,
        "monthly_pay": base,
        "percent": percent,
        "cap": cap,
        "used": used,
        "available": max(ZERO, cap - used),
    }


def repayment_due(advance: Advance, period: date) -> Decimal:
    """The part of a paid advance `period`'s payslip takes: an equal share per instalment
    (the last one takes what is left), from `first_period` on, never more than is owed."""
    if advance.status != Advance.Status.PAID or period < advance.first_period:
        return ZERO
    left = advance.amount - sum((r.amount for r in advance.repayments.all()), ZERO)
    if left <= 0:
        return ZERO
    months_in = (period.year - advance.first_period.year) * 12 + (
        period.month - advance.first_period.month
    )
    if months_in + 1 >= advance.installments:
        return left
    share = quantize(advance.amount / Decimal(advance.installments))
    return min(share, left)


# Lists for the API ----------------------------------------------------------------------


def people_scope(queryset: QuerySet, branch_ids: list[int] | None, *, field: str = "membership"):
    """Rows of people inside `branch_ids` (a person belongs to their branches)."""
    if branch_ids is None:
        return queryset
    ids = Membership.objects.filter(branches__in=branch_ids).values("pk")
    return queryset.filter(**{f"{field}__in": ids})


def compensations(company, *, branch_ids: list[int] | None) -> QuerySet[Compensation]:
    rows = Compensation.objects.for_company(company).select_related(
        "membership__user", "membership__position", "membership__home_branch"
    )
    return people_scope(rows, branch_ids)


def adjustments(company, *, branch_ids: list[int] | None) -> QuerySet[Adjustment]:
    rows = Adjustment.objects.for_company(company).select_related(
        "membership__user", "membership__position", "rule", "proposed_by", "decided_by"
    )
    return people_scope(rows, branch_ids)


def advances(company, *, branch_ids: list[int] | None) -> QuerySet[Advance]:
    rows = (
        Advance.objects.for_company(company)
        .select_related("membership__user", "membership__position", "debt")
        .prefetch_related("repayments")
    )
    return people_scope(rows, branch_ids)


def payable_people(company, *, branch_ids: list[int] | None) -> QuerySet[Membership]:
    from apps.payroll.services import PAYABLE_STATUSES

    people = Membership.objects.for_company(company).filter(status__in=PAYABLE_STATUSES)
    if branch_ids is not None:
        people = Membership.objects.filter(
            pk__in=people.filter(branches__in=branch_ids).values("pk")
        )
    return people.select_related("user", "position", "home_branch")


# Counters -------------------------------------------------------------------------------


def open_proposals(company) -> QuerySet[Adjustment]:
    return Adjustment.objects.for_company(company).filter(status=Adjustment.Status.PROPOSED)


def open_disputes(company) -> QuerySet[Adjustment]:
    return Adjustment.objects.for_company(company).filter(
        disputed_at__isnull=False,
        dispute_answered_at__isnull=True,
        status__in=(Adjustment.Status.PROPOSED, Adjustment.Status.APPROVED),
    )


def requested_advances(company) -> QuerySet[Advance]:
    return Advance.objects.for_company(company).filter(status=Advance.Status.REQUESTED)


def _visible(member: Membership, queryset: QuerySet) -> QuerySet:
    return people_scope(queryset, scope.branch_ids(member)).exclude(membership=member)


def pending_count(member: Membership) -> int:
    """The `payroll.pending` badge: bonuses and fines to decide and disputes to answer."""
    company = member.company
    proposals = _visible(member, open_proposals(company))
    disputes = _visible(member, open_disputes(company))
    return Adjustment.objects.filter(
        Q(pk__in=proposals.values("pk")) | Q(pk__in=disputes.values("pk"))
    ).count()


def advances_count(member: Membership) -> int:
    return _visible(member, requested_advances(member.company)).count()


# Summaries (contracts, the overview, the AI tool) ---------------------------------------

DONE_STATUSES = (PayrollRun.Status.FINALIZED, PayrollRun.Status.PAID)


def regular_run(company, period: date) -> PayrollRun | None:
    return (
        PayrollRun.objects.for_company(company)
        .filter(kind=PayrollRun.Kind.REGULAR, period=periods.first_day(period))
        .exclude(status=PayrollRun.Status.CANCELLED)
        .first()
    )


def _sum(rows, field: str) -> Decimal:
    return sum((getattr(row, field) for row in rows), ZERO)


def _line_sums(payslip_ids) -> dict[str, Decimal]:
    Kind = PayslipLine.Kind
    totals = {"bonuses": ZERO, "fines": ZERO, "advances": ZERO}
    for kind, amount in PayslipLine.objects.filter(payslip_id__in=list(payslip_ids)).values_list(
        "kind", "amount"
    ):
        if kind in (Kind.BONUS, Kind.ALLOWANCE, Kind.TASK_REWARD):
            totals["bonuses"] += amount
        elif kind in (Kind.FINE, Kind.DEDUCTION):
            totals["fines"] -= amount
        elif kind == Kind.ADVANCE:
            totals["advances"] -= amount
    return totals


def run_summary(company, period: date, *, branch_ids: list[int] | None = None) -> dict | None:
    """The month's regular run in sums (people, gross, deductions, net, bonuses, fines,
    advances) over the people in `branch_ids`; None without a run."""
    run = regular_run(company, period)
    if run is None:
        return None
    payslips = list(people_scope(run.payslips.all(), branch_ids))
    lines = _line_sums(p.pk for p in payslips)
    return {
        "run": run.pk,
        "period": run.period.isoformat(),
        "status": run.status,
        "currency": conf.get_settings(company).currency,
        "people": len(payslips),
        "gross": _sum(payslips, "gross"),
        "deductions": _sum(payslips, "deductions"),
        "net": _sum(payslips, "net"),
        "paid": sum(1 for p in payslips if p.status == Payslip.Status.PAID),
        **lines,
    }


def projected_cost(company, period: date, *, branch_ids: list[int] | None = None) -> dict:
    """What `period` costs in pay: the finalized run's sums, or else the month worked out
    with today's data (days ahead counted as planned)."""
    from apps.payroll import calculator

    summary = run_summary(company, period, branch_ids=branch_ids)
    if summary is not None and summary["status"] in DONE_STATUSES:
        return {"source": "run", **summary}
    inputs, people = calculator.gather(company, period)
    if branch_ids is not None:
        visible = set(
            Membership.objects.filter(branches__in=branch_ids).values_list("pk", flat=True)
        )
        people = [person for person in people if person.member_id in visible]
    gross = net = ZERO
    count = 0
    for person in people:
        result = calculator.compute(person, inputs)
        if result is None:
            continue
        count += 1
        net += sum((line.amount for line in result.lines), ZERO)
        gross += sum(
            (line.amount for line in result.lines if line.kind in PayslipLine.EARNINGS),
            ZERO,
        )
    return {
        "source": "estimate",
        "period": periods.first_day(period).isoformat(),
        "currency": inputs.currency,
        "people": count,
        "gross": gross,
        "net": net,
    }


def overview(company, *, months: int, branch_ids: list[int] | None, today: date) -> dict:
    """The payroll overview: the last `months` months' runs, this month's projection, the
    latest closed month by position and by branch, what waits for a decision."""
    this_month = periods.first_day(today)
    first = periods.add_months(this_month, -(months - 1))
    runs = (
        PayrollRun.objects.for_company(company)
        .filter(kind=PayrollRun.Kind.REGULAR, period__gte=first)
        .exclude(status=PayrollRun.Status.CANCELLED)
        .order_by("period")
    )
    series = []
    for run in runs:
        summary = run_summary(company, run.period, branch_ids=branch_ids)
        series.append(
            {
                "period": run.period.isoformat(),
                "label": month_label(run.period),
                "status": run.status,
                "people": summary["people"],
                "gross": _text(summary["gross"]),
                "net": _text(summary["net"]),
                "bonuses": _text(summary["bonuses"]),
                "fines": _text(summary["fines"]),
                "advances": _text(summary["advances"]),
            }
        )
    latest = (
        PayrollRun.objects.for_company(company)
        .filter(kind=PayrollRun.Kind.REGULAR, status__in=DONE_STATUSES)
        .order_by("-period")
        .first()
    )
    by_position: dict = {}
    by_branch: dict = {}
    if latest is not None:
        payslips = people_scope(
            latest.payslips.select_related("membership__position", "membership__home_branch"),
            branch_ids,
        )
        for payslip in payslips:
            member = payslip.membership
            for table, key, label in (
                (
                    by_position,
                    member.position_id,
                    member.position.name if member.position_id else "",
                ),
                (
                    by_branch,
                    member.home_branch_id,
                    member.home_branch.name if member.home_branch_id else "",
                ),
            ):
                row = table.setdefault(
                    key, {"key": str(key or "none"), "label": label, "people": 0, "gross": ZERO}
                )
                row["people"] += 1
                row["gross"] += payslip.gross
    projected = projected_cost(company, this_month, branch_ids=branch_ids)
    current = current_compensations(
        payable_people(company, branch_ids=branch_ids).values_list("pk", flat=True), today
    )
    return {
        "currency": conf.get_settings(company).currency,
        "months": series,
        "latest": {"period": latest.period.isoformat(), "label": month_label(latest.period)}
        if latest
        else None,
        "by_position": [
            {**row, "gross": _text(row["gross"])}
            for row in sorted(by_position.values(), key=lambda row: -row["gross"])
        ],
        "by_branch": [
            {**row, "gross": _text(row["gross"])}
            for row in sorted(by_branch.values(), key=lambda row: -row["gross"])
        ],
        "projected": {
            "period": this_month.isoformat(),
            "label": month_label(this_month),
            "source": projected["source"],
            "people": projected["people"],
            "gross": _text(projected["gross"]),
            "net": _text(projected["net"]),
        },
        "headcount": len(current),
        "pending": {
            "adjustments": people_scope(open_proposals(company), branch_ids).count(),
            "disputes": people_scope(open_disputes(company), branch_ids).count(),
            "advances": people_scope(requested_advances(company), branch_ids).count(),
        },
    }


def _text(value: Decimal) -> str:
    return f"{value:.2f}"
