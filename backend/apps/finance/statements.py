"""Financial statements for a bank, a partner or a buyer (v12): the balance sheet on a day and
what the business is worth. Read functions only; the statement pack (`statement_pack.py`) and
the owner endpoints build on them.

The balance sheet, in the base currency (foreign money at the company's rate of that day):

    Assets       cash on hand, bank and cards, card money on its way; what customers, staff
                 and others owe us; stock at cost (stock module on); fixed assets at net book
                 value (assets module on)
    Liabilities  suppliers, loans (the part due within a year, and later), taxes, what we owe
                 our people, dividends declared and not paid yet, other payables
    Equity       owner money put in less taken out, and the rest as retained earnings, so the
                 two sides balance

The owner's own money (`MoneyAccount.Kind.OWNER`, the personal side) is not the business's:
money moved from it into the business, and what it paid for the business, counts as put in;
money moved to it counts as taken out.

The ledger books medicines as a cost when they arrive, keeps no stock and leaves fixed assets
bought before the books out of the cash. So retained earnings differ from the profit recorded
since the books started; `reconciliation` shows exactly how (stock at cost, opening balances,
older fixed assets, currency revaluation, dividends declared), and anything left over is named
as a gap instead of being hidden. `gaps` lists, plainly, what the books leave out.

With a branch scope only the branches' cash, debts, stock and fixed assets are counted, and the
equity is their net assets (owner money and profit belong to the company as a whole).

What the business is worth (`worth`): two transparent methods and a range, never one number.
Earnings: the last twelve months' profit before depreciation, loan interest and equipment
booked as a cost, times a multiple range the owner may change. Net assets: the balance sheet's
equity (book value). An estimate, not an appraisal.

Money comes back as Decimal; lines carry keys, the callers name them.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max, Min, Q, Sum

from apps.core.money import quantize
from apps.finance import conf, queries
from apps.finance.models import (
    SETTLES_DEBT,
    Category,
    Debt,
    DebtInstallment,
    Dividend,
    DividendLine,
    MoneyAccount,
    Transaction,
)

ZERO = Decimal(0)
Kind = Transaction.Kind
Status = Transaction.Status
AccountKind = MoneyAccount.Kind

# Account kinds by balance sheet line. The owner's own money is not the business's.
CASH_LINES = (
    ("cash_on_hand", (AccountKind.CASH, AccountKind.SAFE, AccountKind.EMPLOYEE)),
    ("bank", (AccountKind.BANK, AccountKind.CARD, AccountKind.WALLET)),
    ("in_transit", (AccountKind.CLEARING,)),
)
PERSONAL = (AccountKind.OWNER,)
# Debts due within this many days of the balance sheet's day are current.
CURRENT_DAYS = 365
STAFF_PAYABLE_KINDS = (Debt.Kind.SALARY, Debt.Kind.REIMBURSEMENT, Debt.Kind.ADVANCE)
SUPPLIER_KINDS = (Debt.Kind.TRADE, Debt.Kind.BILL)
# Categories the fixed assets module books depreciation and write-offs into.
DEPRECIATION_CODES = ("depreciation", "asset_disposal")

# What the business is worth: the default multiple range of a year's earnings (the hand-off
# cites where it comes from), and how much history the earnings method needs.
DEFAULT_MULTIPLE_LOW = Decimal("2.0")
DEFAULT_MULTIPLE_HIGH = Decimal("3.0")
MIN_EARNINGS_DAYS = 60
YEAR_DAYS = 365


# Helpers --------------------------------------------------------------------------------------


def _sum(rows, field: str = "base_amount") -> Decimal:
    return quantize(rows.aggregate(total=Sum(field))["total"] or ZERO)


def _business_rows(company, on: date):
    """Posted rows on the business's own accounts up to `on` (company-wide)."""
    return Transaction.objects.filter(
        company=company, status=Status.POSTED, account__isnull=False, occurred_on__lte=on
    ).exclude(account__kind__in=PERSONAL)


def books_start(company) -> date | None:
    """The first day the books here carry real business: the first opening balance, income or
    expense (depreciation the fixed assets module back-books for older equipment doesn't
    count)."""
    return Transaction.objects.filter(
        company=company,
        status=Status.POSTED,
        kind__in=(Kind.OPENING, Kind.INCOME, Kind.EXPENSE, Kind.OWNER, Kind.DEBT_OPEN),
    ).aggregate(first=Min("occurred_on"))["first"]


