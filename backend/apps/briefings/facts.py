"""The facts of a business review: every number it may say, computed by the modules' own
queries for one reading scope (domains and branches). Nothing here is written by a model; the
words (apps.briefings.writing, or Claude through apps.ai.agents.advisor) only ever restate
these numbers.

    facts = build(company, period, scope, today=today)

Sections, each only when the scope has its domain (apps.briefings.scope):

- finance: revenue, gross profit and gross margin (income less medicines and goods), expenses,
  profit and margin, the payroll share (salaries and payroll taxes over revenue), each with the
  period before and the average of the periods before (`finance.queries.pnl`, per pharmacy
  too); the expense groups that grew most against their average; cash now and the forecast's
  low point and first day below zero (`finance.planning.forecast`); open and overdue debts.
- sales: net sales, receipts, the average receipt and the cash differences of the shifts.
- stock: what is on the shelves at cost (with finance), the slow movers (stock that would last
  90 days or more at the last 28 days' sales, or did not sell at all) and what expires soon.
- attendance: late arrivals and absences; people: who joined and who left.
- insights: the open insights (apps.insights, when it is installed).

Comparisons count only whole periods since the books began (a company that started six weeks
ago has no month to compare): a period before the first entry is left out of the average, and
`previous` is null when the period before has no data. Money is a string with two decimals
("48120000.00"), shares and changes are strings with one decimal ("4.2"). `signals` ranks
what matters (apps.briefings.signals).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Min

from apps.briefings import signals
from apps.briefings.periods import Period
from apps.briefings.scope import Scope
from apps.core.money import quantize

logger = logging.getLogger(__name__)

VERSION = 1
ZERO = Decimal(0)
HUNDRED = Decimal(100)
FORECAST_DAYS = 90
SOON_DAYS = 30
# Stock that would last this long at the recent sales pace is slow (or did not sell at all).
SLOW_DAYS = 90
VELOCITY_DAYS = 28
EXPIRY_DAYS = 60
SHOWN = 5
GOODS = "goods"
PAYROLL_CODES = ("salaries", "payroll_taxes")
# Paid once a month or less: a week they fall in is not a jump (the monthly review compares
# them), and neither is a group a recurring rule pays.
MONTHLY_CODES = (GOODS, "rent", "utilities", "taxes", *PAYROLL_CODES)


def money(value) -> str | None:
    if value is None:
        return None
    return str(quantize(Decimal(value)))


def one_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def share(part: Decimal | None, whole: Decimal | None) -> Decimal | None:
    """`part` as a percentage of `whole`, None without a whole."""
    if part is None or not whole:
        return None
    return part / whole * HUNDRED


def change_pct(value: Decimal, before: Decimal | None) -> str | None:
    """How much `value` moved from `before`, in percent of `before` ("-4.2"); None when the
    base is missing, zero or below zero (a move from a loss isn't a percentage)."""
    if before is None or before <= 0:
        return None
    return one_decimal((value - before) / before * HUNDRED)


def compared(value: Decimal, previous: Decimal | None, average: Decimal | None) -> dict:
    """A money figure with the period before and the average of the periods before."""
    return {
        "value": money(value),
        "previous": money(previous),
        "average": money(average),
        "change": money(value - previous) if previous is not None else None,
        "change_pct": change_pct(value, previous),
        "vs_average": money(value - average) if average is not None else None,
        "vs_average_pct": change_pct(value, average),
    }


def compared_share(value: Decimal | None, previous: Decimal | None, average: Decimal | None):
    """A percentage with the period before and the average, and the moves in points."""
    if value is None:
        return None
    return {
        "value": one_decimal(value),
        "previous": one_decimal(previous),
        "average": one_decimal(average),
        "change_pts": one_decimal(value - previous) if previous is not None else None,
        "vs_average_pts": one_decimal(value - average) if average is not None else None,
    }


def compared_count(value: int, previous: int | None, average: Decimal | None) -> dict:
    return {
        "value": value,
        "previous": previous,
        "average": one_decimal(average),
        "change": value - previous if previous is not None else None,
        "vs_average_pct": change_pct(Decimal(value), average),
    }


# Which periods to compare with ----------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """The period before (None: it has no data) and the whole periods averaged."""

    previous: tuple[date, date] | None
    average: tuple[date, date] | None
    count: int


def window(period: Period, first: date | None) -> Window:
    """The comparisons `period` can make when data begins on `first` (None: no data)."""
    if first is None:
        return Window(None, None, 0)
    previous = period.previous if period.previous[0] >= first else None
    starts = _period_starts(period)
    whole = [start for start in starts if start >= first]
    if not whole:
        return Window(previous, None, 0)
    return Window(previous, (min(whole), period.average[1]), len(whole))


def _period_starts(period: Period) -> list[date]:
    """The first days of the periods averaged, newest first."""
    from apps.briefings import periods

    found = []
    start = period.start
    for _number in range(period.count):
        before = periods.of(period.kind, start).previous[0]
        found.append(before)
        start = before
    return found


def _mean(total, count: int) -> Decimal | None:
    return Decimal(total) / count if count else None


# The P&L ---------------------------------------------------------------------------------------


@dataclass
class PnlNumbers:
    """The P&L of one range (and the compare range's), as the review reads it."""

    income: Decimal = ZERO
    expense: Decimal = ZERO
    profit: Decimal = ZERO
    goods: Decimal = ZERO
    payroll: Decimal = ZERO
    # top-level expense group id -> (name, total, system code)
    groups: dict[int, tuple[str, Decimal, str]] = field(default_factory=dict)
    previous: PnlNumbers | None = None

    @property
    def gross(self) -> Decimal:
        return self.income - self.goods


def pnl_numbers(company, start: date, end: date, *, branch_ids, compare=None) -> PnlNumbers:
    from apps.finance import queries as finance

    report = finance.pnl(company, start, end, "month", branch_ids=branch_ids, compare=compare)
    expense_nodes = report["expense"]["nodes"]

    def build(total_of) -> PnlNumbers:
        return PnlNumbers(
            income=total_of(report["income"]),
            expense=total_of(report["expense"]),
            profit=total_of(report["profit"]),
            goods=sum((total_of(n) for n in expense_nodes if n["system_code"] == GOODS), ZERO),
            payroll=sum(
                (total_of(n) for n in expense_nodes if n["system_code"] in PAYROLL_CODES), ZERO
            ),
            groups={
                node["id"]: (node["name"], total_of(node), node["system_code"])
                for node in expense_nodes
            },
        )

    numbers = build(lambda node: Decimal(node["total"] or 0))
    if compare is not None:
        numbers.previous = build(lambda node: Decimal(node["previous"] or 0))
    return numbers


def _average_pnl(company, frame: Window, *, branch_ids) -> PnlNumbers | None:
    if frame.average is None:
        return None
    total = pnl_numbers(company, *frame.average, branch_ids=branch_ids)
    count = frame.count
    return PnlNumbers(
        income=total.income / count,
        expense=total.expense / count,
        profit=total.profit / count,
        goods=total.goods / count,
        payroll=total.payroll / count,
        groups={
            key: (name, value / count, code) for key, (name, value, code) in total.groups.items()
        },
    )


def _pnl_block(now: PnlNumbers, before: PnlNumbers | None, average: PnlNumbers | None) -> dict:
    def pick(numbers: PnlNumbers | None, name: str):
        return getattr(numbers, name) if numbers is not None else None

    def margin_of(numbers: PnlNumbers | None, part: str):
        return share(pick(numbers, part), pick(numbers, "income")) if numbers else None

    return {
        "revenue": compared(now.income, pick(before, "income"), pick(average, "income")),
        "gross_profit": compared(now.gross, pick(before, "gross"), pick(average, "gross")),
        "gross_margin": compared_share(
            margin_of(now, "gross"), margin_of(before, "gross"), margin_of(average, "gross")
        ),
        "expenses": compared(now.expense, pick(before, "expense"), pick(average, "expense")),
        "profit": compared(now.profit, pick(before, "profit"), pick(average, "profit")),
        "margin": compared_share(
            margin_of(now, "profit"), margin_of(before, "profit"), margin_of(average, "profit")
        ),
    }


def _first_entry(company, branch_ids) -> date | None:
    """The first day income was booked: the books' comparisons start there (an opening debt or
    an old purchase entered months before doesn't make those months comparable)."""
    from apps.finance import queries as finance
    from apps.finance.models import Category

    rows = finance.posted_rows(company, branch_ids=branch_ids).filter(
        kind__in=finance.PNL_KINDS, capitalized=False, category__kind=Category.Kind.INCOME
    )
    return rows.aggregate(first=Min("occurred_on"))["first"]


def _ruled_groups(company, branch_ids) -> set[int]:
    """The expense groups (top level) a recurring rule pays."""
    from apps.finance import recurring
    from apps.finance.models import Category

    ids = set(
        recurring.visible_rules(company, branch_ids=branch_ids)
        .filter(is_active=True, category__isnull=False)
        .values_list("category_id", flat=True)
    )
    if not ids:
        return set()
    return {
        parent or pk
        for pk, parent in Category.objects.filter(pk__in=ids).values_list("pk", "parent_id")
    }


def _finance(company, period: Period, branch_ids, today: date, links) -> dict:
    from apps.companies.models import Branch
    from apps.finance import planning
    from apps.finance import queries as finance

    frame = window(period, _first_entry(company, branch_ids))
    current = pnl_numbers(
        company, period.start, period.end, branch_ids=branch_ids, compare=frame.previous
    )
    average = _average_pnl(company, frame, branch_ids=branch_ids)
    section = _pnl_block(current, current.previous, average)
    section["compared_periods"] = frame.count
    section["payroll"] = {
        "value": money(current.payroll),
        "share": compared_share(
            share(current.payroll, current.income),
            share(current.previous.payroll, current.previous.income) if current.previous else None,
            share(average.payroll, average.income) if average else None,
        ),
    }
    section["url"] = links.pnl()

    # The expense groups that grew most against their average. Goods follow the deliveries,
    # and in a weekly review what is paid monthly (rent, salaries, a recurring bill) lands in
    # one week of four: the monthly review compares those.
    skipped = set()
    if period.kind == "weekly":
        skipped = _ruled_groups(company, branch_ids)
    jumps = []
    for group_id, (name, total, code) in current.groups.items():
        if code == GOODS or (
            period.kind == "weekly" and (code in MONTHLY_CODES or group_id in skipped)
        ):
            continue
        usual = average.groups.get(group_id, ("", ZERO, code))[1] if average else None
        if usual is None or total <= usual:
            continue
        jumps.append(
            {
                "id": group_id,
                "name": name,
                "value": money(total),
                "average": money(usual),
                "change": money(total - usual),
                "vs_average_pct": change_pct(total, usual),
                "url": links.category(group_id),
            }
        )
    jumps.sort(key=lambda row: Decimal(row["change"]), reverse=True)
    section["expense_jumps"] = jumps[:3]

    # Each pharmacy in scope with money this period or the one before.
    branches = Branch.objects.filter(company=company, is_active=True).order_by("order", "name")
    if branch_ids is not None:
        branches = branches.filter(pk__in=branch_ids)
    rows = []
    for branch in branches:
        mine_frame = window(period, _first_entry(company, [branch.pk]))
        mine = pnl_numbers(
            company, period.start, period.end, branch_ids=[branch.pk], compare=mine_frame.previous
        )
        if not any((mine.income, mine.expense)) and not (
            mine.previous and (mine.previous.income or mine.previous.expense)
        ):
            continue
        usual = _average_pnl(company, mine_frame, branch_ids=[branch.pk])
        rows.append(
            {"id": branch.pk, "name": branch.name, "url": links.pnl(branch.pk)}
            | _pnl_block(mine, mine.previous, usual)
        )
    section["branches"] = rows

    # Cash now and where the forecast goes.
    plan = planning.forecast(company, FORECAST_DAYS, branch_ids=branch_ids, today=today)
    soon = min(plan["points"][: SOON_DAYS + 1], key=lambda point: Decimal(point["balance"]))
    below = plan["below_zero_on"]
    section["cash"] = {
        "now": plan["start"],
        "low_30": {"date": soon["date"], "balance": soon["balance"]},
        "low_90": plan["low"],
        "below_zero_on": below,
        "runway_days": (date.fromisoformat(below) - today).days if below else None,
        "horizon_days": FORECAST_DAYS,
        "daily_in": plan["basis"]["daily_in"],
        "daily_out": plan["basis"]["daily_out"],
        "url": links.cash(),
    }

    debts = finance.debt_totals(company, branch_ids=branch_ids, today=today)
    section["debts"] = {
        direction: {
            "open": money(values["total"]),
            "open_count": values["count"],
            "overdue": money(values["overdue"]),
            "overdue_count": values["overdue_count"],
            "url": links.debts(direction),
        }
        for direction, values in debts.items()
    }
    return section


# Sales -----------------------------------------------------------------------------------------


def _first_sales_day(company, branch_ids) -> date | None:
    from apps.members import scope as member_scope
    from apps.sales.models import DailySales

    rows = member_scope.restrict(DailySales.objects.for_company(company), branch_ids)
    return rows.aggregate(first=Min("day"))["first"]


def _sales(company, period: Period, branch_ids, links) -> dict:
    from apps.sales import queries as sales

    frame = window(period, _first_sales_day(company, branch_ids))
    now = sales.totals(company, period.start, period.end, branch_ids=branch_ids)
    before = (
        sales.totals(company, *frame.previous, branch_ids=branch_ids) if frame.previous else None
    )
    usual = sales.totals(company, *frame.average, branch_ids=branch_ids) if frame.average else None

    def receipt(totals) -> Decimal | None:
        if totals is None:
            return None
        return totals.net / totals.receipts if totals.receipts else ZERO

    return {
        "net": compared(
            now.net,
            before.net if before else None,
            _mean(usual.net, frame.count) if usual else None,
        ),
        "receipts": compared_count(
            now.receipts,
            before.receipts if before else None,
            _mean(usual.receipts, frame.count) if usual else None,
        ),
        "average_receipt": compared(receipt(now), receipt(before), receipt(usual)),
        "cash_difference": money(now.difference),
        "shifts": now.shifts,
        "compared_periods": frame.count,
        "url": links.sales(),
    }


# Stock -----------------------------------------------------------------------------------------


def _stock(company, branch_ids, today: date, *, costs: bool, links) -> dict:
    from apps.inventory import engine
    from apps.inventory import queries as inventory

    held: dict[int, dict] = defaultdict(lambda: {"quantity": ZERO, "value": ZERO, "name": ""})
    for row in inventory.stock_rows(company, branch_ids=branch_ids):
        product = row.batch.product
        entry = held[product.pk]
        entry["name"] = product.name
        entry["quantity"] += Decimal(row.quantity)
        entry["value"] += engine.value_of(row.batch, row.quantity)
    pace: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for (_branch, product_id), daily in inventory.velocity(
        company, branch_ids=branch_ids, days=VELOCITY_DAYS
    ).items():
        pace[product_id] += daily
    slow = []
    total_value = ZERO
    daily_cost = ZERO
    for product_id, entry in held.items():
        total_value += entry["value"]
        daily = pace.get(product_id, ZERO)
        if entry["quantity"] > 0 and daily > 0:
            daily_cost += entry["value"] / entry["quantity"] * daily
        days = int(entry["quantity"] / daily) if daily > 0 else None
        if entry["quantity"] > 0 and (days is None or days >= SLOW_DAYS):
            slow.append(
                {
                    "id": product_id,
                    "name": entry["name"],
                    "quantity": f"{entry['quantity'].normalize():f}",
                    "days_of_cover": days,
                    "sold_lately": daily > 0,
                    "value": money(entry["value"]) if costs else None,
                    "url": links.stock_item(entry["name"]),
                    "_rank": entry["value"] if costs else Decimal(days or 10_000),
                }
            )
    slow.sort(key=lambda row: row["_rank"], reverse=True)
    for row in slow:
        del row["_rank"]
    expiring = inventory.expiring_value(
        company, branch_ids=branch_ids, within_days=EXPIRY_DAYS, as_of=today
    )
    section = {
        "items": len(held),
        "slow_count": len(slow),
        "slow": slow[:SHOWN],
        "velocity_days": VELOCITY_DAYS,
        "expiring": {
            "within_days": EXPIRY_DAYS,
            "count": expiring["count"],
            "value": money(expiring["value"]) if costs else None,
            "expired_count": expiring["expired_count"],
            "url": links.expiry(),
        },
        "url": links.stock(),
    }
    if costs:
        section["value"] = money(total_value)
        section["days_of_cover"] = int(total_value / daily_cost) if daily_cost else None
    return section


# People ----------------------------------------------------------------------------------------


def _first_shift_day(company, branch_ids) -> date | None:
    from apps.attendance.models import WorkShift
    from apps.members import scope as member_scope

    rows = member_scope.restrict(WorkShift.objects.working().filter(company=company), branch_ids)
    return rows.aggregate(first=Min("date"))["first"]


def _attendance(company, period: Period, branch_ids, links) -> dict:
    from apps.attendance import queries as attendance

    def counted(start: date, end: date) -> dict:
        days = attendance.daily_counts(company, start, end, branch_ids=branch_ids)
        return {
            name: sum(day[name] for day in days.values())
            for name in ("rostered", "present", "late", "absent")
        }

    frame = window(period, _first_shift_day(company, branch_ids))
    now = counted(period.start, period.end)
    before = counted(*frame.previous) if frame.previous else None
    usual = counted(*frame.average) if frame.average else None
    on_time = share(Decimal(now["present"] - now["late"]), Decimal(now["present"]))
    return {
        "late": compared_count(
            now["late"],
            before["late"] if before else None,
            _mean(usual["late"], frame.count) if usual else None,
        ),
        "absent": compared_count(
            now["absent"],
            before["absent"] if before else None,
            _mean(usual["absent"], frame.count) if usual else None,
        ),
        "present": now["present"],
        "rostered": now["rostered"],
        "on_time_pct": one_decimal(on_time),
        "compared_periods": frame.count,
        "url": links.attendance(),
    }


def _people(company, period: Period, branch_ids, links) -> dict:
    from apps.hr.queries import employment_dates
    from apps.members.queries import directory

    current = list(directory(company, branch_ids=branch_ids, status="current"))
    former = list(directory(company, branch_ids=branch_ids, status="former"))
    dates = employment_dates(company, [member.pk for member in current + former])

    def within(day: date | None) -> bool:
        return day is not None and period.start <= day <= period.end

    joined = [m for m in current if within(dates.get(m.pk, (None, None))[0])]
    left = [m for m in former if within(dates.get(m.pk, (None, None))[1])]
    return {
        "headcount": len(current),
        "joined": [{"id": m.pk, "name": m.full_name or str(m)} for m in joined[:SHOWN]],
        "joined_count": len(joined),
        "left": [{"id": m.pk, "name": m.full_name or str(m)} for m in left[:SHOWN]],
        "left_count": len(left),
        "url": links.people(),
    }


# Insights (apps.insights, built beside this; skipped while it isn't there) ----------------------

# An insight's domain -> the review domain a reader needs to see it.
INSIGHT_DOMAINS = {
    "finance": "finance",
    "payroll": "finance",
    "sales": "sales",
    "stock": "stock",
    "inventory": "stock",
    "attendance": "attendance",
    "people": "people",
    "hr": "people",
    "tasks": "insights",
}


def open_insights(company, branch_ids) -> list:
    """The open insights in the branch scope, from `apps.insights.queries.open_for`; nothing
    when that app (or the function) isn't there or fails."""
    try:
        from apps.insights import queries as insight_queries

        return list(insight_queries.open_for(company, branch_ids) or [])
    except Exception:  # not installed yet, or broken: the review goes on without it
        logger.debug("No open insights for company %s", company.pk)
        return []


def _get(row, name, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _insights(company, branch_ids, domains, links) -> list[dict]:
    found = []
    for row in open_insights(company, branch_ids):
        needs = INSIGHT_DOMAINS.get(str(_get(row, "domain", "") or ""), "finance")
        if needs not in domains:
            continue
        pk = _get(row, "id") or _get(row, "pk")
        if pk is None:
            continue
        found.append(
            {
                "id": pk,
                "title": str(_get(row, "title", "") or "")[:160],
                "severity": str(_get(row, "severity", "info") or "info"),
                "suggested_action": str(_get(row, "suggested_action", "") or "")[:200],
                "url": links.insight(pk),
            }
        )
    order = {"critical": 0, "warning": 1}
    found.sort(key=lambda row: order.get(row["severity"], 2))
    return found[:SHOWN]


# The whole --------------------------------------------------------------------------------------


class Links:
    """Dashboard paths the review links to, for one company."""

    def __init__(self, company, period: Period):
        self.base = f"/c/{company.pk}"
        self.range = f"from={period.start.isoformat()}&to={period.end.isoformat()}"

    def pnl(self, branch_id: int | None = None) -> str:
        branch = f"&branch={branch_id}" if branch_id else ""
        return f"{self.base}/finance/reports/pnl?{self.range}{branch}"

    def category(self, category_id: int) -> str:
        return f"{self.base}/finance/reports/category-trend?category={category_id}"

    def cash(self) -> str:
        return f"{self.base}/finance/calendar"

    def debts(self, direction: str) -> str:
        return f"{self.base}/finance/reports/debts-aging?direction={direction}"

    def sales(self) -> str:
        return f"{self.base}/sales"

    def stock(self) -> str:
        return f"{self.base}/stock/levels"

    def stock_item(self, name: str) -> str:
        from urllib.parse import quote

        return f"{self.base}/stock/levels?q={quote(name[:60])}"

    def expiry(self) -> str:
        return f"{self.base}/stock/expiry"

    def attendance(self) -> str:
        return f"{self.base}/attendance/reports"

    def people(self) -> str:
        return f"{self.base}/people"

    def insight(self, pk) -> str:
        return f"{self.base}/insights?insight={pk}"


def build(company, period: Period, scope: Scope, *, today: date) -> dict:
    """The facts of the review of `period` for readers of `scope`."""
    domains = set(scope.domains)
    branch_ids = scope.branch_ids
    links = Links(company, period)
    facts: dict = {
        "version": VERSION,
        "kind": period.kind,
        "period": period.as_dict(),
        "today": today.isoformat(),
        "currency": company.base_currency,
        "company": company.name,
        "domains": sorted(domains),
        "every_branch": branch_ids is None,
    }
    if "finance" in domains:
        facts["finance"] = _finance(company, period, branch_ids, today, links)
    if "sales" in domains:
        facts["sales"] = _sales(company, period, branch_ids, links)
    if "stock" in domains:
        facts["stock"] = _stock(company, branch_ids, today, costs="finance" in domains, links=links)
    if "attendance" in domains:
        facts["attendance"] = _attendance(company, period, branch_ids, links)
    if "people" in domains:
        facts["people"] = _people(company, period, branch_ids, links)
    if "insights" in domains:
        facts["insights"] = _insights(company, branch_ids, domains, links)
    facts["signals"] = signals.of(facts)
    return facts


def _nonzero(*values) -> bool:
    return any(value is not None and Decimal(value) for value in values)


def is_empty(facts: dict) -> bool:
    """Nothing to review: no money moved, nothing sold, no stock, nobody rostered."""
    finance = facts.get("finance")
    if finance and (
        _nonzero(
            *(
                finance[name][key]
                for name in ("revenue", "expenses")
                for key in ("value", "previous")
            )
        )
        or _nonzero(finance["cash"]["now"])
    ):
        return False
    sales = facts.get("sales")
    if sales and _nonzero(sales["net"]["value"], sales["net"]["previous"]):
        return False
    stock = facts.get("stock")
    if stock and stock["items"]:
        return False
    attendance = facts.get("attendance")
    return not (attendance and attendance["rostered"])
