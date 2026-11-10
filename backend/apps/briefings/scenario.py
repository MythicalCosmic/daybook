"""What if: the cash forecast with a change of money per month (`finance.planning.forecast`).

    what_if(company, branch_ids=None, today=today, monthly=Decimal("-30000000"),
            start=date(2026, 12, 1), one_off=Decimal("-50000000"))

The forecast as the cash plan shows it is the baseline; the scenario adds `one_off` once on
`start` and `monthly` on `start` and on the same day of each month after it (the last day of a
shorter month), the way rent or salaries fall. Both come back with their lowest point, the first
day below zero and how many days the money lasts (None: it lasts past the horizon), so "can I
afford a second pharmacy" is answered from the same numbers as the cash plan.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from apps.core.money import quantize

ZERO = Decimal(0)
MIN_DAYS, MAX_DAYS = 30, 120


def _month_days(start: date, until: date) -> list[date]:
    """`start` and the same day of every month after it, up to `until`."""
    found = []
    year, month = start.year, start.month
    while True:
        last = calendar.monthrange(year, month)[1]
        moment = date(year, month, min(start.day, last))
        if moment > until:
            return found
        found.append(moment)
        month += 1
        if month > 12:
            year, month = year + 1, 1


def _summary(points: list[tuple[date, Decimal]], today: date) -> dict:
    low_day, low = min(points, key=lambda point: point[1])
    below = next((day for day, balance in points if balance < 0), None)
    return {
        "low": {"date": low_day.isoformat(), "balance": str(quantize(low))},
        "below_zero_on": below.isoformat() if below else None,
        "runway_days": (below - today).days if below else None,
        "end": str(quantize(points[-1][1])),
    }


def what_if(
    company,
    *,
    branch_ids,
    today: date,
    monthly: Decimal,
    start: date | None = None,
    one_off: Decimal = ZERO,
    days: int = 90,
) -> dict:
    from apps.finance import planning

    days = max(MIN_DAYS, min(int(days), MAX_DAYS))
    start = max(start or today, today)
    plan = planning.forecast(company, days, branch_ids=branch_ids, today=today)
    base = [
        (date.fromisoformat(point["date"]), Decimal(point["balance"])) for point in plan["points"]
    ]
    until = today + timedelta(days=days)
    steps = {moment: monthly for moment in _month_days(start, until)}
    if one_off:
        steps[start] = steps.get(start, ZERO) + one_off
    changed = []
    running = ZERO
    for day, balance in base:
        running += steps.get(day, ZERO)
        changed.append((day, balance + running))
    return {
        "today": today.isoformat(),
        "days": days,
        "currency": plan["currency"],
        "cash_now": plan["start"],
        "change": {
            "monthly": str(quantize(monthly)),
            "one_off": str(quantize(one_off)),
            "from": start.isoformat(),
            "months_in_horizon": len(_month_days(start, until)),
            "total_in_horizon": str(quantize(running)),
        },
        "baseline": _summary(base, today),
        "scenario": _summary(changed, today),
    }