def _settled_by(company, on: date) -> dict[int, Decimal]:
    """{debt id: what payments, write-offs and credit notes took off it up to `on`}, in the
    debt's currency."""
    settled: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for entry in (
        Transaction.objects.filter(
            SETTLES_DEBT, company=company, status=Status.POSTED, occurred_on__lte=on
        )
        .values("debt_id")
        .annotate(total=Sum("debt_amount"))
        .order_by()
    ):
        settled[entry["debt_id"]] = entry["total"] or ZERO
    return settled


def _debts_on(company, on: date, *, branch_ids) -> list[tuple[Debt, Decimal]]:
    """[(debt, what was still owed at the end of `on`, in its currency)] of the debts in scope
    open on that day."""
    settled = _settled_by(company, on)
    found = []
    for debt in (
        queries.scoped_debts(company, branch_ids=branch_ids)
        .exclude(status=Debt.Status.CANCELLED)
        .filter(issued_on__lte=on)
        .select_related("company", "counterparty", "membership")
        .order_by("issued_on", "pk")
    ):
        left = quantize(debt.amount - settled[debt.pk])
        if left > 0:
            found.append((debt, left))
    return found


def _loan_split(debt: Debt, left: Decimal, on: date) -> tuple[Decimal, Decimal]:
    """(due within a year of `on`, due later) of what is left on a loan, in its currency: by its
    instalment plan when it has one (the payments so far cover the earliest instalments), else
    by its due day."""
    horizon = on + timedelta(days=CURRENT_DAYS)
    plan = list(DebtInstallment.objects.filter(debt=debt).order_by("due_on", "position", "pk"))
    if not plan:
        if debt.due_on is not None and debt.due_on > horizon:
            return ZERO, left
        return left, ZERO
    covered = debt.amount - left
    current = later = ZERO
    for installment in plan:
        paid = min(covered, installment.amount)
        covered -= paid
        rest = installment.amount - paid
        if installment.due_on <= horizon:
            current += rest
        else:
            later += rest
    unplanned = left - current - later
    if unplanned > 0:  # the plan covers less than the loan: the rest is due with the loan
        if debt.due_on is not None and debt.due_on > horizon:
            later += unplanned
        else:
            current += unplanned
    return quantize(min(current, left)), quantize(max(left - min(current, left), ZERO))


def _line(key: str, amount: Decimal, **extra) -> dict:
    return {"key": key, "amount": quantize(amount), **extra}


def _section(key: str, lines: list[dict], *, keep_empty: bool = False) -> dict:
    kept = [line for line in lines if keep_empty or line["amount"]]
    return {"key": key, "lines": kept, "total": quantize(sum((li["amount"] for li in kept), ZERO))}


# The balance sheet ------------------------------------------------------------------------------


