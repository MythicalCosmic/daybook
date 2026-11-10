"""Egasi paneli, the owner's cockpit, in one call (`GET cockpit/`).

    money       profit by branch from the P&L (`finance.queries.pnl`, one call per branch and
                one for the whole scope): this month so far against the same days of last
                month, and last month in full against the month before; per branch revenue,
                goods bought, gross margin, costs by top-level category, profit and margin,
                the monthly profit of the last six full months, and a state (red, amber,
                green). The company total, and what is booked on no branch (scope None only).
    cash        cash now, the 90-day forecast (`finance.planning.forecast`) with its low point
                and what causes it, the cash buffer and the runway in days.
    decisions   what waits for the caller's decision (`apps.insights.decisions`).
    insights    the live insights the caller may see.

Money needs `finance.view` and the finance module; without them `money` and `cash` are left
out. The money part is the slow one: it is cached per company, branch scope and day for
`TTL` seconds, and the key moves with the pulse versions of the ledger, so a change shows at
once. Decisions and insights are read fresh on every call.

Every amount comes from the P&L or the forecast as they are booked: nothing is estimated.
Salaries and depreciation are booked at the end of a month, so "this month so far" lacks them
until then; `missing` names the cost groups last month had that this month has none of yet.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.console import pulse
from apps.core.money import quantize
from apps.insights import decisions, detectors, queries
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

ZERO = Decimal(0)
TTL = 300
TREND_MONTHS = 6
HORIZON = 90
# Pulse keys whose change makes the cached money stale (unregistered ones simply read "0").
MONEY_KEYS = (
    "finance.ledger",
    "finance.claims",
    "companies.branches",
    "inventory",
    "payroll.runs",
    "payroll.pay",
    "assets",
    "sales.shifts",
)
# Cost groups booked once a month: "this month so far" may simply not have them yet.
MONTHLY_CODES = ("salaries", "payroll_taxes", "depreciation", "rent", "utilities")
MARGIN_DROP = Decimal(3)  # percentage points: amber
PROFIT_DROP = Decimal("0.2")  # a fifth less profit: amber


def sees_money(member: Membership) -> bool:
    return member.has_perm(Perm.FINANCE_VIEW) and member.company.has_feature("finance")


def build(member: Membership, *, now=None) -> dict:
    company = member.company
    now = now or timezone.now()
    from apps.finance import queries as finance

    today = finance.local_today(company, now)
    branch_ids = scope.branch_ids(member)
    data = {
        "today": today.isoformat(),
        "currency": company.base_currency,
        "generated_at": now.isoformat(),
        "can": {
            "money": sees_money(member),
            "insights": member.has_perm(Perm.REPORTS_VIEW),
            "settings": member.has_perm(Perm.COMPANY_SETTINGS)
            or member.has_perm(Perm.AI_CONFIGURE),
        },
    }
    insights = queries.summary(member)
    if sees_money(member):
        cached = money_and_cash(company, today, branch_ids)
        flagged = _flags(member)
        data["money"] = _with_states(cached["money"], flagged)
        data["cash"] = cached["cash"]
    data["decisions"] = decisions.collect(member)
    data["insights"] = insights
    return data


def _key(company, today: date, branch_ids) -> str:
    seen = "all" if branch_ids is None else ".".join(map(str, branch_ids)) or "none"
    versions = pulse.versions(company.pk, list(MONEY_KEYS))
    stamp = hashlib.sha256(
        "|".join(f"{key}={versions[key]}" for key in MONEY_KEYS).encode()
    ).hexdigest()[:12]
    return f"insights:cockpit:{company.pk}:{today.isoformat()}:{seen}:{stamp}"


def money_and_cash(company, today: date, branch_ids) -> dict:
    """The cached part: {"money", "cash"} for a branch scope."""
    key = _key(company, today, branch_ids)
    found = cache.get(key)
    if found is None:
        found = {
            "money": money(company, today, branch_ids),
            "cash": cash(company, today, branch_ids),
        }
        cache.set(key, found, TTL)
    return found


# Money ----------------------------------------------------------------------------------------


def _branches(company, branch_ids):
    from apps.companies.models import Branch

    rows = Branch.objects.filter(company=company, is_active=True).order_by("order", "pk")
    if branch_ids is not None:
        rows = rows.filter(pk__in=branch_ids)
    return list(rows)


def _s(value) -> str | None:
    return None if value is None else str(quantize(value))


def _margin(profit: Decimal, revenue: Decimal) -> str | None:
    if not revenue:
        return None
    return str((profit / revenue * 100).quantize(Decimal("0.1")))


def _section(pnl: dict, index: int, previous_index: int | None) -> dict:
    """One period of a P&L: revenue, goods, gross margin, costs by group, profit and margin,
    with the period it is compared with (`previous_index`, or the P&L's compare range when
    None)."""

    def at(node: dict, i: int | None) -> Decimal:
        if i is None:
            return node["previous"] or ZERO
        return node["amounts"][i] if 0 <= i < len(node["amounts"]) else ZERO

    def figures(i: int | None) -> dict:
        revenue = at(pnl["income"], i)
        expense = at(pnl["expense"], i)
        goods = sum(
            (at(node, i) for node in pnl["expense"]["nodes"] if node["system_code"] == "goods"),
            ZERO,
        )
        profit = revenue - expense
        return {
            "revenue": revenue,
            "goods": goods,
            "gross": revenue - goods,
            "expense": expense,
            "profit": profit,
        }

    now = figures(index)
    before = figures(previous_index) if previous_index is None or previous_index >= 0 else None
    costs = []
    for node in pnl["expense"]["nodes"]:
        amount = at(node, index)
        prior = at(node, previous_index) if before is not None else None
        if not amount and not prior:
            continue
        costs.append(
            {
                "key": node["system_code"] or str(node["id"]),
                "name": node["name"],
                "color": node["color"],
                "amount": _s(amount),
                "previous": _s(prior),
            }
        )
    costs.sort(key=lambda cost: Decimal(cost["amount"]), reverse=True)
    result = {
        "revenue": _s(now["revenue"]),
        "goods": _s(now["goods"]),
        "gross": _s(now["gross"]),
        "gross_margin": _margin(now["gross"], now["revenue"]),
        "expense": _s(now["expense"]),
        "profit": _s(now["profit"]),
        "margin": _margin(now["profit"], now["revenue"]),
        "costs": costs,
        "previous": None,
    }
    if before is not None:
        result["previous"] = {
            "revenue": _s(before["revenue"]),
            "gross": _s(before["gross"]),
            "gross_margin": _margin(before["gross"], before["revenue"]),
            "expense": _s(before["expense"]),
            "profit": _s(before["profit"]),
            "margin": _margin(before["profit"], before["revenue"]),
        }
    return result


def _missing(month: dict, last_month: dict) -> list[dict]:
    """Monthly cost groups last month had and this month has none of yet."""
    now = {cost["key"]: cost for cost in month["costs"]}
    return [
        {"key": cost["key"], "name": cost["name"], "last_month": cost["amount"]}
        for cost in last_month["costs"]
        if cost["key"] in MONTHLY_CODES
        and Decimal(cost["amount"]) > 0
        and not Decimal((now.get(cost["key"]) or {}).get("amount") or 0)
    ]


def periods(today: date) -> dict:
    first = detectors.month_start(today)
    last = detectors.add_months(first, -1)
    same_from, same_to = detectors.same_days_last_month(today)
    return {
        "month": {
            "from": first.isoformat(),
            "to": today.isoformat(),
            "previous_from": same_from.isoformat(),
            "previous_to": same_to.isoformat(),
        },
        "last_month": {
            "from": last.isoformat(),
            "to": (first - timedelta(days=1)).isoformat(),
            "previous_from": detectors.add_months(last, -1).isoformat(),
            "previous_to": (last - timedelta(days=1)).isoformat(),
        },
    }


def figures(company, today: date, branch_ids) -> dict:
    """This month so far and last month (each with what it is compared with) and the monthly
    profit trend, from one P&L of the last `TREND_MONTHS` months and this one."""
    from apps.finance import queries as finance

    first = detectors.month_start(today)
    start = detectors.add_months(first, -TREND_MONTHS)
    pnl = finance.pnl(
        company,
        start,
        today,
        "month",
        branch_ids=branch_ids,
        compare=detectors.same_days_last_month(today),
    )
    current = len(pnl["periods"]) - 1
    month = _section(pnl, current, None)
    last_month = _section(pnl, current - 1, current - 2)
    month["missing"] = _missing(month, last_month)
    trend = [
        {"month": period["key"], "profit": _s(amount)}
        for period, amount in zip(pnl["periods"][:-1], pnl["profit"]["amounts"][:-1], strict=True)
    ]
    return {"month": month, "last_month": last_month, "trend": trend}


def _subtract(total: dict, parts: list[dict]) -> dict:
    """What the scope's total has that no branch has: rows booked on no branch."""
    keys = ("revenue", "goods", "gross", "expense", "profit")
    result = {
        key: _s(Decimal(total[key]) - sum((Decimal(part[key]) for part in parts), ZERO))
        for key in keys
    }
    costs = []
    for cost in total["costs"]:
        rest = Decimal(cost["amount"]) - sum(
            (
                Decimal(other["amount"])
                for part in parts
                for other in part["costs"]
                if other["key"] == cost["key"]
            ),
            ZERO,
        )
        if rest:
            costs.append({"key": cost["key"], "name": cost["name"], "amount": _s(rest)})
    costs.sort(key=lambda cost: Decimal(cost["amount"]), reverse=True)
    return {**result, "costs": costs}


