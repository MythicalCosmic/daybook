"""The owner's money (v11): how much the owner can take out of the business today without
hurting it, why, what was taken and put in this month, and a monthly amount the cash forecast
can carry.

    cash now            every account of the company except the owner's own money (the
                        personal side, `MoneyAccount.Kind.OWNER`)
  - payments due        within `FinanceSettings.draw_horizon_days` (30): bills and automatic
                        payments, the tax calendar, payables to distributors and others (overdue
                        ones count now), loan instalments, pay owed to the team and the next
                        payroll (payroll's own figure for its next run while it isn't booked)
  - cash buffer         `FinanceSettings.cash_buffer`, or else one month of fixed costs
  - planned purchases   those due within the horizon, or without a date
  = safe to take        never below zero

Money owed to us is left out (it may come late, or never), and so are bills whose amount nobody
knows yet (they are listed). Everything is in the base currency at today's rate; foreign money
without any rate is left out of the cash (`complete` is then false).

Fixed costs are the expenses of the last 90 days (the books' age when younger) per 30 days,
without medicines and goods (they come back as sales) and without taxes (they follow sales and
are in the tax calendar): rent, pay, utilities, the bank and the like.

The suggested monthly draw is the largest amount that, taken on the first day of each of the
coming months, keeps the 90-day cash forecast (`planning.forecast`, without the owner's own
money) at or above the buffer every day.

Contract for other packages (the owner's cockpit, the advisor), company-wide, money as Decimal:

    safe_amount(company, on=None)              the breakdown above, with its reasons
    owner_flows(company, start, end)           draws and contributions in a period
    suggested_monthly(company, on=None)        the monthly draw the forecast carries
    cash_buffer(company, on=None)              {"amount", "auto", "fixed_costs"}
    fixed_costs(company, on=None)              one month of fixed costs
    history(company, months=6, on=None)        net profit, draws and contributions per month
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from django.db import transaction
from django.db.models import Min, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.finance import conf, planning, queries, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    Category,
    Debt,
    FinanceSettings,
    MoneyAccount,
    PlannedPurchase,
    Transaction,
)
from apps.members.models import Membership

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
Kind = MoneyAccount.Kind
# The personal side: the owner's own money, never counted as the business's cash.
PERSONAL_KINDS = (Kind.OWNER,)
# Where the owner takes money from or puts it into: the business's own money (not terminal
# money on its way to the bank, cash an employee holds or the owner's own money).
DRAW_KINDS = (Kind.CASH, Kind.BANK, Kind.CARD, Kind.WALLET, Kind.SAFE)
# Expense categories that follow sales instead of the calendar (with their subcategories).
VARIABLE_CODES = ("goods", "taxes")
FIXED_DAYS = 90
MONTH_DAYS = 30
SUGGEST_DAYS = 90
SUGGEST_MONTHS = 3
PROFIT_MONTHS = 3  # the full months whose average net profit the suggestion is shown against
MIN_HORIZON, MAX_HORIZON = 7, 90


@dataclass
class Reason:
    """One payment (or a group of them) the safe amount keeps back."""

    key: str
    kind: str  # bill, auto, tax, payable, payroll, loan, installment
    title: str
    subtitle: str
    date: date
    amount: Decimal | None  # in the base currency; None while nobody knows it
    count: int = 1
    overdue: bool = False
    estimate: bool = False
    url: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "date": self.date,
            "amount": quantize(self.amount) if self.amount is not None else None,
            "count": self.count,
            "overdue": self.overdue,
            "estimate": self.estimate,
            "url": self.url,
        }


class OverSafe(DomainError):
    """A draw above the safe amount that nobody confirmed."""

    def __init__(self, message: str, safe: Decimal):
        super().__init__(message)
        self.safe = safe


# The breakdown -----------------------------------------------------------------------------------


def safe_amount(company, on: date | None = None, *, horizon_days: int | None = None) -> dict:
    """How much is safe to take out today, and why (see the module's docstring).

    `on` is the day it is worked out for (today by default; the cash is that day's, the
    payments are the ones open now). Money comes back as Decimal, days as dates."""
    today = on or queries.local_today(company)
    settings_row = conf.get_settings(company)
    days = _horizon(horizon_days or settings_row.draw_horizon_days)
    until = today + timedelta(days=days)
    position = queries.cash_position(company, today, branch_ids=None)
    business = personal = ZERO
    for account in position["accounts"]:
        if account["base"] is None:
            continue
        if account["kind"] in PERSONAL_KINDS:
            personal += account["base"]
        else:
            business += account["base"]
    reasons = obligations(company, today, until)
    due = quantize(sum((reason.amount for reason in reasons if reason.amount is not None), ZERO))
    buffer = cash_buffer(company, today)
    purchases = planned_purchases(company, today, until)
    planned = quantize(sum((row.amount for row in purchases["kept"]), ZERO))
    needed = due + buffer["amount"] + planned
    safe = max(quantize(business - needed), ZERO)
    return {
        "today": today,
        "currency": company.base_currency,
        "horizon_days": days,
        "until": until,
        "cash": quantize(business),
        "personal": quantize(personal),
        "complete": position["complete"],
        "due": due,
        "reasons": [reason.as_dict() for reason in _ordered(reasons)],
        "unknown": sum(1 for reason in reasons if reason.amount is None),
        "buffer": buffer,
        "planned": planned,
        "purchases": purchases,
        "safe": safe,
        "short": max(quantize(needed - business), ZERO),
        "month": owner_flows(company, today.replace(day=1), today),
    }


def _horizon(days: int) -> int:
    return max(MIN_HORIZON, min(int(days), MAX_HORIZON))


def _ordered(reasons: list[Reason]) -> list[Reason]:
    """Overdue first, then the biggest; unknown amounts last."""
    return sorted(
        reasons,
        key=lambda r: (r.amount is None, not r.overdue, -(r.amount or ZERO), r.date, r.key),
    )


def obligations(company, today: date, until: date) -> list[Reason]:
    """What must be paid from today to `until` (overdue included), company-wide, as reasons:
    each bill and tax, the payables of each counterparty together, each loan instalment, and
    the team's pay in one line (never per person)."""
    value = queries.valuation(company, today)
    planned_debts = _debts_with_plan(company)
    reasons: list[Reason] = []
    by_party: dict[str, list[tuple[planning.Item, Decimal | None]]] = defaultdict(list)
    people: list[tuple[planning.Item, Decimal | None]] = []
    for item in planning.items(company, today, until, branch_ids=None):
        if item.direction != "out":
            continue  # money owed to us may never come
        if item.debt_id is not None and item.debt_id in planned_debts:
            continue  # its instalments are counted below
        base = value.to_base(item.amount, item.currency) if item.amount is not None else None
        if item.kind == "payable":
            by_party[item.title].append((item, base))
        elif item.kind == "payroll":
            people.append((item, base))
        else:  # bill, auto, tax
            reasons.append(
                Reason(
                    key=item.key,
                    kind=item.kind,
                    title=item.title,
                    subtitle=item.subtitle,
                    date=item.date,
                    amount=base,
                    overdue=item.overdue,
                    estimate=item.estimate,
                    url=item.url,
                )
            )
    for party, rows in by_party.items():
        known = [base for _item, base in rows if base is not None]
        first = min(item.date for item, _base in rows)
        reasons.append(
            Reason(
                key=f"payable:{rows[0][0].debt_id}",
                kind="payable",
                title=party,
                subtitle=ngettext("%(count)s payment", "%(count)s payments", len(rows))
                % {"count": len(rows)},
                date=first,
                amount=quantize(sum(known, ZERO)) if known else None,
                count=len(rows),
                overdue=any(item.overdue for item, _base in rows),
                url=f"/c/{company.pk}/finance/payables",
            )
        )
    reasons += _instalments(company, today, until, value, planned_debts)
    reasons += _payroll(company, today, until, people)
    return reasons


def _debts_with_plan(company) -> set[int]:
    """Open payables to counterparties that have an instalment plan."""
    return set(
        Debt.objects.for_company(company)
        .filter(
            status=Debt.Status.OPEN,
            direction=Debt.Direction.PAYABLE,
            counterparty__isnull=False,
            installments__isnull=False,
        )
        .values_list("pk", flat=True)
        .distinct()
    )


def _instalments(company, today, until, value, debt_ids: set[int]) -> list[Reason]:
    found = []
    debts = Debt.objects.filter(pk__in=debt_ids).select_related("counterparty", "company")
    for debt in debts.order_by("pk"):
        for row in queries.installment_schedule(debt, today):
            if row["status"] == "paid" or row["due_on"] > until:
                continue
            base = value.to_base(row["amount"] - row["paid"], debt.currency)
            found.append(
                Reason(
                    key=f"instalment:{row['id']}",
                    kind="loan" if debt.kind == Debt.Kind.LOAN else "installment",
                    title=debt.counterparty.name,
                    subtitle=debt.description or str(debt.get_kind_display()),
                    date=row["due_on"],
                    amount=base,
                    overdue=row["status"] == "overdue",
                    url=f"/c/{company.pk}/finance/debts?debt={debt.pk}",
                )
            )
    return found


def _payroll(company, today, until, people) -> list[Reason]:
    """The team's pay: what is booked and owed (finalized payslips, expenses to pay back), or
    payroll's own figure for its next run when that is more (its run isn't booked yet), and
    the pay days after it within the horizon."""
    booked = quantize(sum((base for _item, base in people if base is not None), ZERO))
    count = len(people)
    reasons = []
    pay_days = [(day, amount) for day, amount in payroll_estimates(company, today) if day <= until]
    url = f"/c/{company.pk}/payroll"
    if booked and (not pay_days or booked >= pay_days[0][1]):
        first = min(item.date for item, _base in people)
        reasons.append(
            Reason(
                key="payroll:booked",
                kind="payroll",
                title=_("Pay owed to the team"),
                subtitle=ngettext("%(count)s line", "%(count)s lines", count) % {"count": count},
                date=first,
                amount=booked,
                count=count,
                overdue=any(item.overdue for item, _base in people),
                url=f"/c/{company.pk}/finance/debts?direction=payable",
            )
        )
        pay_days = pay_days[1:]
    for day, amount in pay_days:
        reasons.append(
            Reason(
                key=f"payroll:{day.isoformat()}",
                kind="payroll",
                title=_("Payroll"),
                subtitle=_("Pay day"),
                date=day,
                amount=amount,
                estimate=True,
                url=url,
            )
        )
    return reasons


def payroll_estimates(company, today: date, months: int = 3) -> list[tuple[date, Decimal]]:
    """The next pay days and what each pays, from payroll's portfolio facts (its finalized run,
    or else its estimate of the month), through the console registry: finance never imports
    payroll. Empty while payroll is off or can't say."""
    if not company.has_feature("payroll"):
        return []
    from apps.console import registry

    provider = registry.COMPANY_FACTS.get("payroll")
    reader = _company_reader(company)
    if provider is None or reader is None:
        return []
    try:
        facts = provider.facts(company, None, reader) or {}
        if not facts.get("next_run_on") or not facts.get("next_run_amount"):
            return []
        day = date.fromisoformat(facts["next_run_on"])
        amount = quantize(Decimal(facts["next_run_amount"]))
    except Exception:  # payroll's trouble never breaks the owner's money page
        logger.exception("Payroll facts failed for company %s", company.pk)
        return []
    if amount <= 0 or day < today:
        return []
    found = []
    for step in range(months):
        found.append((_add_months(day, step), amount))
    return found


def _company_reader(company) -> Membership | None:
    """An owner of the company, to read company-wide facts as (every branch, every right)."""
    return (
        Membership.objects.select_related("role", "company")
        .filter(company=company, status=Membership.Status.APPROVED, role__is_owner=True)
        .order_by("pk")
        .first()
    )


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = index // 12, index % 12 + 1
    following = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, min(day.day, (following - timedelta(days=1)).day))