def balance_sheet(company, on: date, *, branch_ids, today: date | None = None) -> dict:
    """The balance sheet at the end of `on` (see the module docstring), for `branch_ids` (None:
    the whole company)."""
    today = today or queries.local_today(company)
    on = min(on, today)
    whole = branch_ids is None
    gaps: list[dict] = []

    # Cash: every account in scope but the owner's own, at that day's rate.
    position = queries.cash_position(company, on, branch_ids=branch_ids, today=today)
    business = [row for row in position["accounts"] if row["kind"] not in PERSONAL]
    cash_lines = []
    for key, kinds in CASH_LINES:
        rows = [row for row in business if row["kind"] in kinds]
        if rows:
            amount = sum((row["base"] or ZERO for row in rows), ZERO)
            cash_lines.append(_line(key, amount, count=len(rows)))
    unrated = [row for row in business if row["base"] is None and row["balance"]]
    if unrated:
        gaps.append(
            {"key": "no_rate", "params": {"currencies": sorted({r["currency"] for r in unrated})}}
        )
    below_zero = [row for row in business if (row["base"] or ZERO) < 0]
    for row in below_zero:
        gaps.append({"key": "negative_account", "params": {"account": row["name"]}})
    foreign = _foreign(company, business, position)

    # Debts on that day, at the rate each was opened at.
    receivable = defaultdict(lambda: ZERO)
    payable = defaultdict(lambda: ZERO)
    counts = defaultdict(int)
    loans_current = loans_later = ZERO
    for debt, left in _debts_on(company, on, branch_ids=branch_ids):
        value = queries.book_value(debt, left)
        if debt.direction == Debt.Direction.RECEIVABLE:
            if debt.membership_id is not None:
                key = "staff_owe_us"
            elif debt.kind == Debt.Kind.LOAN:
                key = "loans_given"
            elif debt.kind in (*SUPPLIER_KINDS, Debt.Kind.OTHER):
                key = "customers"
            else:
                key = "other_receivable"
            receivable[key] += value
            counts[key] += 1
            continue
        if debt.kind == Debt.Kind.LOAN:
            soon, _later = _loan_split(debt, left, on)
            soon_value = queries.book_value(debt, soon)
            loans_current += soon_value
            loans_later += value - soon_value
            counts["loans"] += 1
            continue
        if debt.membership_id is not None or debt.kind in STAFF_PAYABLE_KINDS:
            key = "staff"
        elif debt.kind in SUPPLIER_KINDS:
            key = "suppliers"
        elif debt.kind == Debt.Kind.TAX:
            key = "taxes"
        else:
            key = "other_payable"
        payable[key] += value
        counts[key] += 1

    assets = [
        _section("cash", cash_lines, keep_empty=not cash_lines),
        _section(
            "receivables",
            [
                _line(key, receivable[key], count=counts[key])
                for key in ("customers", "staff_owe_us", "loans_given", "other_receivable")
            ],
        ),
    ]
    stock = _stock(company, on, branch_ids=branch_ids, today=today, gaps=gaps)
    if stock is not None:
        assets.append(_section("stock", [_line("stock_at_cost", stock)], keep_empty=True))
    fixed = _fixed_assets(company, on, branch_ids=branch_ids, gaps=gaps)
    if fixed is not None:
        assets.append(
            _section(
                "fixed_assets",
                [_line("fixed_assets_book", fixed["book"], cost=fixed["cost"])],
                keep_empty=True,
            )
        )
    assets = [section for section in assets if section["lines"] or section["key"] == "cash"]
    assets_total = quantize(sum((section["total"] for section in assets), ZERO))

    dividends = _dividends_due(company, on) if whole else ZERO
    current = _section(
        "current",
        [
            _line("suppliers", payable["suppliers"], count=counts["suppliers"]),
            _line("loans_current", loans_current, count=counts["loans"]),
            _line("taxes", payable["taxes"], count=counts["taxes"]),
            _line("staff", payable["staff"], count=counts["staff"]),
            _line("dividends", dividends),
            _line("other_payable", payable["other_payable"], count=counts["other_payable"]),
        ],
    )
    long_term = _section("long_term", [_line("loans_long", loans_later, count=counts["loans"])])
    liabilities = [section for section in (current, long_term) if section["lines"]]
    liabilities_total = quantize(current["total"] + long_term["total"])

    net_assets = quantize(assets_total - liabilities_total)
    reconciliation = None
    if whole:
        owner = _owner_money(company, on)
        retained = quantize(net_assets - owner["net"])
        equity_lines = [
            _line("owner_put_in", owner["put_in"]),
            _line("owner_taken_out", -owner["taken_out"]),
            _line("retained", retained),
        ]
        reconciliation = _reconcile(
            company,
            on,
            retained=retained,
            stock=stock or ZERO,
            fixed=fixed,
            revaluation=sum((row["base"] or ZERO for row in business), ZERO)
            - _business_booked(company, on),
            dividends=dividends,
        )
        if abs(reconciliation["unexplained"]) >= 1:
            gaps.append({"key": "unexplained", "params": {"amount": reconciliation["unexplained"]}})
    else:
        equity_lines = [_line("net_assets", net_assets)]
    equity = {"lines": equity_lines, "total": net_assets}

    start = books_start(company)
    if start is None:
        gaps.append({"key": "no_books", "params": {}})
    elif (
        whole
        and not Transaction.objects.filter(
            company=company, status=Status.POSTED, kind=Kind.OPENING
        ).exists()
    ):
        gaps.append({"key": "no_opening", "params": {"day": start}})
    pending = Transaction.objects.filter(
        company=company, status=Status.PENDING, occurred_on__lte=on
    )
    if branch_ids is not None:
        pending = pending.filter(branch_id__in=branch_ids)
    if pending.exists():
        gaps.append(
            {
                "key": "pending",
                "params": {"count": pending.count(), "amount": -_sum(pending)},
            }
        )
    return {
        "on": on,
        "currency": company.base_currency,
        "whole_company": whole,
        "books_start": start,
        "assets": {"sections": assets, "total": assets_total},
        "liabilities": {"sections": liabilities, "total": liabilities_total},
        "equity": equity,
        "check": {
            "assets": assets_total,
            "liabilities_and_equity": quantize(liabilities_total + net_assets),
            "balanced": assets_total == quantize(liabilities_total + net_assets),
        },
        "current_assets": quantize(
            sum(
                (s["total"] for s in assets if s["key"] in ("cash", "receivables", "stock")),
                ZERO,
            )
        ),
        "current_liabilities": current["total"],
        "accounts": business,
        "foreign": foreign,
        "rate": position["rate"],
        "complete": position["complete"],
        "reconciliation": reconciliation,
        "gaps": gaps,
    }


