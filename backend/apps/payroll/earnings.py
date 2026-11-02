"""The wallet's "earned so far this month" (docs/PLAN-OWNER.md §9.3): a plain module.

It runs the payslip calculation twice for one person: once as if the month ended today (the
days ahead count as not worked yet: "so far"), once for the whole month with the data as it is
(the days ahead as planned: the "estimate"). Bonuses, fines and advances are those of the month;
proposed ones are listed apart, they count only once approved. Cached for 10 minutes.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.payroll import calculator, periods, rules
from apps.payroll.models import Adjustment, PayslipLine

ZERO = Decimal(0)
Kind = PayslipLine.Kind
CACHE_SECONDS = 600
GROUPS = {
    "base": (Kind.BASE, Kind.PRORATION, Kind.LEAVE_COMPENSATION),
    "extra": (Kind.OVERTIME, Kind.NIGHT_WORK, Kind.HOLIDAY_WORK),
    "pieces": (Kind.PIECE, Kind.TASK_REWARD),
    "bonuses": (Kind.BONUS, Kind.ALLOWANCE),
    "fines": (Kind.FINE, Kind.DEDUCTION),
    "taxes": (Kind.INCOME_TAX, Kind.INPS),
    "advances": (Kind.ADVANCE,),
    "reimbursements": (Kind.REIMBURSEMENT,),
}


def _text(value: Decimal) -> str:
    return f"{value:.2f}"


def _sums(result) -> dict:
    lines = result.lines if result is not None else []
    found = {
        name: _text(sum((line.amount for line in lines if line.kind in kinds), ZERO))
        for name, kinds in GROUPS.items()
    }
    found["net"] = _text(sum((line.amount for line in lines), ZERO))
    return found


def cache_key(member) -> str:
    return f"payroll:earnings:{member.company_id}:{member.pk}"


def current(member, *, now: datetime | None = None, fresh: bool = False) -> dict:
    """What `member` has earned this month so far and the month's estimate (their own pay)."""
    key = cache_key(member)
    if not fresh and (found := cache.get(key)) is not None:
        return found
    found = _current(member, now or timezone.now())
    cache.set(key, found, CACHE_SECONDS)
    return found


def forget(member) -> None:
    cache.delete(cache_key(member))


def _current(member, now: datetime) -> dict:
    company = member.company
    today = periods.today(company, now)
    period = periods.first_day(today)
    inputs, people = calculator.gather(company, period, member_ids=[member.pk], now=now)
    person = people[0] if people else None
    estimate = calculator.compute(person, inputs) if person is not None else None
    so_far = None
    if person is not None:
        ended = today if person.employed_to is None else min(person.employed_to, today)
        so_far = calculator.compute(replace(person, employed_to=ended), inputs)
    proposed = Adjustment.objects.filter(
        membership=member, period=period, status=Adjustment.Status.PROPOSED
    ).order_by("created_at", "pk")
    return {
        "period": period.isoformat(),
        "as_of": today.isoformat(),
        "currency": inputs.currency,
        "has_pay_setup": person is not None and estimate is not None,
        "pay_type": estimate.pay_type if estimate is not None else None,
        "so_far": _sums(so_far),
        "estimate": _sums(estimate),
        "worked_minutes": so_far.worked_minutes if so_far is not None else 0,
        "scheduled_days": so_far.scheduled_days if so_far is not None else 0,
        "absent_days": so_far.absent_days if so_far is not None else 0,
        "proposed": [
            {
                "id": row.pk,
                "kind": row.kind,
                "amount": _text(row.amount),
                "reason": row.reason,
                "source": row.source,
            }
            for row in proposed
        ],
        "progress": [
            {
                **row,
                "value": _text(row["value"]),
                "earned": _text(row["earned"]),
                "target": _text(row["target"]) if row["target"] is not None else None,
                "target_amount": _text(row["target_amount"])
                if row["target_amount"] is not None
                else None,
                "limit": _text(row["limit"]) if row["limit"] is not None else None,
            }
            for row in rules.progress(member, period, now=now)
        ],
    }