# The cash buffer and fixed costs ------------------------------------------------------------------


def cash_buffer(company, on: date | None = None) -> dict:
    """What always stays in the business: the setting, or one month of fixed costs."""
    monthly = fixed_costs(company, on)
    chosen = conf.get_settings(company).cash_buffer
    if chosen is not None:
        return {"amount": quantize(chosen), "auto": False, "fixed_costs": monthly}
    return {"amount": monthly, "auto": True, "fixed_costs": monthly}


def fixed_costs(company, on: date | None = None) -> Decimal:
    """One month (30 days) of the expenses that don't follow sales (see the docstring)."""
    today = on or queries.local_today(company)
    start = today - timedelta(days=FIXED_DAYS)
    rows = queries.posted_rows(company, branch_ids=None)
    first = rows.aggregate(first=Min("occurred_on"))["first"]
    if first is None or first >= today:
        return ZERO
    observed = (today - max(start, first)).days
    variable = Category.objects.for_company(company).filter(
        Q(system_code__in=VARIABLE_CODES) | Q(parent__system_code__in=VARIABLE_CODES)
    )
    spent = (
        rows.filter(
            kind=Transaction.Kind.EXPENSE,
            capitalized=False,
            occurred_on__gte=start,
            occurred_on__lt=today,
        )
        .exclude(category__in=variable)
        .aggregate(total=Sum("base_amount"))["total"]
    )
    if not spent or observed <= 0:
        return ZERO
    return max(quantize(-spent / observed * MONTH_DAYS), ZERO)