def money(company, today: date, branch_ids) -> dict:
    branches = []
    for branch in _branches(company, branch_ids):
        branches.append(
            {
                "id": branch.pk,
                "name": branch.name,
                "code": branch.code,
                **figures(company, today, [branch.pk]),
            }
        )
    total = figures(company, today, branch_ids)
    unassigned = None
    if branch_ids is None:
        unassigned = {
            name: _subtract(total[name], [b[name] for b in branches])
            for name in ("month", "last_month")
        }
        if not any(
            Decimal(unassigned[name][key])
            for name in ("month", "last_month")
            for key in ("revenue", "expense")
        ):
            unassigned = None
    return {
        "periods": periods(today),
        "total": total,
        "branches": branches,
        "unassigned": unassigned,
    }


def _flags(member: Membership) -> dict[int, str]:
    """The loudest live insight per branch the caller may see: {branch id: severity}."""
    from apps.insights import access
    from apps.insights.models import Insight

    flagged: dict[int, str] = {}
    rows = access.visible(member).filter(status__in=Insight.LIVE, branch__isnull=False)
    for branch_id, severity in rows.values_list("branch_id", "severity"):
        if flagged.get(branch_id) != Insight.Severity.CRITICAL:
            flagged[branch_id] = severity
    return flagged


def state(section: dict, flag: str | None) -> tuple[str, list[str]]:
    """Red (losing money, or an urgent insight), amber (margin or profit falling, or a
    warning), else green; with the reasons."""
    reasons = []
    profit = Decimal(section["profit"])
    previous = section.get("previous") or {}
    if profit < 0:
        reasons.append("loss")
    if flag == "critical":
        reasons.append("critical")
    if reasons:
        return "red", reasons
    margin, margin_before = section.get("margin"), previous.get("margin")
    if (
        margin is not None
        and margin_before is not None
        and Decimal(margin_before) - Decimal(margin) >= MARGIN_DROP
    ):
        reasons.append("margin_down")
    profit_before = Decimal(previous["profit"]) if previous.get("profit") else None
    if (
        profit_before is not None
        and profit_before > 0
        and profit < profit_before * (1 - PROFIT_DROP)
    ):
        reasons.append("profit_down")
    if flag == "warning":
        reasons.append("warning")
    return ("amber", reasons) if reasons else ("green", [])


