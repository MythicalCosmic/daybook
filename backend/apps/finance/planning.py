"""Cash planning (Package I, §1.6): what has to be paid and what comes in (`upcoming`), and the
30/60/90-day cash forecast with its low point (`forecast`).

Upcoming payments are:
- the open occurrences of recurring payments (bills, automatic posts, the tax calendar), an
  overdue bill first, on their due day after the holiday move;
- open debts to and from counterparties with a due date (payables and receivables);
- the pay the company owes its people (finalized payslips, expenses to pay back), as one line
  per day without names, the way the P&L shows salaries.

The forecast starts from the cash on every account in scope, adds the scheduled items above
(payables on their due day, an overdue payable today; receivables on their due day, never an
overdue one: it may not come) and the usual daily takings and spending (the average of the last
eight weeks of posted income and expenses that move money, without what the recurring rules with
a known amount already plan), and finds the lowest point and the first day below zero.

A pharmacy buys on credit: what it pays distributors is debt payments, not expenses, and only the
payables already booked are known. So the usual daily payments to suppliers (and collections of
what customers owe) are added too, but only after the last known due date of that side, when the
booked debts no longer cover the days ahead; nothing is counted twice.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.core.money import quantize
from apps.finance import queries, recurring
from apps.finance.models import Category, Debt, RecurringRule, Transaction

ZERO = Decimal(0)
MAX_DAYS = 120
RUN_RATE_DAYS = 56
PEOPLE_KINDS = (Debt.Kind.SALARY, Debt.Kind.REIMBURSEMENT)


@dataclass(frozen=True)
class Item:
    key: str
    kind: str  # bill, auto, tax, payable, receivable, payroll
    title: str
    subtitle: str
    date: date
    amount: Decimal | None  # in `currency`; None when nobody knows it yet
    currency: str
    direction: str  # in, out
    overdue: bool
    estimate: bool
    rule_id: int | None
    debt_id: int | None
    url: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "date": self.date.isoformat(),
            "amount": str(quantize(self.amount)) if self.amount is not None else None,
            "currency": self.currency,
            "direction": self.direction,
            "overdue": self.overdue,
            "estimate": self.estimate,
            "rule_id": self.rule_id,
            "debt_id": self.debt_id,
            "url": self.url,
        }


def items(company, today: date, until: date, *, branch_ids) -> list[Item]:
    """Everything due on or before `until`, overdue first, then by day."""
    found = [
        *_rule_items(company, today, until, branch_ids),
        *_debt_items(company, today, until, branch_ids),
    ]
    found.sort(key=lambda item: (not item.overdue, item.date, item.direction, item.title, item.key))
    return found


def upcoming(company, days: int = 30, *, branch_ids, today: date | None = None) -> dict:
    """The upcoming payments of the next `days` days (with what is overdue) and their totals
    in the base currency (`finance.queries.upcoming`, the AI tool and the brief section)."""
    days = max(1, min(int(days), MAX_DAYS))
    today = today or queries.local_today(company)
    rows = items(company, today, today + timedelta(days=days), branch_ids=branch_ids)
    value = queries.valuation(company, today)
    totals = defaultdict(lambda: ZERO)
    for item in rows:
        base = value.to_base(item.amount, item.currency) if item.amount is not None else None
        if base is None:
            continue
        totals[item.direction] += base
        if item.overdue:
            totals[f"overdue_{item.direction}"] += base
    return {
        "today": today.isoformat(),
        "days": days,
        "currency": company.base_currency,
        "items": [item.as_dict() for item in rows],
        "totals": {
            key: str(quantize(totals[key])) for key in ("out", "in", "overdue_out", "overdue_in")
        },
    }


def _rule_items(company, today: date, until: date, branch_ids) -> list[Item]:
    found = []
    for occurrence in recurring.due_items(company, today, until, branch_ids=branch_ids):
        rule = occurrence.rule
        tax = rule.template_key.startswith("tax.")
        unknown = rule.amount_varies and not rule.amount
        found.append(
            Item(
                key=f"rule:{rule.pk}:{occurrence.scheduled.isoformat()}",
                kind="tax" if tax else rule.mode,
                title=rule.name,
                subtitle=rule.counterparty.name if rule.counterparty_id else "",
                date=occurrence.due,
                amount=None if unknown else rule.amount,
                currency=rule.currency,
                direction="in" if rule.kind == Category.Kind.INCOME else "out",
                overdue=occurrence.due < today,
                estimate=rule.amount_varies,
                rule_id=rule.pk,
                debt_id=None,
                url=f"/c/{company.pk}/finance/recurring?rule={rule.pk}",
            )
        )
    return found


def _debt_items(company, today: date, until: date, branch_ids) -> list[Item]:
    debts = queries.scoped_debts(company, branch_ids=branch_ids).filter(status=Debt.Status.OPEN)
    found = []
    parties = (
        debts.filter(counterparty__isnull=False, due_on__isnull=False, due_on__lte=until)
        .select_related("counterparty")
        .order_by("due_on", "pk")
    )
    for debt in parties:
        payable = debt.direction == Debt.Direction.PAYABLE
        found.append(
            Item(
                key=f"debt:{debt.pk}",
                kind="payable" if payable else "receivable",
                title=debt.counterparty.name,
                subtitle=debt.description,
                date=debt.due_on,
                amount=debt.amount - debt.paid,
                currency=debt.currency,
                direction="out" if payable else "in",
                overdue=debt.due_on < today,
                estimate=False,
                rule_id=None,
                debt_id=debt.pk,
                url=f"/c/{company.pk}/finance/debts?debt={debt.pk}",
            )
        )
    # What the company owes its people: one line per day and currency, never per person.
    people = (
        debts.filter(
            membership__isnull=False,
            direction=Debt.Direction.PAYABLE,
            kind__in=PEOPLE_KINDS,
        )
        .filter(Q(due_on__isnull=True) | Q(due_on__lte=until))
        .values_list("due_on", "currency", "amount", "paid")
    )
    grouped: dict[tuple[date, str], list[Decimal]] = defaultdict(list)
    for due, currency, amount, paid in people:
        # Pay finalized without a due day is owed now.
        grouped[(due if due is not None else today, currency)].append(amount - paid)
    for (day, currency), amounts in sorted(grouped.items()):
        count = len(amounts)
        found.append(
            Item(
                key=f"payroll:{day.isoformat()}:{currency}",
                kind="payroll",
                title=_("Pay and expenses owed to the team"),
                subtitle=ngettext("%(count)s person", "%(count)s people", count) % {"count": count},
                date=day,
                amount=sum(amounts, ZERO),
                currency=currency,
                direction="out",
                overdue=day < today,
                estimate=False,
                rule_id=None,
                debt_id=None,
                url=f"/c/{company.pk}/finance/debts?direction=payable",
            )
        )
    return found


# The forecast ---------------------------------------------------------------------------------


def run_rate(company, today: date, *, branch_ids) -> dict:
    """The usual money in and out per day over the last eight weeks: posted income and expenses
    on accounts (without what recurring rules posted, and without the categories that rules with
    a known amount plan), and debt payments to suppliers and from customers."""
    start = today - timedelta(days=RUN_RATE_DAYS)
    window = queries.posted_rows(company, branch_ids=branch_ids).filter(
        account__isnull=False, occurred_on__gte=start, occurred_on__lt=today
    )
    planned = (
        recurring.visible_rules(company, branch_ids=branch_ids)
        .filter(is_active=True, amount__gt=0)
        .values_list("category_id", flat=True)
    )
    rows = (
        window.filter(kind__in=(Transaction.Kind.INCOME, Transaction.Kind.EXPENSE))
        .exclude(source_type=recurring.SOURCE)
        .exclude(category_id__in=list(planned))
    )
    payments = window.filter(kind=Transaction.Kind.DEBT_PAYMENT, counterparty__isnull=False)
    first = (
        window.filter(kind__in=(Transaction.Kind.INCOME, Transaction.Kind.EXPENSE, "debt_payment"))
        .order_by("occurred_on")
        .values_list("occurred_on", flat=True)
        .first()
    )
    observed = (today - first).days if first else 0
    if observed <= 0:
        return {
            "daily_in": ZERO,
            "daily_out": ZERO,
            "daily_collected": ZERO,
            "daily_paid": ZERO,
            "days_observed": 0,
        }
    sums = rows.aggregate(
        income=Sum("base_amount", filter=Q(base_amount__gt=0)),
        expense=Sum("base_amount", filter=Q(base_amount__lt=0)),
    )
    debts = payments.aggregate(
        collected=Sum("base_amount", filter=Q(debt__direction=Debt.Direction.RECEIVABLE)),
        paid=Sum("base_amount", filter=Q(debt__direction=Debt.Direction.PAYABLE)),
    )
    return {
        "daily_in": quantize((sums["income"] or ZERO) / observed),
        "daily_out": quantize(-(sums["expense"] or ZERO) / observed),
        "daily_collected": quantize((debts["collected"] or ZERO) / observed),
        "daily_paid": quantize(-(debts["paid"] or ZERO) / observed),
        "days_observed": observed,
    }


def forecast(company, days: int = 90, *, branch_ids, today: date | None = None) -> dict:
    """The cash balance day by day for `days` days (`finance.queries.forecast`)."""
    days = max(1, min(int(days), MAX_DAYS))
    today = today or queries.local_today(company)
    until = today + timedelta(days=days)
    start = queries.cash_position(company, None, branch_ids=branch_ids, today=today)["total"]
    value = queries.valuation(company, today)
    basis = run_rate(company, today, branch_ids=branch_ids)
    flows: dict[date, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])  # day -> [in, out]
    events = []
    # The last due day of the debts already booked, per side: after it, the usual payments to
    # suppliers (and collections from customers) carry on.
    covered = {"payable": today, "receivable": today}
    for item in items(company, today, until, branch_ids=branch_ids):
        if item.kind in covered and item.date > covered[item.kind]:
            covered[item.kind] = item.date
        if item.amount is None:
            continue
        if item.direction == "in" and item.overdue:
            continue  # an overdue receivable may never come
        base = value.to_base(item.amount, item.currency)
        if base is None or not base:
            continue
        day = max(item.date, today)
        flows[day][0 if item.direction == "in" else 1] += base
        events.append(
            {
                "date": day.isoformat(),
                "title": item.title,
                "amount": str(quantize(base)),
                "direction": item.direction,
            }
        )
    balance = start
    points = []
    low = None
    below_zero_on = None
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        money_in, money_out = flows.get(day, (ZERO, ZERO))
        if offset > 0:  # today's takings are already on the accounts
            money_in += basis["daily_in"]
            money_out += basis["daily_out"]
            if day > covered["receivable"]:
                money_in += basis["daily_collected"]
            if day > covered["payable"]:
                money_out += basis["daily_paid"]
        balance = quantize(balance + money_in - money_out)
        points.append(
            {
                "date": day.isoformat(),
                "balance": str(balance),
                "in": str(quantize(money_in)),
                "out": str(quantize(money_out)),
            }
        )
        if low is None or balance < low[1]:
            low = (day, balance)
        if below_zero_on is None and balance < 0:
            below_zero_on = day
    return {
        "today": today.isoformat(),
        "days": days,
        "currency": company.base_currency,
        "start": str(quantize(start)),
        "end": str(balance),
        "points": points,
        "low": {"date": low[0].isoformat(), "balance": str(low[1])},
        "below_zero_on": below_zero_on.isoformat() if below_zero_on else None,
        "basis": {
            "daily_in": str(basis["daily_in"]),
            "daily_out": str(basis["daily_out"]),
            "daily_collected": str(basis["daily_collected"]),
            "daily_paid": str(basis["daily_paid"]),
            "suppliers_from": covered["payable"].isoformat(),
            "days_observed": basis["days_observed"],
        },
        "events": events,
    }


def rule_count(company) -> int:
    return RecurringRule.objects.for_company(company).filter(is_active=True).count()