# Planned purchases -------------------------------------------------------------------------------


def planned_purchases(company, today: date, until: date) -> dict:
    """Open planned purchases: `kept` (due by `until`, or without a date) and `later`."""
    rows = list(
        PlannedPurchase.objects.for_company(company)
        .filter(done_at__isnull=True)
        .select_related("branch")
    )
    kept = [row for row in rows if row.due_on is None or row.due_on <= until]
    later = [row for row in rows if row.due_on is not None and row.due_on > until]
    return {"kept": kept, "later": later}


@transaction.atomic
def plan_purchase(
    company, *, by: Membership, title: str, amount, due_on: date | None = None, branch=None
) -> PlannedPurchase:
    services._need_actor(by)
    user = services._actor(company, by)
    services._same_company(company, branch)
    title = _title(title)
    row = PlannedPurchase.objects.create(
        company=company,
        title=title,
        amount=services._money(amount),
        due_on=due_on,
        branch=branch,
        created_by=user,
    )
    services._audit(
        FinanceAction.PURCHASE_PLANNED,
        company,
        user,
        row,
        title=row.title,
        amount=str(row.amount),
        due_on=due_on.isoformat() if due_on else None,
    )
    return row


@transaction.atomic
def update_purchase(row: PlannedPurchase, *, by: Membership, **fields) -> PlannedPurchase:
    """Change the title, amount, day or branch, or mark it bought or dropped (`done`)."""
    services._need_actor(by)
    row = PlannedPurchase.objects.select_for_update().get(pk=row.pk)
    company = row.company
    user = services._actor(company, by)
    unknown = set(fields) - {"title", "amount", "due_on", "branch", "done"}
    if unknown:
        raise ValueError(f"Unknown fields {sorted(unknown)}.")
    before = _purchase_snapshot(row)
    if "title" in fields:
        row.title = _title(fields["title"])
    if "amount" in fields:
        row.amount = services._money(fields["amount"])
    if "due_on" in fields:
        row.due_on = fields["due_on"]
    if "branch" in fields:
        services._same_company(company, fields["branch"])
        row.branch = fields["branch"]
    if "done" in fields:
        row.done_at = (row.done_at or timezone.now()) if fields["done"] else None
    row.save()
    changes = services._diff(before, _purchase_snapshot(row))
    if changes:
        services._audit(FinanceAction.PURCHASE_UPDATED, company, user, row, changes=changes)
    return row