def _with_states(data: dict, flagged: dict[int, str]) -> dict:
    branches = []
    for branch in data["branches"]:
        states = {}
        for name in ("month", "last_month"):
            color, reasons = state(branch[name], flagged.get(branch["id"]))
            states[name] = {"state": color, "reasons": reasons}
        branches.append({**branch, "states": states})
    return {**data, "branches": branches}


# Cash -----------------------------------------------------------------------------------------


def cash(company, today: date, branch_ids) -> dict:
    from apps.finance import queries as finance

    forecast = finance.forecast(company, HORIZON, branch_ids=branch_ids, today=today)
    buffer, source = detectors.cash_buffer(company, today)
    start = Decimal(forecast["start"])
    basis = forecast["basis"]
    daily = Decimal(basis["daily_out"]) + Decimal(basis["daily_paid"])
    cover = None
    if daily > 0:
        cover = max(int(start / daily), 0)
    below = forecast["below_zero_on"]
    to_zero = (date.fromisoformat(below) - today).days if below else None
    days, why = cover, "spending"
    if to_zero is not None and (cover is None or to_zero <= cover):
        days, why = to_zero, "forecast"
    low = forecast["low"]
    low_day = date.fromisoformat(low["date"])
    low_balance = Decimal(low["balance"])
    return {
        "currency": forecast["currency"],
        "now": forecast["start"],
        "buffer": str(buffer),
        "buffer_source": source,
        "daily_spend": str(quantize(daily)),
        "runway": {"days": days, "basis": why, "below_zero_on": below, "horizon": HORIZON},
        "low": {
            "date": low["date"],
            "balance": low["balance"],
            "short_by": str(quantize(max(-low_balance, ZERO))),
            "under_buffer_by": str(quantize(max(buffer - low_balance, ZERO))),
            "causes": detectors.low_point_causes(company, today, low_day, branch_ids=branch_ids),
        },
        "end": forecast["end"],
        "points": [{"date": p["date"], "balance": p["balance"]} for p in forecast["points"]],
        "basis": basis,
    }