def _foreign(company, business: list[dict], position: dict) -> list[dict]:
    """The foreign money held, in its own currency and what it is worth in the base one."""
    held: dict[str, dict] = {}
    for row in business:
        if row["currency"] == company.base_currency or not row["balance"]:
            continue
        entry = held.setdefault(row["currency"], {"amount": ZERO, "base": ZERO, "rated": True})
        entry["amount"] += row["balance"]
        if row["base"] is None:
            entry["rated"] = False
        else:
            entry["base"] += row["base"]
    rate = position["rate"]
    return [
        {
            "currency": currency,
            "amount": quantize(entry["amount"]),
            "base": quantize(entry["base"]) if entry["rated"] else None,
            "rate": rate["rate"],
            "rate_date": rate["date"],
            "stale": rate["stale"],
        }
        for currency, entry in sorted(held.items())
    ]


def _business_booked(company, on: date) -> Decimal:
    """The base value the business's accounts' rows were booked at, up to `on`."""
    return _sum(_business_rows(company, on))


def _stock(company, on: date, *, branch_ids, today: date, gaps: list) -> Decimal | None:
    """Stock at cost on `on`, or None while the stock module is off (named as a gap)."""
    if not company.has_feature("stock"):
        gaps.append({"key": "no_stock_module", "params": {}})
        return None
    from apps.inventory import queries as stock_queries

    value = stock_queries.stock_value_on(company, on, branch_ids=branch_ids)
    if value < 0:
        gaps.append({"key": "stock_history", "params": {}})
        return ZERO
    return value


def _fixed_assets(company, on: date, *, branch_ids, gaps: list) -> dict | None:
    """{"cost", "depreciation", "book"} of the fixed assets owned on `on`, or None while the
    assets module is off (named as a gap, with equipment the ledger booked as a cost)."""
    if not company.has_feature("assets"):
        spent = -_sum(
            Transaction.objects.filter(
                company=company,
                status=Status.POSTED,
                kind=Kind.EXPENSE,
                category__is_capex=True,
                capitalized=False,
                occurred_on__lte=on,
            )
        )
        gaps.append({"key": "no_assets_module", "params": {"equipment": spent}})
        return None
    from apps.assets import queries as asset_queries

    total = asset_queries.movement(company, branch_ids=branch_ids, start=on, end=on)["total"]
    return {
        "cost": total["close_cost"],
        "depreciation": total["close_depreciation"],
        "book": total["close_book"],
    }


def _dividends_due(company, on: date) -> Decimal:
    """Dividends declared by the end of `on` and not paid by then."""
    due = ZERO
    zone_end = datetime.combine(on + timedelta(days=1), time.min, tzinfo=_zone(company))
    lines = (
        DividendLine.objects.filter(dividend__company=company, dividend__created_at__lt=zone_end)
        .exclude(dividend__status=Dividend.Status.CANCELLED)
        .select_related("transaction")
    )
    for line in lines:
        paid = line.is_paid and line.paid_on is not None and line.paid_on <= on
        if not paid:
            due += line.amount
    return quantize(due)


def _zone(company):
    from zoneinfo import ZoneInfo

    return ZoneInfo(company.timezone)