@transaction.atomic
def remove_purchase(row: PlannedPurchase, *, by: Membership) -> None:
    services._need_actor(by)
    company = row.company
    user = services._actor(company, by)
    services._audit(
        FinanceAction.PURCHASE_REMOVED, company, user, row, title=row.title, amount=str(row.amount)
    )
    row.delete()


def _title(value) -> str:
    title = (value or "").strip()[:200]
    if not title:
        raise DomainError(_("Say what you plan to buy."))
    return title


def _purchase_snapshot(row: PlannedPurchase) -> dict:
    return {
        "title": row.title,
        "amount": str(row.amount),
        "due_on": row.due_on.isoformat() if row.due_on else None,
        "branch": row.branch_id,
        "done": row.done_at is not None,
    }


# Settings ----------------------------------------------------------------------------------------


@transaction.atomic
def update_settings(company, *, by: Membership, **fields) -> FinanceSettings:
    """The cash buffer (an amount, or None for one month of fixed costs) and the horizon."""
    services._need_actor(by)
    user = services._actor(company, by)
    unknown = set(fields) - {"cash_buffer", "draw_horizon_days"}
    if unknown:
        raise ValueError(f"Unknown fields {sorted(unknown)}.")
    row = FinanceSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    before = {"cash_buffer": row.cash_buffer, "draw_horizon_days": row.draw_horizon_days}
    if "cash_buffer" in fields:
        value = fields["cash_buffer"]
        row.cash_buffer = (
            services._money(value, allow_zero=True) if value not in (None, "") else None
        )
    if "draw_horizon_days" in fields:
        days = fields["draw_horizon_days"]
        if isinstance(days, bool) or not isinstance(days, int):
            raise DomainError(_("Give a number of days."))
        if not MIN_HORIZON <= days <= MAX_HORIZON:
            raise DomainError(
                _("From %(min)s to %(max)s days.") % {"min": MIN_HORIZON, "max": MAX_HORIZON}
            )
        row.draw_horizon_days = days
    row.save(update_fields=["cash_buffer", "draw_horizon_days"])
    after = {"cash_buffer": row.cash_buffer, "draw_horizon_days": row.draw_horizon_days}
    changes = {
        key: [_text(before[key]), _text(after[key])] for key in after if before[key] != after[key]
    }
    if changes:
        services._audit(FinanceAction.SETTINGS_UPDATED, company, user, row, changes=changes)
    return row


