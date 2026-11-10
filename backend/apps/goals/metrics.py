"""The metrics a business goal tracks, each computed from the data of the module that owns it
(through that module's `queries`), never typed in by hand.

A metric has a unit (`money` in the base currency, `percent` or `count`), a direction (`up`:
more is better; `down`: less is better), a kind that says how progress and the forecast work,
the module that must be on and the permission that shows its numbers:

- `sum`    adds up over the period (revenue, gross and net profit): the forecast keeps the pace
           so far to the period's end
- `rate`   a share that grows over the period (staff turnover): forecast the same way
- `ratio`  an average over the period so far (margin, average check, late arrivals): the
           forecast is the value so far
- `level`  where something stands on a day (branches open, headcount, training completed):
           progress is the way from where it stood on day one to the target, against the time
           passed

Every number comes from the same query its own page uses: revenue, profit and margin from the
P&L (`finance.queries`), gross profit as income less "Medicines and goods", the average check
from the sales days (`sales.queries.totals`), headcount and turnover from the people HR counts
(`hr.queries`), late arrivals from the attendance summary and training from the mandatory
courses' compliance (`learning.queries.compliance`).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils.translation import gettext_lazy as _

from apps.goals.models import Metric
from apps.members.permissions import Perm

ZERO = Decimal(0)
HUNDRED = Decimal(100)
CENT = Decimal("0.01")

type Measure = Callable[[object, date, date, list[int] | None], Decimal | None]


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: object  # a lazy translation
    unit: str  # money, percent, count
    better: str  # up, down
    kind: str  # sum, rate, ratio, level
    feature: str | None
    perm: Perm | None
    branchable: bool
    measure: Measure
    hint: object = ""

    def available(self, company) -> bool:
        return self.feature is None or company.has_feature(self.feature)

    def visible_to(self, member) -> bool:
        return self.perm is None or member.has_perm(self.perm)


def _round(value: Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(CENT)


def _percent(part: Decimal, whole: Decimal) -> Decimal | None:
    if not whole:
        return None
    return _round(Decimal(part) / Decimal(whole) * HUNDRED)


# Money ---------------------------------------------------------------------------------------


def revenue(company, start: date, end: date, branch_ids) -> Decimal:
    from apps.finance import queries

    return _round(queries.totals(company, start, end, branch_ids=branch_ids)["income"])


def net_profit(company, start: date, end: date, branch_ids) -> Decimal:
    from apps.finance import queries

    return _round(queries.totals(company, start, end, branch_ids=branch_ids)["profit"])


def gross_profit(company, start: date, end: date, branch_ids) -> Decimal:
    """Income less the cost of medicines and goods (the P&L's "Medicines and goods" line)."""
    from apps.finance import queries

    pnl = queries.pnl(company, start, end, "month", branch_ids=branch_ids)
    goods = sum(
        (node["total"] for node in pnl["expense"]["nodes"] if node["system_code"] == "goods"),
        ZERO,
    )
    return _round(pnl["income"]["total"] - goods)


def margin(company, start: date, end: date, branch_ids) -> Decimal | None:
    """Net profit as a percent of income; None without income."""
    from apps.finance import queries

    totals = queries.totals(company, start, end, branch_ids=branch_ids)
    return _percent(totals["profit"], totals["income"])


def average_check(company, start: date, end: date, branch_ids) -> Decimal | None:
    """Net sales per receipt; None without receipts."""
    from apps.sales import queries

    totals = queries.totals(company, start, end, branch_ids=branch_ids)
    if not totals.receipts:
        return None
    return _round(totals.net / totals.receipts)


# People ----------------------------------------------------------------------------------------


def _employment(company, branch_ids) -> dict[int, tuple[date, date | None]]:
    from apps.hr import queries

    people = queries.people(company, branch_ids=branch_ids, statuses=queries.EMPLOYED)
    return queries.employment_dates(company, list(people.values_list("pk", flat=True)))


def _employed_on(dates: dict, day: date) -> int:
    return sum(
        1
        for hired, left in dates.values()
        if hired is not None and hired <= day and (left is None or left >= day)
    )


def headcount(company, start: date, end: date, branch_ids) -> Decimal:
    """The people employed on `end`, as the HR overview counts them."""
    return Decimal(_employed_on(_employment(company, branch_ids), end))


def turnover(company, start: date, end: date, branch_ids) -> Decimal | None:
    """People who left in the period per the average headcount (of its first and last day),
    in percent; None without anyone employed."""
    dates = _employment(company, branch_ids)
    left = sum(1 for _hired, gone in dates.values() if gone is not None and start <= gone <= end)
    average = Decimal(_employed_on(dates, start) + _employed_on(dates, end)) / 2
    if not average:
        return None
    return _percent(Decimal(left), average)


def late_arrivals(company, start: date, end: date, branch_ids) -> Decimal | None:
    """Late check-ins per day someone came in, in percent; None while nobody came."""
    from apps.attendance import queries

    summary = queries.period_summary(company, start, end, branch_ids=branch_ids)
    attended = sum(row.attended_days for row in summary.values())
    late = sum(row.late_arrivals for row in summary.values())
    return _percent(Decimal(late), Decimal(attended)) if attended else None


def training(company, start: date, end: date, branch_ids) -> Decimal | None:
    """People who finished every mandatory course, per the people who have one, in percent."""
    from apps.learning import queries

    moment = datetime.combine(end, time(23, 59), tzinfo=ZoneInfo(company.timezone))
    report = queries.compliance(company, branch_ids=branch_ids, now=moment)
    return _percent(Decimal(report.completed), Decimal(report.people)) if report.people else None


def branches(company, start: date, end: date, branch_ids) -> Decimal:
    """Branches open on `end` (pharmacies and warehouses; offices don't count)."""
    from apps.companies.models import Branch, BranchKind

    rows = Branch.objects.for_company(company).filter(is_active=True, created_at__date__lte=end)
    return Decimal(rows.exclude(kind=BranchKind.OFFICE).count())


# The catalogue -----------------------------------------------------------------------------------


METRICS: dict[str, MetricSpec] = {
    spec.key: spec
    for spec in (
        MetricSpec(
            Metric.REVENUE,
            Metric.REVENUE.label,
            "money",
            "up",
            "sum",
            "finance",
            Perm.FINANCE_VIEW,
            True,
            revenue,
            _("Income in the profit and loss statement."),
        ),
        MetricSpec(
            Metric.GROSS_PROFIT,
            Metric.GROSS_PROFIT.label,
            "money",
            "up",
            "sum",
            "finance",
            Perm.FINANCE_VIEW,
            True,
            gross_profit,
            _("Income less the cost of medicines and goods."),
        ),
        MetricSpec(
            Metric.NET_PROFIT,
            Metric.NET_PROFIT.label,
            "money",
            "up",
            "sum",
            "finance",
            Perm.FINANCE_VIEW,
            True,
            net_profit,
            _("Income less every expense, as the profit and loss statement shows it."),
        ),
        MetricSpec(
            Metric.MARGIN,
            Metric.MARGIN.label,
            "percent",
            "up",
            "ratio",
            "finance",
            Perm.FINANCE_VIEW,
            True,
            margin,
            _("Net profit as a percent of income."),
        ),
        MetricSpec(
            Metric.BRANCHES,
            Metric.BRANCHES.label,
            "count",
            "up",
            "level",
            None,
            None,
            False,
            branches,
            _("Pharmacies and warehouses that work."),
        ),
        MetricSpec(
            Metric.HEADCOUNT,
            Metric.HEADCOUNT.label,
            "count",
            "up",
            "level",
            None,
            Perm.MEMBERS_VIEW,
            True,
            headcount,
            _("People employed, as HR counts them."),
        ),
        MetricSpec(
            Metric.TURNOVER,
            Metric.TURNOVER.label,
            "percent",
            "down",
            "rate",
            None,
            Perm.MEMBERS_VIEW,
            True,
            turnover,
            _("People who left, per the average headcount of the period."),
        ),
        MetricSpec(
            Metric.AVERAGE_CHECK,
            Metric.AVERAGE_CHECK.label,
            "money",
            "up",
            "ratio",
            "sales",
            Perm.SALES_VIEW,
            True,
            average_check,
            _("Net sales per receipt."),
        ),
        MetricSpec(
            Metric.LATE_ARRIVALS,
            Metric.LATE_ARRIVALS.label,
            "percent",
            "down",
            "ratio",
            "attendance",
            Perm.ATTENDANCE_VIEW,
            True,
            late_arrivals,
            _("Late check-ins per day someone came in."),
        ),
        MetricSpec(
            Metric.TRAINING,
            Metric.TRAINING.label,
            "percent",
            "up",
            "level",
            "learning",
            Perm.LEARNING_VIEW,
            True,
            training,
            _("People who finished every mandatory course."),
        ),
    )
}


def spec(key: str) -> MetricSpec:
    return METRICS[key]


def for_member(member) -> list[MetricSpec]:
    """The metrics `member` may track: their module is on and they see its numbers."""
    company = member.company
    return [
        metric
        for metric in METRICS.values()
        if metric.available(company) and metric.visible_to(member)
    ]