def _owner_money(company, on: date) -> dict:
    """What the owner put into the business and took out of it up to `on`: owner rows on the
    business's accounts, and everything the owner's own money did for or with the business."""
    owner_rows = _business_rows(company, on).filter(kind=Kind.OWNER)
    personal = Transaction.objects.filter(
        company=company,
        status=Status.POSTED,
        occurred_on__lte=on,
        account__kind__in=PERSONAL,
    ).exclude(kind__in=(Kind.OWNER, Kind.OPENING))
    put_in = _sum(owner_rows.filter(base_amount__gt=0)) - _sum(personal.filter(base_amount__lt=0))
    taken_out = -_sum(owner_rows.filter(base_amount__lt=0)) + _sum(
        personal.filter(base_amount__gt=0)
    )
    return {"put_in": put_in, "taken_out": taken_out, "net": quantize(put_in - taken_out)}


def _reconcile(
    company,
    on: date,
    *,
    retained: Decimal,
    stock: Decimal,
    fixed: dict | None,
    revaluation: Decimal,
    dividends: Decimal,
) -> dict:
    """How retained earnings are made, line by line, from what the books recorded."""
    profit = queries.totals(company, date(1900, 1, 1), on, branch_ids=None)["profit"]
    opening_cash = _sum(_business_rows(company, on).filter(kind=Kind.OPENING))
    opening_debts = ZERO
    for debt in Debt.objects.filter(company=company, is_opening=True, issued_on__lte=on).exclude(
        status=Debt.Status.CANCELLED
    ):
        value = queries.book_value(debt, debt.amount)
        opening_debts += value if debt.direction == Debt.Direction.RECEIVABLE else -value
    older_assets = ZERO
    if fixed is not None:
        # Fixed assets the ledger paid for are cash out (capitalized rows) and come back as book
        # value less the depreciation booked: whatever is left was owned before the books.
        capitalized = _sum(
            Transaction.objects.filter(
                company=company, status=Status.POSTED, capitalized=True, occurred_on__lte=on
            )
        )
        depreciation = _sum(
            Transaction.objects.filter(
                company=company, status=Status.POSTED, kind=Kind.NON_CASH, occurred_on__lte=on
            )
        )
        older_assets = quantize(fixed["book"] + capitalized - depreciation)
    lines = [
        _line("profit_recorded", profit),
        _line("opening_balances", quantize(opening_cash + opening_debts)),
        _line("stock_at_cost", stock),
        _line("older_fixed_assets", older_assets),
        _line("revaluation", quantize(revaluation)),
        _line("dividends_declared", -dividends),
    ]
    explained = quantize(sum((line["amount"] for line in lines), ZERO))
    return {
        "lines": [line for line in lines if line["amount"] or line["key"] == "profit_recorded"],
        "retained": retained,
        "unexplained": quantize(retained - explained),
    }


# What the business is worth --------------------------------------------------------------------


def multiples(company) -> tuple[Decimal, Decimal]:
    """The owner's multiple range of a year's earnings, or the conservative default."""
    row = conf.get_settings(company)
    low = row.valuation_multiple_low or DEFAULT_MULTIPLE_LOW
    high = row.valuation_multiple_high or DEFAULT_MULTIPLE_HIGH
    return (min(low, high), max(low, high))


def earnings(company, on: date) -> dict:
    """The last twelve months' profit before depreciation, loan interest and equipment booked as
    a cost (the whole company), and how it is made. With less than a year of books it is scaled
    up to a year from what there is; with less than `MIN_EARNINGS_DAYS` it is not given."""
    start = books_start(company)
    first = on - timedelta(days=YEAR_DAYS - 1)
    if start is not None and start > first:
        first = start
    days = (on - first).days + 1 if start is not None and first <= on else 0
    result = {"from": first, "to": on, "days": max(days, 0), "enough": days >= MIN_EARNINGS_DAYS}
    if days <= 0:
        return {**result, "profit": ZERO, "lines": [], "earnings": ZERO, "yearly": None}
    rows = queries.posted_rows(company, branch_ids=None).filter(
        kind__in=queries.PNL_KINDS, occurred_on__range=(first, on)
    )
    profit = queries.totals(company, first, on, branch_ids=None)["profit"]
    depreciation = -_sum(rows.filter(capitalized=False, kind=Kind.NON_CASH))
    depreciation -= _sum(
        rows.filter(capitalized=False, category__system_code__in=DEPRECIATION_CODES).exclude(
            kind=Kind.NON_CASH
        )
    )
    interest = -_sum(
        rows.filter(
            capitalized=False,
            category__kind=Category.Kind.EXPENSE,
            debt__kind=Debt.Kind.LOAN,
            debt__direction=Debt.Direction.PAYABLE,
        ).exclude(kind__in=(Kind.FX, Kind.NON_CASH))
    )
    # Equipment bought and booked as a cost (an equipment category, not made a fixed asset) is
    # an investment, not a running cost.
    equipment = -_sum(rows.filter(capitalized=False, kind=Kind.EXPENSE, category__is_capex=True))
    lines = [
        _line("profit", profit),
        _line("depreciation", depreciation),
        _line("interest", interest),
        _line("equipment", equipment),
    ]
    total = quantize(profit + depreciation + interest + equipment)
    yearly = None
    if days >= MIN_EARNINGS_DAYS:
        yearly = total if days >= YEAR_DAYS else quantize(total * YEAR_DAYS / days)
    return {**result, "profit": profit, "lines": lines, "earnings": total, "yearly": yearly}