def _text(value) -> str | None:
    return str(value) if value is not None else None


# Taking money out and putting it in ---------------------------------------------------------------


def draw_accounts(member: Membership):
    """The business accounts `member` may take money from or put it into."""
    from apps.finance import access

    return (
        access.recordable_accounts(member)
        .filter(kind__in=DRAW_KINDS)
        .select_related("branch")
        .order_by("order", "name")
    )


def take(
    company,
    *,
    by: Membership,
    account: MoneyAccount,
    amount,
    occurred_on: date,
    description: str = "",
    confirmed: bool = False,
) -> Transaction:
    """The owner takes money out of the business: an owner draw on a business account. Above
    what is safe to take, it needs `confirmed` (the dashboard asks first)."""
    value = services._money(amount)
    _check_draw_account(company, account)
    if not confirmed:
        safe = safe_amount(company)["safe"]
        if value > safe:
            raise OverSafe(
                _("That is more than is safe to take out today (%(safe)s). Confirm to take it.")
                % {"safe": services._format(safe, company.base_currency)},
                safe,
            )
    return services.record_transaction(
        company,
        by=by,
        kind=Transaction.Kind.OWNER,
        amount=-value,
        occurred_on=occurred_on,
        account=account,
        description=(description or "").strip()[:300] or _("Taken by the owner"),
    )


