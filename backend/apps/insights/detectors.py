"""The detection rules: each reads a company's numbers through the other apps' contracts
(`apps.finance.queries` and `planning`, `apps.sales.queries`, `apps.inventory.queries`) and says
what it found, as `Finding`s with the numbers behind them. `engine.run` stores them.

One finding per subject (`key`): the same subject found again updates its insight, a subject
no longer found resolves it. Thresholds scale with the company's sensitivity (low: only big
changes, high: small ones too) and money thresholds with `expense_alert_min_amount`.

    cash_low             the 30-day forecast's low point under the cash buffer
    branch_margin        a branch's margin (or profit) falling against the period before
    expense_spike        an expense category's last 7 days against its 8-week average
    overdue_receivables  overdue money customers owe, piling up
    overdue_payables     overdue supplier bills, piling up
    stock_build          stock value growing while sales fall (stock module)
    staff_cost           salaries and payroll taxes taking a growing share of revenue
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property

from django.db.models import Q, Sum

from apps.companies.models import Branch
from apps.core.money import quantize
from apps.insights.models import Insight, InsightSettings

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
Kind = Insight.Kind
Domain = Insight.Domain
Severity = Insight.Severity

SCALE = {
    InsightSettings.Sensitivity.LOW: Decimal("1.5"),
    InsightSettings.Sensitivity.NORMAL: Decimal(1),
    InsightSettings.Sensitivity.HIGH: Decimal("0.7"),
}

# Expense trees that are lumpy by nature or have a rule of their own: goods arrive in deliveries
# (stock_build watches them), salaries and their taxes are booked once a month (staff_cost),
# rent and taxes are monthly bills, depreciation and fixed assets follow their own plans.
SPIKE_EXCLUDED = (
    "goods",
    "salaries",
    "payroll_taxes",
    "rent",
    "taxes",
    "depreciation",
    "asset_disposal",
    "fx_diff",
)
SPIKE_WEEKS = 8
SPIKE_ACTIVE_WEEKS = 3  # a usual expense: spent in at least 3 of the 8 weeks before
MARGIN_MIN_DAYS = 7  # this month counts once it has a week of days; before that, last month
FORECAST_DAYS = 90  # the cockpit's forecast
CASH_DAYS = 30  # the cash low point counts within this many days
STAFF_CODES = ("salaries", "payroll_taxes")


@dataclass(frozen=True)
class Finding:
    key: str
    severity: str
    metrics: dict
    branch_id: int | None = None
    subject_type: str = ""
    subject_id: int | None = None
    subject_label: str = ""
    window_start: date | None = None
    window_end: date | None = None


@dataclass
class Context:
    """What every rule of one run shares: the company, its day and settings."""

    company: object
    today: date
    now: datetime
    settings: InsightSettings
    cache: dict = field(default_factory=dict)

    @property
    def scale(self) -> Decimal:
        return SCALE.get(self.settings.sensitivity, Decimal(1))

    @property
    def currency(self) -> str:
        return self.company.base_currency

    @property
    def min_amount(self) -> Decimal:
        return self.settings.expense_alert_min_amount or Decimal(1_000_000)

    @cached_property
    def branches(self) -> list[Branch]:
        return list(
            Branch.objects.filter(company=self.company, is_active=True).order_by("order", "pk")
        )


@dataclass(frozen=True)
class Detector:
    kind: str
    domain: str
    feature: str | None
    detect: Callable[[Context], list[Finding]]


DETECTORS: dict[str, Detector] = {}


def detector(kind: str, *, domain: str, feature: str | None):
    def register(fn: Callable[[Context], list[Finding]]):
        if kind in DETECTORS:
            raise ValueError(f"A detector for {kind!r} is already registered.")
        DETECTORS[kind] = Detector(kind, domain, feature, fn)
        return fn

    return register


def enabled(company, settings_row: InsightSettings) -> list[Detector]:
    """The rules that run for the company: module on, kind not switched off."""
    off = set(settings_row.disabled_kinds or ())
    return [
        rule
        for rule in DETECTORS.values()
        if rule.kind not in off and (rule.feature is None or company.has_feature(rule.feature))
    ]


def domain_of(kind: str) -> str:
    rule = DETECTORS.get(kind)
    return rule.domain if rule else Domain.FINANCE


# Shared pieces ----------------------------------------------------------------------------


def _round1(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return _round1(part / whole * 100) if whole else None


def month_start(day: date) -> date:
    return day.replace(day=1)


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def same_days_last_month(today: date) -> tuple[date, date]:
    """The days of last month that match this month so far (the finance overview's rule)."""
    first = month_start(today)
    last_start = add_months(first, -1)
    last_end = min(last_start + timedelta(days=(today - first).days), first - timedelta(days=1))
    return last_start, last_end


def cash_buffer(company, today: date) -> tuple[Decimal, str]:
    """The least cash to keep: the one buffer the owner sets on "Mening pulim" (Finance's
    `cash_buffer`), else one month of fixed costs. It is the amount "safe to take" keeps back
    (`apps.finance.owner_draw.cash_buffer`), so the cockpit and the owner's money agree."""
    from apps.finance import owner_draw

    found = owner_draw.cash_buffer(company, today)
    return quantize(found["amount"]), ("fixed_costs" if found["auto"] else "setting")


def low_point_causes(
    company, today: date, low_day: date, *, branch_ids, limit: int = 3
) -> list[dict]:
    """The biggest payments due in the week before the cash low point (anything due before it
    when that week has none), in the base currency: what makes cash that low."""
    from apps.finance import queries

    days = max(1, (low_day - today).days)
    upcoming = queries.upcoming(company, days, branch_ids=branch_ids, today=today)
    value = queries.valuation(company, today)
    payments = []
    for item in upcoming["items"]:
        if item["direction"] != "out" or item["amount"] is None:
            continue
        base = value.to_base(Decimal(item["amount"]), item["currency"])
        if not base:
            continue
        due = max(date.fromisoformat(item["date"]), today)
        if due > low_day:
            continue
        payments.append(
            {
                "title": item["title"],
                "kind": item["kind"],
                "date": due.isoformat(),
                "amount": str(quantize(base)),
                "overdue": item["overdue"],
            }
        )
    near = [p for p in payments if date.fromisoformat(p["date"]) >= low_day - timedelta(days=6)]
    chosen = near or payments
    chosen.sort(key=lambda p: Decimal(p["amount"]), reverse=True)
    return chosen[:limit]


def _forecast(ctx: Context, days: int) -> dict:
    key = ("forecast", days)
    if key not in ctx.cache:
        from apps.finance import queries

        ctx.cache[key] = queries.forecast(ctx.company, days, branch_ids=None, today=ctx.today)
    return ctx.cache[key]


# The rules --------------------------------------------------------------------------------


@detector(Kind.CASH_LOW, domain=Domain.FINANCE, feature="finance")
def cash_low(ctx: Context) -> list[Finding]:
    """The low point of the next 30 days of the cockpit's 90-day forecast (one forecast, so the
    insight and the runway chart never disagree about a day)."""
    forecast = _forecast(ctx, FORECAST_DAYS)
    points = forecast["points"][: CASH_DAYS + 1]
    if not points:
        return []
    buffer, source = cash_buffer(ctx.company, ctx.today)
    lowest = min(points, key=lambda point: Decimal(point["balance"]))
    low = Decimal(lowest["balance"])
    low_day = date.fromisoformat(lowest["date"])
    below = next((point["date"] for point in points if Decimal(point["balance"]) < 0), None)
    if low >= buffer and below is None:
        return []
    metrics = {
        "value": str(quantize(low)),
        "baseline": forecast["start"],
        "threshold": str(buffer),
        "unit": "money",
        "currency": ctx.currency,
        "low_date": low_day.isoformat(),
        "below_zero_on": below,
        "short_by": str(quantize(max(buffer - low, ZERO))),
        "days": CASH_DAYS,
        "buffer_source": source,
        "causes": low_point_causes(ctx.company, ctx.today, low_day, branch_ids=None),
        "series": [point["balance"] for point in points],
    }
    return [
        Finding(
            key=Kind.CASH_LOW.value,
            severity=Severity.CRITICAL if low < 0 or below else Severity.WARNING,
            metrics=metrics,
            window_start=ctx.today,
            window_end=low_day,
        )
    ]


def _expense_nodes(section: dict, index: int | None) -> dict[str, dict]:
    nodes = {}
    for node in section["nodes"]:
        amount = node["total"] if index is None else node["amounts"][index]
        nodes[str(node["system_code"] or node["id"])] = {
            "name": node["name"],
            "amount": amount,
            "previous": node["previous"] or ZERO,
        }
    return nodes


def _shares_up(costs: dict[str, dict], revenue: Decimal, revenue_before: Decimal) -> list[dict]:
    """The cost groups that took a bigger share of revenue than before (what moved the
    margin), the biggest rise first; half a point or more."""
    grown = []
    for cost in costs.values():
        share = _pct(cost["amount"], revenue)
        share_before = _pct(cost["previous"], revenue_before)
        if share is None or share_before is None or share - share_before < Decimal("0.5"):
            continue
        grown.append(
            {
                "name": cost["name"],
                "amount": str(cost["amount"]),
                "previous": str(cost["previous"]),
                "share": str(share),
                "share_previous": str(share_before),
            }
        )
    grown.sort(key=lambda c: Decimal(c["share"]) - Decimal(c["share_previous"]), reverse=True)
    return grown


@detector(Kind.BRANCH_MARGIN, domain=Domain.FINANCE, feature="finance")
def branch_margin(ctx: Context) -> list[Finding]:
    from apps.finance import queries

    if ctx.today.day >= MARGIN_MIN_DAYS:
        period = "month"
        current = (month_start(ctx.today), ctx.today)
        previous = same_days_last_month(ctx.today)
    else:
        period = "last_month"
        last = add_months(month_start(ctx.today), -1)
        current = (last, month_start(ctx.today) - timedelta(days=1))
        previous = (add_months(last, -1), last - timedelta(days=1))
    threshold = _round1(Decimal(3) * ctx.scale)
    min_revenue = ctx.min_amount * 5
    found = []
    for branch in ctx.branches:
        pnl = queries.pnl(ctx.company, *current, "month", branch_ids=[branch.pk], compare=previous)
        revenue = pnl["income"]["total"]
        revenue_before = pnl["income"]["previous"] or ZERO
        if revenue < min_revenue or revenue_before <= 0:
            continue
        profit = pnl["profit"]["total"]
        profit_before = pnl["profit"]["previous"] or ZERO
        margin = _round1(profit / revenue * 100)
        margin_before = _round1(profit_before / revenue_before * 100)
        drop = margin_before - margin
        profit_fell = (
            profit_before > 0
            and profit < profit_before * (1 - Decimal("0.25") * ctx.scale)
            and drop >= 1
        )
        turned_loss = profit < 0 <= profit_before
        if not (drop >= threshold or profit_fell or turned_loss):
            continue
        grown = _shares_up(_expense_nodes(pnl["expense"], None), revenue, revenue_before)
        metrics = {
            "value": str(margin),
            "baseline": str(margin_before),
            "threshold": str(threshold),
            "unit": "percent",
            "currency": ctx.currency,
            "period": period,
            "from": current[0].isoformat(),
            "to": current[1].isoformat(),
            "previous_from": previous[0].isoformat(),
            "previous_to": previous[1].isoformat(),
            "revenue": str(revenue),
            "revenue_previous": str(revenue_before),
            "profit": str(profit),
            "profit_previous": str(profit_before),
            "drop": str(_round1(drop)),
            "revenue_change": str(_pct(revenue - revenue_before, revenue_before)),
            "costs_up": grown[:3],
        }
        found.append(
            Finding(
                key=f"{Kind.BRANCH_MARGIN}:{branch.pk}",
                severity=Severity.CRITICAL if profit < 0 else Severity.WARNING,
                metrics=metrics,
                branch_id=branch.pk,
                subject_type="branch",
                subject_id=branch.pk,
                subject_label=branch.name,
                window_start=current[0],
                window_end=current[1],
            )
        )
    return found


def _spike_rows(ctx: Context, start: date):
    from apps.finance import queries, recurring
    from apps.finance.models import Category, Transaction

    excluded = Q(category__system_code__in=SPIKE_EXCLUDED) | Q(
        category__parent__system_code__in=SPIKE_EXCLUDED
    )
    return (
        queries.posted_rows(ctx.company, branch_ids=None)
        .filter(
            kind=Transaction.Kind.EXPENSE,
            capitalized=False,
            category__kind=Category.Kind.EXPENSE,
            occurred_on__range=(start, ctx.today),
        )
        .exclude(source_type=recurring.SOURCE)
        .exclude(excluded)
    )


@detector(Kind.EXPENSE_SPIKE, domain=Domain.FINANCE, feature="finance")
def expense_spike(ctx: Context) -> list[Finding]:
    """Per expense category (as booked, a subcategory on its own) across the company: what a
    category costs a whole company is what its owner weighs."""
    from apps.finance.models import Category

    week_start = ctx.today - timedelta(days=6)
    first = week_start - timedelta(days=7 * SPIKE_WEEKS)
    sums: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO] * (SPIKE_WEEKS + 1))
    for row in (
        _spike_rows(ctx, first)
        .values("category_id", "occurred_on")
        .annotate(total=Sum("base_amount"))
        .order_by()
    ):
        index = min((row["occurred_on"] - first).days // 7, SPIKE_WEEKS)
        sums[row["category_id"]][index] -= row["total"]
    ratio_needed = Decimal("1.8") * ctx.scale
    names = {category.pk: category.name for category in Category.objects.filter(pk__in=set(sums))}
    found = []
    for category_id, weeks in sums.items():
        current = quantize(weeks[SPIKE_WEEKS])
        before = weeks[:SPIKE_WEEKS]
        if sum(1 for amount in before if amount > 0) < SPIKE_ACTIVE_WEEKS:
            continue
        average = quantize(sum(before, ZERO) / SPIKE_WEEKS)
        if average <= 0 or current <= 0:
            continue
        ratio = _round1(current / average)
        excess = current - average
        if ratio < ratio_needed or excess < ctx.min_amount:
            continue
        severe = ratio >= 3 and excess >= ctx.min_amount * 5
        metrics = {
            "value": str(current),
            "baseline": str(average),
            "threshold": str(_round1(ratio_needed)),
            "unit": "money",
            "currency": ctx.currency,
            "ratio": str(ratio),
            "excess": str(quantize(excess)),
            "weeks": SPIKE_WEEKS,
            "from": week_start.isoformat(),
            "to": ctx.today.isoformat(),
            "series": [str(quantize(amount)) for amount in weeks],
        }
        found.append(
            Finding(
                key=f"{Kind.EXPENSE_SPIKE}:{category_id}",
                severity=Severity.CRITICAL if severe else Severity.WARNING,
                metrics=metrics,
                subject_type="category",
                subject_id=category_id,
                subject_label=names.get(category_id, ""),
                window_start=week_start,
                window_end=ctx.today,
            )
        )
    return found


def _overdue(ctx: Context, direction: str) -> dict | None:
    """Overdue debts of counterparties (people's pay and advances are payroll's) in one
    direction: total, count, the oldest, the biggest parties."""
    from apps.finance import queries

    total = ZERO
    count = 0
    oldest = 0
    parties: dict[int, dict] = {}
    rows = (
        queries.debts(ctx.company, direction, branch_ids=None, overdue_only=True, today=ctx.today)
        .filter(counterparty__isnull=False)
        .select_related("company", "counterparty")
    )
    for debt in rows:
        value = queries.book_value(debt, debt.amount - debt.paid)
        if value <= 0:
            continue
        days = queries.days_overdue(debt, ctx.today)
        total += value
        count += 1
        oldest = max(oldest, days)
        party = parties.setdefault(
            debt.counterparty_id, {"name": debt.counterparty.name, "amount": ZERO, "days": 0}
        )
        party["amount"] += value
        party["days"] = max(party["days"], days)
    if not count:
        return None
    biggest = sorted(parties.values(), key=lambda p: p["amount"], reverse=True)[:3]
    return {
        "total": quantize(total),
        "count": count,
        "oldest": oldest,
        "parties": [{**p, "amount": str(quantize(p["amount"]))} for p in biggest],
    }


def _overdue_finding(ctx: Context, kind: str, direction: str) -> list[Finding]:
    from apps.finance import queries

    found = _overdue(ctx, direction)
    if found is None:
        return []
    warning = ctx.min_amount * 3 * ctx.scale
    if found["total"] < warning:
        return []
    if kind == Kind.OVERDUE_RECEIVABLES:
        if found["count"] < 2 and found["oldest"] < 30:
            return []
        critical = found["total"] >= ctx.min_amount * 20 * ctx.scale
    else:
        critical = found["total"] >= ctx.min_amount * 10 * ctx.scale and found["oldest"] >= 30
    owed = queries.debt_totals(ctx.company, branch_ids=None, today=ctx.today)[direction]
    metrics = {
        "value": str(found["total"]),
        "baseline": str(quantize(owed["total"])),
        "threshold": str(quantize(warning)),
        "unit": "money",
        "currency": ctx.currency,
        "count": found["count"],
        "oldest_days": found["oldest"],
        "parties": found["parties"],
    }
    return [
        Finding(
            key=str(kind),
            severity=Severity.CRITICAL if critical else Severity.WARNING,
            metrics=metrics,
            window_end=ctx.today,
        )
    ]


@detector(Kind.OVERDUE_RECEIVABLES, domain=Domain.FINANCE, feature="finance")
def overdue_receivables(ctx: Context) -> list[Finding]:
    return _overdue_finding(ctx, Kind.OVERDUE_RECEIVABLES, "receivable")


@detector(Kind.OVERDUE_PAYABLES, domain=Domain.FINANCE, feature="finance")
def overdue_payables(ctx: Context) -> list[Finding]:
    return _overdue_finding(ctx, Kind.OVERDUE_PAYABLES, "payable")


STOCK_METRIC = "stock_value"
STOCK_DAYS = 28


def _sales(ctx: Context, start: date, end: date, branch_ids) -> Decimal:
    if ctx.company.has_feature("sales"):
        from apps.sales import queries as sales_queries

        return quantize(sales_queries.totals(ctx.company, start, end, branch_ids=branch_ids).net)
    from apps.finance import queries

    return queries.totals(ctx.company, start, end, branch_ids=branch_ids)["income"]


def record_stock(ctx: Context) -> dict[int | None, Decimal]:
    """Today's stock value at cost per branch (and in all), kept as snapshots: the stock module
    keeps no history of its value."""
    from apps.insights.models import Snapshot
    from apps.inventory import queries as stock_queries

    values: dict[int | None, Decimal] = {}
    for branch in ctx.branches:
        values[branch.pk] = stock_queries.stock_value(ctx.company, branch_ids=[branch.pk])["value"]
    values[None] = quantize(sum(values.values(), ZERO))
    for branch_id, value in values.items():
        Snapshot.objects.update_or_create(
            company=ctx.company,
            day=ctx.today,
            metric=STOCK_METRIC,
            branch_id=branch_id,
            defaults={"value": value},
        )
    return values


@detector(Kind.STOCK_BUILD, domain=Domain.FINANCE, feature="stock")
def stock_build(ctx: Context) -> list[Finding]:
    from apps.insights.models import Snapshot

    now_values = record_stock(ctx)
    then = ctx.today - timedelta(days=STOCK_DAYS)
    earlier = {}
    for snapshot in Snapshot.objects.filter(
        company=ctx.company,
        metric=STOCK_METRIC,
        day__range=(then - timedelta(days=7), then + timedelta(days=3)),
    ).order_by("day"):
        # The snapshot closest to four weeks ago wins (later ones overwrite earlier ones up
        # to that day; after it, only when nothing came before).
        if snapshot.day <= then or snapshot.branch_id not in earlier:
            earlier[snapshot.branch_id] = snapshot.value
    stock_needed = Decimal(10) * ctx.scale
    sales_needed = Decimal(5) * ctx.scale
    found = []
    for branch_id, value in now_values.items():
        before = earlier.get(branch_id)
        if not before or before <= 0:
            continue
        if branch_id is None and len(ctx.branches) <= 1:
            continue  # one branch: the branch finding says it all
        stock_change = _pct(value - before, before)
        scope = None if branch_id is None else [branch_id]
        recent = _sales(ctx, ctx.today - timedelta(days=STOCK_DAYS - 1), ctx.today, scope)
        prior = _sales(
            ctx,
            ctx.today - timedelta(days=2 * STOCK_DAYS - 1),
            ctx.today - timedelta(days=STOCK_DAYS),
            scope,
        )
        if prior <= 0:
            continue
        sales_change = _pct(recent - prior, prior)
        if stock_change < stock_needed or sales_change > -sales_needed:
            continue
        branch = next((b for b in ctx.branches if b.pk == branch_id), None)
        metrics = {
            "value": str(quantize(value)),
            "baseline": str(quantize(before)),
            "threshold": str(_round1(stock_needed)),
            "unit": "money",
            "currency": ctx.currency,
            "stock_change": str(stock_change),
            "sales": str(recent),
            "sales_previous": str(prior),
            "sales_change": str(sales_change),
        }
        found.append(
            Finding(
                key=f"{Kind.STOCK_BUILD}:{branch_id or 0}",
                severity=Severity.WARNING,
                metrics=metrics,
                branch_id=branch_id,
                subject_type="branch" if branch else "",
                subject_id=branch_id,
                subject_label=branch.name if branch else "",
                window_start=then,
                window_end=ctx.today,
            )
        )
    return found


@detector(Kind.STAFF_COST, domain=Domain.PAYROLL, feature="finance")
def staff_cost(ctx: Context) -> list[Finding]:
    from apps.finance import queries

    last = add_months(month_start(ctx.today), -1)
    first = add_months(last, -3)
    pnl = queries.pnl(
        ctx.company, first, month_start(ctx.today) - timedelta(days=1), "month", branch_ids=None
    )
    months = len(pnl["periods"])
    staff = [ZERO] * months
    for node in pnl["expense"]["nodes"]:
        if node["system_code"] in STAFF_CODES:
            staff = [staff[i] + node["amounts"][i] for i in range(months)]
    revenue = pnl["income"]["amounts"]
    shares = [
        _pct(staff[i], revenue[i]) if revenue[i] > 0 and staff[i] > 0 else None
        for i in range(months)
    ]
    current = shares[-1] if shares else None
    before = [share for share in shares[:-1] if share is not None]
    if current is None or not before:
        return []
    baseline = _round1(sum(before, ZERO) / len(before))
    needed = _round1(Decimal(3) * ctx.scale)
    if current - baseline < needed:
        return []
    month = date.fromisoformat(pnl["periods"][-1]["from"])
    metrics = {
        "value": str(current),
        "baseline": str(baseline),
        "threshold": str(needed),
        "unit": "percent",
        "currency": ctx.currency,
        "staff_cost": str(quantize(staff[-1])),
        "revenue": str(revenue[-1]),
        "month": month.strftime("%Y-%m"),
        "month_label": month.strftime("%m.%Y"),
        "series": [str(share) if share is not None else None for share in shares],
    }
    return [
        Finding(
            key=Kind.STAFF_COST.value,
            severity=Severity.WARNING,
            metrics=metrics,
            window_start=month,
            window_end=month_start(ctx.today) - timedelta(days=1),
        )
    ]