def worth(company, on: date, *, sheet: dict | None = None, low=None, high=None) -> dict:
    """What the business is worth on `on` (the whole company): the earnings method's range, the
    net assets, and the range they span together."""
    default_low, default_high = multiples(company)
    low = Decimal(low) if low is not None else default_low
    high = Decimal(high) if high is not None else default_high
    low, high = min(low, high), max(low, high)
    sheet = sheet or balance_sheet(company, on, branch_ids=None)
    made = earnings(company, sheet["on"])
    net_assets = sheet["equity"]["total"]
    # A multiple of earnings values the business itself, without its money and its loans (a
    # buyer pays for the income): the owner's part adds the cash and takes off what is owed
    # on loans and to the partners.
    cash = _section_total(sheet, "cash") or ZERO
    debt = ZERO
    for section in sheet["liabilities"]["sections"]:
        for line in section["lines"]:
            if line["key"] in ("loans_current", "loans_long", "dividends"):
                debt += line["amount"]
    method = {
        "applies": False,
        "reason": None,
        "business_low": None,
        "business_high": None,
        "cash": quantize(cash),
        "debt": quantize(debt),
        "low": None,
        "high": None,
    }
    yearly = made["yearly"]
    if not made["enough"]:
        method["reason"] = "too_early"
    elif yearly is None or yearly <= 0:
        method["reason"] = "loss"
    else:
        business_low, business_high = quantize(yearly * low), quantize(yearly * high)
        method |= {
            "applies": True,
            "business_low": business_low,
            "business_high": business_high,
            "low": quantize(business_low + cash - debt),
            "high": quantize(business_high + cash - debt),
        }
    values = [net_assets]
    if method["applies"]:
        values += [method["low"], method["high"]]
    return {
        "on": sheet["on"],
        "currency": company.base_currency,
        "multiple_low": low,
        "multiple_high": high,
        "default_low": DEFAULT_MULTIPLE_LOW,
        "default_high": DEFAULT_MULTIPLE_HIGH,
        "earnings": made,
        "earnings_method": method,
        "net_assets": {
            "value": net_assets,
            "assets": sheet["assets"]["total"],
            "liabilities": sheet["liabilities"]["total"],
            "stock": _section_total(sheet, "stock"),
            "fixed_assets": _section_total(sheet, "fixed_assets"),
        },
        "range": {"low": quantize(min(values)), "high": quantize(max(values))},
    }


def _section_total(sheet: dict, key: str) -> Decimal | None:
    for section in sheet["assets"]["sections"]:
        if section["key"] == key:
            return section["total"]
    return None


def last_activity(company) -> date | None:
    """The last day anything was posted (the statement pack's "books up to")."""
    return Transaction.objects.filter(company=company, status=Status.POSTED).aggregate(
        last=Max("occurred_on")
    )["last"]


def has_rows(company, start: date, end: date, *, branch_ids) -> bool:
    """Whether any income or expense was posted between `start` and `end` (a period worth
    comparing with)."""
    return (
        queries.posted_rows(company, branch_ids=branch_ids)
        .filter(Q(kind=Kind.INCOME) | Q(kind=Kind.EXPENSE), occurred_on__range=(start, end))
        .exists()
    )