def put(
    company,
    *,
    by: Membership,
    account: MoneyAccount,
    amount,
    occurred_on: date,
    description: str = "",
) -> Transaction:
    """The owner puts their own money into the business: an owner contribution."""
    value = services._money(amount)
    _check_draw_account(company, account)
    return services.record_transaction(
        company,
        by=by,
        kind=Transaction.Kind.OWNER,
        amount=value,
        occurred_on=occurred_on,
        account=account,
        description=(description or "").strip()[:300] or _("Put in by the owner"),
    )


def _check_draw_account(company, account: MoneyAccount) -> None:
    services._same_company(company, account)
    if account.kind not in DRAW_KINDS:
        raise DomainError(
            _("Take money from or put it into a cash desk, safe, bank account, card or wallet.")
        )


# Draws and contributions -------------------------------------------------------------------------


def owner_rows(company, start: date, end: date):
    """Posted owner draws and contributions on business accounts from `start` to `end`."""
    return (
        Transaction.objects.for_company(company)
        .filter(
            kind=Transaction.Kind.OWNER,
            status=Transaction.Status.POSTED,
            occurred_on__range=(start, end),
            account__isnull=False,
        )
        .exclude(account__kind__in=PERSONAL_KINDS)
    )


def owner_flows(company, start: date, end: date, *, limit: int = 50) -> dict:
    """What the owners took out and put in from `start` to `end` (both included): totals in the
    base currency and the rows, newest first (dividends paid show as draws too)."""
    rows = owner_rows(company, start, end)
    sums = rows.aggregate(
        out=Sum("base_amount", filter=Q(base_amount__lt=0)),
        put=Sum("base_amount", filter=Q(base_amount__gt=0)),
    )
    drawn = quantize(-(sums["out"] or ZERO))
    put_in = quantize(sums["put"] or ZERO)
    listed = rows.select_related("account", "membership", "created_by").order_by(
        "-occurred_on", "-pk"
    )
    return {
        "from": start,
        "to": end,
        "drawn": drawn,
        "put_in": put_in,
        "net": quantize(put_in - drawn),
        "count": rows.count(),
        "rows": [_flow_row(row) for row in listed[:limit]],
    }


def _flow_row(row: Transaction) -> dict:
    who = row.membership
    return {
        "id": row.pk,
        "occurred_on": row.occurred_on,
        "direction": "in" if row.amount > 0 else "out",
        "amount": quantize(abs(row.amount)),
        "currency": row.currency,
        "base_amount": quantize(abs(row.base_amount)),
        "account": {"id": row.account_id, "name": row.account.name, "kind": row.account.kind},
        "description": row.description,
        "person": str(who) if who is not None else None,
        "dividend": row.source_type == "finance.dividend",
        "created_by": row.created_by.get_full_name() if row.created_by_id else None,
    }


def history(company, months: int = 6, on: date | None = None) -> list[dict]:
    """Net profit (the P&L's), what was drawn and what was put in, per month for the last
    `months` months (this one so far included), oldest first."""
    today = on or queries.local_today(company)
    first = today.replace(day=1)
    found = []
    for back in range(months - 1, -1, -1):
        start = _add_months(first, -back)
        end = min(_add_months(start, 1) - timedelta(days=1), today)
        flows = owner_rows(company, start, end).aggregate(
            out=Sum("base_amount", filter=Q(base_amount__lt=0)),
            put=Sum("base_amount", filter=Q(base_amount__gt=0)),
        )
        profit = queries.totals(company, start, end, branch_ids=None)["profit"]
        found.append(
            {
                "month": start,
                "profit": quantize(profit),
                "drawn": quantize(-(flows["out"] or ZERO)),
                "put_in": quantize(flows["put"] or ZERO),
            }
        )
    return found


# The suggestion ----------------------------------------------------------------------------------


def suggested_monthly(company, on: date | None = None) -> dict:
    """The largest monthly draw, taken on the first day of each coming month, that keeps the
    90-day forecast (without the owner's own money) at or above the cash buffer every day.

    `monthly` is rounded down to a round figure and is zero when the forecast already goes
    below the buffer before the first draw (`below_buffer_on`)."""
    today = on or queries.local_today(company)
    forecast = planning.forecast(company, SUGGEST_DAYS, branch_ids=None, today=today)
    position = queries.cash_position(company, today, branch_ids=None)
    personal = sum(
        (
            account["base"]
            for account in position["accounts"]
            if account["kind"] in PERSONAL_KINDS and account["base"] is not None
        ),
        ZERO,
    )
    buffer = cash_buffer(company, today)["amount"]
    first = _add_months(today.replace(day=1), 1)
    dates = [_add_months(first, step) for step in range(SUGGEST_MONTHS)]
    dates = [day for day in dates if day <= today + timedelta(days=SUGGEST_DAYS)]
    best: Decimal | None = None
    below_on = None
    payroll = _unbooked_payroll(company, today, today + timedelta(days=SUGGEST_DAYS))
    points = []
    for point in forecast["points"]:
        day = date.fromisoformat(point["date"])
        later_pay = sum((amount for pay_day, amount in payroll if pay_day <= day), ZERO)
        points.append((day, Decimal(point["balance"]) - personal - later_pay))
    for day, balance in points:
        taken = sum(1 for draw_day in dates if draw_day <= day)
        room = balance - buffer
        if taken == 0:
            if room < 0 and below_on is None:
                below_on = day
            continue
        candidate = room / taken
        best = candidate if best is None else min(best, candidate)
    monthly = ZERO
    if below_on is None and best is not None and best > 0:
        monthly = round_down(best, company.base_currency)
    low_day, low_balance = None, None
    for day, balance in points:
        after = balance - monthly * sum(1 for draw_day in dates if draw_day <= day)
        if low_balance is None or after < low_balance:
            low_day, low_balance = day, after
    months = history(company, PROFIT_MONTHS + 1, today)[:-1]
    profit_average = quantize(
        sum((row["profit"] for row in months), ZERO) / Decimal(max(len(months), 1))
    )
    return {
        "today": today,
        "currency": company.base_currency,
        "days": SUGGEST_DAYS,
        "monthly": monthly,
        "dates": dates,
        "buffer": quantize(buffer),
        "low": {"date": low_day, "balance": quantize(low_balance or ZERO)},
        "below_buffer_on": below_on,
        # Taking more than the business earns comes out of its capital, whatever the cash says.
        "profit_average": profit_average,
        "above_profit": monthly > max(profit_average, ZERO),
        "basis": forecast["basis"],
    }


def _unbooked_payroll(company, today: date, until: date) -> list[tuple[date, Decimal]]:
    """The pay days the forecast can't see yet (their runs aren't booked): payroll's figure on
    each, without the run whose pay is already owed (that one the forecast has)."""
    pay_days = [(day, amount) for day, amount in payroll_estimates(company, today) if day <= until]
    if not pay_days:
        return []
    booked = sum(
        (
            item.amount
            for item in planning.items(company, today, until, branch_ids=None)
            if item.kind == "payroll" and item.amount is not None
        ),
        ZERO,
    )
    if booked and booked >= pay_days[0][1]:
        pay_days = pay_days[1:]
    return pay_days


def round_down(amount: Decimal, currency: str) -> Decimal:
    """Down to a round figure: 100 000 so‘m (10 000 below a million), 10 dollars (1 below 1 000)."""
    if currency == "UZS":
        step = Decimal(100000) if amount >= 1_000_000 else Decimal(10000)
    else:
        step = Decimal(10) if amount >= 1000 else Decimal(1)
    steps = (amount / step).to_integral_value(rounding=ROUND_FLOOR)
    return quantize(max(steps * step, ZERO))
