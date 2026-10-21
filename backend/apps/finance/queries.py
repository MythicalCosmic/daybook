"""Read functions of the finance ledger, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`; None is
every branch and must be written out). Amounts come back as `Decimal`; reports add up
`base_amount`, the amount in the base currency frozen when each row was posted, and account
balances add up `amount` in the account's currency.

Contract for other packages (§11.3 Package D):

    totals(company, start, end, group_by, *, branch_ids)        income, expense, profit (+ series)
    transactions(company, filters, limit, *, branch_ids)        ledger rows matching filters
    cash_position(company, on, *, branch_ids)                   money on every account, in base too
    debts(company, direction, *, branch_ids, overdue_only=False) open debts with `outstanding`
    pnl(company, start, end, group, *, branch_ids)              category tree by period
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import (
    Case,
    CharField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    QuerySet,
    Sum,
    Value,
    When,
)
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.core.money import Currency, MoneyField, quantize
from apps.finance.models import (
    Category,
    Counterparty,
    Debt,
    DebtInstallment,
    MoneyAccount,
    Receipt,
    Transaction,
    Transfer,
)
from apps.finance.rates import convert, rate_for
from apps.members import scope

ZERO = Decimal(0)
Kind = Transaction.Kind
Status = Transaction.Status
PNL_KINDS = Transaction.PNL_KINDS
# Kinds of money account whose balance is cash on hand in a branch (branch facts).
CASH_KINDS = (MoneyAccount.Kind.CASH, MoneyAccount.Kind.SAFE, MoneyAccount.Kind.EMPLOYEE)
CASH_FLOW_SECTIONS = ("operating", "investing", "financing", "owner", "transfers", "opening")
# Sections that are real money in or out (transfers move money between our own accounts, and
# opening entries are what was there before the books started).
FLOW_SECTIONS = ("operating", "investing", "financing", "owner")
AGING_BUCKETS = ("current", "d1_30", "d31_60", "d61_90", "d90")


# The W0 contract ----------------------------------------------------------------------------


def balance(account: MoneyAccount, on: date | None = None) -> Decimal:
    """The account's balance: now (the cached balance, read fresh), or at the end of `on`
    (the sum of its posted rows up to that day)."""
    if on is None:
        return MoneyAccount.objects.filter(pk=account.pk).values_list("balance", flat=True).get()
    rows = Transaction.objects.filter(
        account_id=account.pk, status=Transaction.Status.POSTED, occurred_on__lte=on
    )
    return quantize(rows.aggregate(total=Sum("amount"))["total"] or 0)


def ledger_balance(account: MoneyAccount) -> Decimal:
    """The sum of every posted row on the account: the truth the cached balance must equal."""
    rows = Transaction.objects.filter(account_id=account.pk, status=Transaction.Status.POSTED)
    return quantize(rows.aggregate(total=Sum("amount"))["total"] or 0)


def open_debts(
    company,
    *,
    membership=None,
    counterparty=None,
    kind: str | None = None,
    direction: str | None = None,
) -> QuerySet[Debt]:
    """Debts still open, the soonest due first, each annotated with `outstanding`
    (`amount - paid`, in the debt's currency)."""
    debts = Debt.objects.for_company(company).filter(status=Debt.Status.OPEN)
    if membership is not None:
        debts = debts.filter(membership=membership)
    if counterparty is not None:
        debts = debts.filter(counterparty=counterparty)
    if kind is not None:
        debts = debts.filter(kind=kind)
    if direction is not None:
        debts = debts.filter(direction=direction)
    return _with_outstanding(debts).order_by(F("due_on").asc(nulls_last=True), "issued_on", "pk")


def has_ledger_rows(company) -> bool:
    """Whether anything was booked in the company's base currency (its base currency is then
    locked): any transaction, transfer or debt, void ones included."""
    return (
        Transaction.objects.filter(company=company).exists()
        or Transfer.objects.filter(company=company).exists()
        or Debt.objects.filter(company=company).exists()
    )


def local_today(company, now: datetime | None = None) -> date:
    """Today in the company's timezone."""
    return timezone.localtime(now or timezone.now(), ZoneInfo(company.timezone)).date()


# Valuation ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Valuation:
    """Converts amounts into the base currency at the rate of one day."""

    base: str
    rate: Decimal | None  # UZS per 1 USD; None when no rate exists at all
    stale: bool
    source: str
    day: date

    def to_base(self, amount: Decimal, currency: str) -> Decimal | None:
        if currency == self.base:
            return quantize(amount)
        if self.rate is None:
            return None
        return convert(amount, currency, self.base, self.rate)


def valuation(company, day: date) -> Valuation:
    """The rate the company uses for its foreign currency on `day` (stale when it's an older
    rate), for valuing money now. Never raises: without any rate, foreign money has no base
    value and `rate` is None."""
    base = company.base_currency
    foreign = Currency.USD if base != Currency.USD else Currency.UZS
    try:
        quote = rate_for(company, foreign, day)
    except DomainError:
        return Valuation(base, None, True, "none", day)
    return Valuation(base, quote.rate, quote.stale, quote.source, day)


def book_value(debt: Debt, amount: Decimal) -> Decimal:
    """An amount of `debt` in the base currency at the debt's frozen rate."""
    return convert(amount, debt.currency, debt.company.base_currency, debt.rate)


# Scoped querysets ----------------------------------------------------------------------------


def posted_rows(company, *, branch_ids) -> QuerySet[Transaction]:
    rows = Transaction.objects.for_company(company).filter(status=Status.POSTED)
    return scope.restrict(rows, branch_ids)


def scoped_accounts(company, *, branch_ids) -> QuerySet[MoneyAccount]:
    return scope.restrict(MoneyAccount.objects.for_company(company), branch_ids)


def scoped_debts(company, *, branch_ids) -> QuerySet[Debt]:
    return scope.restrict(Debt.objects.for_company(company), branch_ids)


def _with_outstanding(debts: QuerySet[Debt]) -> QuerySet[Debt]:
    return debts.annotate(
        outstanding=ExpressionWrapper(F("amount") - F("paid"), output_field=MoneyField())
    )


# Totals and the P&L ----------------------------------------------------------------------------


def _signed_pnl(rows: QuerySet[Transaction]) -> dict:
    """{"income", "expense"} of P&L rows: income as it is, expenses as positive amounts (an
    exchange gain on an expense category lowers expenses)."""
    sums = rows.aggregate(
        income=Sum("base_amount", filter=Q(category__kind=Category.Kind.INCOME)),
        expense=Sum("base_amount", filter=Q(category__kind=Category.Kind.EXPENSE)),
    )
    income = quantize(sums["income"] or 0)
    expense = quantize(-(sums["expense"] or 0))
    return {"income": income, "expense": expense, "profit": income - expense}


def totals(company, start: date, end: date, group_by: str | None = None, *, branch_ids) -> dict:
    """Income, expenses and profit from `start` to `end` (both included), on the P&L basis:
    posted income, expense, write-off and exchange-difference rows by their category's kind.
    Owner contributions, draws, transfers and opening balances never count. With `group_by`
    ("day", "week", "month") a zero-filled `series` too."""
    rows = posted_rows(company, branch_ids=branch_ids).filter(
        kind__in=PNL_KINDS, occurred_on__range=(start, end)
    )
    result = _signed_pnl(rows)
    if group_by:
        daily = (
            rows.values("occurred_on", "category__kind")
            .annotate(total=Sum("base_amount"))
            .order_by()
        )
        buckets = {
            key: {"income": ZERO, "expense": ZERO} for key in bucket_keys(start, end, group_by)
        }
        for entry in daily:
            key = bucket_of(entry["occurred_on"], group_by)
            if key not in buckets:
                continue
            if entry["category__kind"] == Category.Kind.INCOME:
                buckets[key]["income"] += entry["total"]
            else:
                buckets[key]["expense"] -= entry["total"]
        result["series"] = [
            {
                "date": key.isoformat(),
                "income": quantize(values["income"]),
                "expense": quantize(values["expense"]),
                "profit": quantize(values["income"] - values["expense"]),
            }
            for key, values in buckets.items()
        ]
    return result


def pnl(
    company,
    start: date,
    end: date,
    group: str = "month",
    *,
    branch_ids,
    compare: tuple[date, date] | None = None,
) -> dict:
    """The profit and loss statement: income and expense category trees with an amount per
    period (`group` "month" or "quarter", clipped to the range), totals, profit and margin.

    Each node carries `amounts` (per period), `total`, `own` (rows booked on the parent itself)
    and, with `compare`, `previous` (the compare range's total). Expenses are positive. Nodes
    with nothing in either range are left out.
    """
    periods = period_list(start, end, group)
    rows = posted_rows(company, branch_ids=branch_ids).filter(kind__in=PNL_KINDS)
    monthly = (
        rows.filter(occurred_on__range=(start, end))
        .annotate(month=TruncMonth("occurred_on"))
        .values("category_id", "month")
        .annotate(total=Sum("base_amount"))
        .order_by()
    )
    per_category: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO] * len(periods))
    for entry in monthly:
        index = _period_index(periods, entry["month"])
        if index is not None:
            per_category[entry["category_id"]][index] += entry["total"]
    previous: dict[int, Decimal] = {}
    if compare is not None:
        for entry in (
            rows.filter(occurred_on__range=compare)
            .values("category_id")
            .annotate(total=Sum("base_amount"))
            .order_by()
        ):
            previous[entry["category_id"]] = entry["total"]

    categories = {
        category.pk: category
        for category in Category.objects.for_company(company).order_by("order", "name", "pk")
    }

    def sign(category: Category, value: Decimal) -> Decimal:
        return quantize(value if category.kind == Category.Kind.INCOME else -value)

    def node(category: Category, children: list[dict]) -> dict:
        own = [
            sign(category, value) for value in per_category.get(category.pk, [ZERO] * len(periods))
        ]
        amounts = [
            quantize(own[index] + sum((child["amounts"][index] for child in children), ZERO))
            for index in range(len(periods))
        ]
        prev_own = sign(category, previous.get(category.pk, ZERO))
        prev_total = quantize(
            prev_own + sum((child["previous"] or ZERO for child in children), ZERO)
        )
        return {
            "id": category.pk,
            "name": category.name,
            "color": category.color,
            "system_code": category.system_code,
            "is_sensitive": category.is_sensitive,
            "amounts": amounts,
            "total": quantize(sum(amounts, ZERO)),
            "own": own,
            "own_total": quantize(sum(own, ZERO)),
            "previous": prev_total if compare is not None else None,
            "children": children,
        }

    def tree(kind: str) -> list[dict]:
        nodes = []
        tops = [c for c in categories.values() if c.kind == kind and c.parent_id is None]
        for top in tops:
            children = [
                node(child, []) for child in categories.values() if child.parent_id == top.pk
            ]
            children = [child for child in children if _has_amount(child)]
            built = node(top, children)
            if _has_amount(built):
                nodes.append(built)
        nodes.sort(key=lambda item: item["total"], reverse=True)
        return nodes

    def section(nodes: list[dict]) -> dict:
        amounts = [
            quantize(sum((item["amounts"][index] for item in nodes), ZERO))
            for index in range(len(periods))
        ]
        prev = quantize(sum((item["previous"] or ZERO for item in nodes), ZERO))
        return {
            "nodes": nodes,
            "amounts": amounts,
            "total": quantize(sum(amounts, ZERO)),
            "previous": prev if compare is not None else None,
        }

    income = section(tree(Category.Kind.INCOME))
    expense = section(tree(Category.Kind.EXPENSE))
    profit_amounts = [
        quantize(income["amounts"][index] - expense["amounts"][index])
        for index in range(len(periods))
    ]
    profit_total = quantize(income["total"] - expense["total"])
    profit_previous = (
        quantize(income["previous"] - expense["previous"]) if compare is not None else None
    )
    return {
        "group": group,
        "periods": [
            {"key": key, "from": first.isoformat(), "to": last.isoformat()}
            for key, first, last in periods
        ],
        "income": income,
        "expense": expense,
        "profit": {"amounts": profit_amounts, "total": profit_total, "previous": profit_previous},
        "margin": {
            "amounts": [
                _margin(profit_amounts[index], income["amounts"][index])
                for index in range(len(periods))
            ],
            "total": _margin(profit_total, income["total"]),
            "previous": _margin(profit_previous, income["previous"])
            if compare is not None
            else None,
        },
    }


def _has_amount(node: dict) -> bool:
    return any(node["amounts"]) or bool(node["previous"]) or bool(node["children"])


def _margin(profit: Decimal | None, income: Decimal | None) -> str | None:
    """Profit as a percentage of income, one decimal ("12.4"), or None without income."""
    if profit is None or not income:
        return None
    return str((profit / income * 100).quantize(Decimal("0.1")))


# Periods and buckets ---------------------------------------------------------------------------


def period_list(start: date, end: date, group: str) -> list[tuple[str, date, date]]:
    """[(key, first day, last day)] of each month ("2026-09") or quarter ("2026-Q3") that
    touches the range, clipped to it."""
    if group not in ("month", "quarter"):
        raise ValueError(f"group is month or quarter, not {group!r}.")
    periods = []
    cursor = date(start.year, start.month, 1)
    if group == "quarter":
        cursor = date(start.year, 3 * ((start.month - 1) // 3) + 1, 1)
    while cursor <= end:
        months = 3 if group == "quarter" else 1
        following = _add_months(cursor, months)
        first, last = max(cursor, start), min(following - timedelta(days=1), end)
        if group == "quarter":
            key = f"{cursor.year}-Q{(cursor.month - 1) // 3 + 1}"
        else:
            key = f"{cursor.year}-{cursor.month:02d}"
        periods.append((key, first, last))
        cursor = following
    return periods


def _period_index(periods, month: date) -> int | None:
    for index, (_key, first, last) in enumerate(periods):
        month_end = _add_months(date(month.year, month.month, 1), 1) - timedelta(days=1)
        if month_end >= first and month <= last:
            return index
    return None


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def bucket_of(day: date, group: str) -> date:
    if group == "day":
        return day
    if group == "week":
        return day - timedelta(days=day.weekday())
    if group == "month":
        return date(day.year, day.month, 1)
    raise ValueError(f"group is day, week or month, not {group!r}.")


def bucket_keys(start: date, end: date, group: str) -> list[date]:
    keys = []
    cursor = bucket_of(start, group)
    while cursor <= end:
        keys.append(cursor)
        if group == "day":
            cursor += timedelta(days=1)
        elif group == "week":
            cursor += timedelta(days=7)
        else:
            cursor = _add_months(cursor, 1)
    return keys


def auto_group(start: date, end: date) -> str:
    days = (end - start).days + 1
    if days <= 62:
        return "day"
    if days <= 190:
        return "week"
    return "month"


# Cash flow -----------------------------------------------------------------------------------


def _section_case():
    return Case(
        When(kind=Kind.OWNER, then=Value("owner")),
        When(kind=Kind.OPENING, then=Value("opening")),
        When(kind=Kind.TRANSFER, then=Value("transfers")),
        When(
            kind__in=(Kind.DEBT_OPEN, Kind.DEBT_PAYMENT),
            debt__kind=Debt.Kind.LOAN,
            then=Value("financing"),
        ),
        When(
            kind__in=(Kind.INCOME, Kind.EXPENSE), category__is_capex=True, then=Value("investing")
        ),
        default=Value("operating"),
        output_field=CharField(),
    )


def cash_flow(
    company,
    start: date,
    end: date,
    group_by: str = "day",
    *,
    branch_ids,
    compare: tuple[date, date] | None = None,
) -> dict:
    """Money in and out of the accounts from `start` to `end`: every posted row with an
    account, in the base currency at the rate each row was booked at.

    `series` (zero-filled per `group_by` bucket) and `totals` count real flows: operating,
    investing (equipment categories), financing (loans) and owner money; `income` is money in,
    `expense` money out (positive), `net` the difference. `sections` add the transfers between
    our own accounts and opening balances, so `start_cash + Σ sections = end_cash`.
    """
    rows = posted_rows(company, branch_ids=branch_ids).filter(account__isnull=False)
    in_range = rows.filter(occurred_on__range=(start, end)).annotate(section=_section_case())
    daily = (
        in_range.values("occurred_on", "section")
        .annotate(
            inflow=Sum("base_amount", filter=Q(base_amount__gt=0)),
            outflow=Sum("base_amount", filter=Q(base_amount__lt=0)),
        )
        .order_by()
    )
    buckets = {key: {"income": ZERO, "expense": ZERO} for key in bucket_keys(start, end, group_by)}
    sections = {key: {"income": ZERO, "expense": ZERO} for key in CASH_FLOW_SECTIONS}
    for entry in daily:
        inflow = entry["inflow"] or ZERO
        outflow = -(entry["outflow"] or ZERO)
        sections[entry["section"]]["income"] += inflow
        sections[entry["section"]]["expense"] += outflow
        if entry["section"] in FLOW_SECTIONS:
            key = bucket_of(entry["occurred_on"], group_by)
            if key in buckets:
                buckets[key]["income"] += inflow
                buckets[key]["expense"] += outflow
    start_cash = quantize(
        rows.filter(occurred_on__lt=start).aggregate(total=Sum("base_amount"))["total"] or 0
    )
    movement = sum((values["income"] - values["expense"] for values in sections.values()), ZERO)
    income = sum((sections[key]["income"] for key in FLOW_SECTIONS), ZERO)
    expense = sum((sections[key]["expense"] for key in FLOW_SECTIONS), ZERO)
    result = {
        "currency": company.base_currency,
        "group": group_by,
        "totals": {
            "income": quantize(income),
            "expense": quantize(expense),
            "net": quantize(income - expense),
        },
        "previous": None,
        "series": [
            {
                "date": key.isoformat(),
                "income": quantize(values["income"]),
                "expense": quantize(values["expense"]),
                "net": quantize(values["income"] - values["expense"]),
            }
            for key, values in buckets.items()
        ],
        "sections": [
            {
                "key": key,
                "income": quantize(values["income"]),
                "expense": quantize(values["expense"]),
                "net": quantize(values["income"] - values["expense"]),
            }
            for key, values in sections.items()
        ],
        "start_cash": start_cash,
        "end_cash": quantize(start_cash + movement),
    }
    if compare is not None:
        previous = cash_flow(company, compare[0], compare[1], group_by, branch_ids=branch_ids)
        result["previous"] = previous["totals"]
    return result


# Accounts ------------------------------------------------------------------------------------


def account_figures(accounts: list[MoneyAccount], today: date, value: Valuation) -> dict[int, dict]:
    """{account id: {"base", "spark", "last_activity"}}: the balance in the base currency at
    today's rate, the end-of-day balance of the last 30 days and the last day anything moved."""
    if not accounts:
        return {}
    ids = [account.pk for account in accounts]
    start = today - timedelta(days=29)
    posted = Transaction.objects.filter(account_id__in=ids, status=Status.POSTED)
    before = {
        entry["account_id"]: entry["total"]
        for entry in posted.filter(occurred_on__lt=start)
        .values("account_id")
        .annotate(total=Sum("amount"))
        .order_by()
    }
    daily: dict[int, dict[date, Decimal]] = defaultdict(dict)
    for entry in (
        posted.filter(occurred_on__range=(start, today))
        .values("account_id", "occurred_on")
        .annotate(total=Sum("amount"))
        .order_by()
    ):
        daily[entry["account_id"]][entry["occurred_on"]] = entry["total"]
    last = {
        entry["account_id"]: entry["day"]
        for entry in posted.values("account_id").annotate(day=Max("occurred_on")).order_by()
    }
    figures = {}
    for account in accounts:
        running = before.get(account.pk) or ZERO
        spark = []
        for offset in range(30):
            day = start + timedelta(days=offset)
            running += daily[account.pk].get(day, ZERO)
            spark.append(quantize(running))
        figures[account.pk] = {
            "base": value.to_base(account.balance, account.currency),
            "spark": spark,
            "last_activity": last.get(account.pk),
        }
    return figures


# Everything a statement line shows (the account's own name and category parents included), so a
# long statement costs the same few queries as a short one.
STATEMENT_RELATIONS = (
    "account",
    "category__parent",
    "counterparty",
    "membership",
    "branch",
    "project",
    "debt",
    "transfer",
    "created_by",
    "approved_by",
    "voided_by",
)


def statement(account: MoneyAccount, start: date, end: date) -> dict:
    """An account's posted rows from `start` to `end` with the running balance, the opening
    and closing balance, and entries waiting for approval."""
    opening = balance(account, start - timedelta(days=1))
    rows = list(
        Transaction.objects.filter(
            account=account, status=Status.POSTED, occurred_on__range=(start, end)
        )
        .select_related(*STATEMENT_RELATIONS)
        .order_by("occurred_on", "pk")
    )
    running = opening
    lines = []
    money_in = money_out = ZERO
    for row in rows:
        running += row.amount
        if row.amount > 0:
            money_in += row.amount
        else:
            money_out -= row.amount
        lines.append((row, quantize(running)))
    pending = list(
        Transaction.objects.filter(account=account, status=Status.PENDING)
        .select_related(*STATEMENT_RELATIONS)
        .order_by("occurred_on", "pk")
    )
    return {
        "opening": opening,
        "closing": quantize(running),
        "money_in": quantize(money_in),
        "money_out": quantize(money_out),
        "lines": lines,
        "pending": pending,
    }


def cash_position(company, on: date | None, *, branch_ids, today: date | None = None) -> dict:
    """Money on every account in scope at the end of `on` (now when None or today): per
    account, per currency, and in total in the base currency at that day's rate."""
    today = today or local_today(company)
    day = on or today
    accounts = list(
        scoped_accounts(company, branch_ids=branch_ids)
        .select_related("branch", "holder")
        .order_by("order", "name")
    )
    if day >= today:
        balances = {account.pk: account.balance for account in accounts}
    else:
        balances = {
            entry["account_id"]: entry["total"]
            for entry in Transaction.objects.filter(
                account__in=accounts, status=Status.POSTED, occurred_on__lte=day
            )
            .values("account_id")
            .annotate(total=Sum("amount"))
            .order_by()
        }
    value = valuation(company, day)
    by_currency: dict[str, Decimal] = defaultdict(lambda: ZERO)
    rows = []
    total = ZERO
    complete = True
    for account in accounts:
        amount = quantize(balances.get(account.pk) or ZERO)
        if not account.is_active and not amount:
            continue
        base = value.to_base(amount, account.currency)
        if base is None:
            complete = False
        else:
            total += base
        by_currency[account.currency] += amount
        rows.append(
            {
                "id": account.pk,
                "name": account.name,
                "kind": account.kind,
                "currency": account.currency,
                "branch_id": account.branch_id,
                "balance": amount,
                "base": base,
            }
        )
    return {
        "on": day,
        "currency": company.base_currency,
        "total": quantize(total),
        "complete": complete,
        "by_currency": [
            {
                "currency": currency,
                "amount": quantize(amount),
                "base": value.to_base(amount, currency),
            }
            for currency, amount in sorted(by_currency.items())
        ],
        "accounts": rows,
        "rate": {
            "rate": value.rate,
            "stale": value.stale,
            "source": value.source,
            "date": value.day,
        },
    }


# Ledger rows ------------------------------------------------------------------------------------


TRANSACTION_FILTERS = (
    "from",
    "to",
    "account",
    "category",
    "counterparty",
    "member",
    "branch",
    "kind",
    "status",
    "q",
    "min",
    "max",
    "has_receipt",
    "source_type",
    "debt",
    "project",
)


def filter_transactions(rows: QuerySet[Transaction], filters: dict) -> QuerySet[Transaction]:
    """Apply the list filters of `transactions/` (§4.7). Values are already parsed: days are
    dates, ids ints (lists for the multi-valued ones), amounts Decimals, `has_receipt` a bool.
    `category` includes the subcategories of a parent; `min`/`max` compare the absolute base
    amount; `q` matches the description, the counterparty and the person."""
    if start := filters.get("from"):
        rows = rows.filter(occurred_on__gte=start)
    if end := filters.get("to"):
        rows = rows.filter(occurred_on__lte=end)
    for key, field in (
        ("account", "account_id"),
        ("counterparty", "counterparty_id"),
        ("member", "membership_id"),
        ("branch", "branch_id"),
        ("kind", "kind"),
        ("status", "status"),
        ("source_type", "source_type"),
        ("debt", "debt_id"),
        ("project", "project_id"),
    ):
        value = filters.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list | tuple | set):
            rows = rows.filter(**{f"{field}__in": list(value)})
        else:
            rows = rows.filter(**{field: value})
    if categories := filters.get("category"):
        ids = list(categories) if isinstance(categories, list | tuple | set) else [categories]
        rows = rows.filter(Q(category_id__in=ids) | Q(category__parent_id__in=ids))
    if (low := filters.get("min")) is not None:
        rows = rows.filter(Q(base_amount__gte=low) | Q(base_amount__lte=-low))
    if (high := filters.get("max")) is not None:
        rows = rows.filter(base_amount__lte=high, base_amount__gte=-high)
    if (has_receipt := filters.get("has_receipt")) is not None:
        if has_receipt:
            rows = rows.filter(
                pk__in=Receipt.objects.filter(transaction__isnull=False).values("transaction_id")
            )
        else:
            rows = rows.exclude(
                pk__in=Receipt.objects.filter(transaction__isnull=False).values("transaction_id")
            )
    if q := (filters.get("q") or "").strip():
        text = (
            Q(description__icontains=q)
            | Q(counterparty__name__icontains=q)
            | Q(membership__first_name__icontains=q)
            | Q(membership__last_name__icontains=q)
            | Q(category__name__icontains=q)
            | Q(account__name__icontains=q)
        )
        if filters.get("mask_sensitive"):
            text = (
                Q(category__name__icontains=q)
                | Q(account__name__icontains=q)
                | (
                    text
                    & ~(Q(category__is_sensitive=True) | Q(debt__kind__in=Debt.SENSITIVE_KINDS))
                )
            )
        rows = rows.filter(text)
    return rows


def transactions(company, filters: dict, limit: int = 50, *, branch_ids) -> list[Transaction]:
    """Ledger rows in scope matching `filters` (see `filter_transactions`), newest first."""
    rows = scope.restrict(Transaction.objects.for_company(company), branch_ids)
    rows = filter_transactions(rows, filters).select_related(
        "account", "category", "counterparty", "membership", "branch", "debt"
    )
    return list(rows.order_by("-occurred_on", "-pk")[:limit])


# Debts ---------------------------------------------------------------------------------------


def debts(
    company,
    direction: str | None,
    *,
    branch_ids,
    overdue_only: bool = False,
    today: date | None = None,
) -> QuerySet[Debt]:
    """Open debts in scope (one direction, or both with None), the soonest due first, with
    `outstanding` in the debt's currency."""
    rows = scoped_debts(company, branch_ids=branch_ids).filter(status=Debt.Status.OPEN)
    if direction:
        rows = rows.filter(direction=direction)
    if overdue_only:
        rows = rows.filter(due_on__lt=today or local_today(company))
    return _with_outstanding(rows).order_by(F("due_on").asc(nulls_last=True), "issued_on", "pk")


def days_overdue(debt: Debt, today: date) -> int:
    if debt.due_on is None or debt.status != Debt.Status.OPEN or debt.due_on >= today:
        return 0
    return (today - debt.due_on).days


def debt_totals(company, *, branch_ids, today: date) -> dict:
    """What is owed to us and what we owe (book value in the base currency), with the overdue
    part and the counts, for the overview and the debts page header."""
    result = {
        direction: {"total": ZERO, "overdue": ZERO, "count": 0, "overdue_count": 0}
        for direction in Debt.Direction.values
    }
    for debt in debts(company, None, branch_ids=branch_ids, today=today).select_related("company"):
        value = book_value(debt, debt.amount - debt.paid)
        bucket = result[debt.direction]
        bucket["total"] += value
        bucket["count"] += 1
        if days_overdue(debt, today):
            bucket["overdue"] += value
            bucket["overdue_count"] += 1
    return result


def overdue_count(company, *, branch_ids, today: date) -> int:
    return debts(company, None, branch_ids=branch_ids, overdue_only=True, today=today).count()


def aging_bucket(days: int) -> str:
    if days <= 0:
        return "current"
    if days <= 30:
        return "d1_30"
    if days <= 60:
        return "d31_60"
    if days <= 90:
        return "d61_90"
    return "d90"


def debts_aging(
    company, direction: str, *, branch_ids, today: date, mask_sensitive: bool = False
) -> dict:
    """Open debts of one direction by how long they are overdue (current, 1-30, 31-60, 61-90,
    90+ days), per party and in total, at book value in the base currency. Without payroll
    access the salary-type debts of people are summed in one hidden row."""
    parties: dict[tuple, dict] = {}
    totals_ = dict.fromkeys(AGING_BUCKETS, ZERO)
    rows = debts(company, direction, branch_ids=branch_ids, today=today).select_related(
        "company", "counterparty", "membership"
    )
    for debt in rows:
        value = book_value(debt, debt.amount - debt.paid)
        bucket = aging_bucket(days_overdue(debt, today))
        if mask_sensitive and debt.kind in Debt.SENSITIVE_KINDS:
            key = ("hidden", 0)
            label = None
        elif debt.counterparty_id:
            key = ("counterparty", debt.counterparty_id)
            label = debt.counterparty.name
        else:
            key = ("member", debt.membership_id)
            label = str(debt.membership)
        party = parties.setdefault(
            key,
            {
                "type": key[0],
                "id": key[1] or None,
                "name": label,
                **dict.fromkeys(AGING_BUCKETS, ZERO),
                "total": ZERO,
                "count": 0,
                "oldest_due": None,
            },
        )
        party[bucket] += value
        party["total"] += value
        party["count"] += 1
        if debt.due_on and (party["oldest_due"] is None or debt.due_on < party["oldest_due"]):
            party["oldest_due"] = debt.due_on
        totals_[bucket] += value
    ordered = sorted(parties.values(), key=lambda item: item["total"], reverse=True)
    return {
        "direction": direction,
        "currency": company.base_currency,
        "totals": {**totals_, "total": sum(totals_.values(), ZERO)},
        "parties": ordered,
    }


def installment_schedule(debt: Debt, today: date) -> list[dict]:
    """The debt's instalments with how much of each is covered by the payments so far, in
    order: `status` paid, partial, due (not yet), overdue."""
    covered = debt.paid
    schedule = []
    for installment in DebtInstallment.objects.filter(debt=debt).order_by(
        "due_on", "position", "pk"
    ):
        paid = min(covered, installment.amount)
        covered -= paid
        if paid == installment.amount:
            status = "paid"
        elif installment.due_on < today:
            status = "overdue"
        elif paid > 0:
            status = "partial"
        else:
            status = "due"
        schedule.append(
            {
                "id": installment.pk,
                "due_on": installment.due_on,
                "amount": installment.amount,
                "paid": quantize(paid),
                "status": status,
            }
        )
    return schedule


# Balances on a date ---------------------------------------------------------------------------


def balances_on(company, on: date, *, branch_ids) -> dict:
    """What the company had at the end of `on`: every account's balance (and its base value at
    that day's rate), what was owed to us and what we owed then (at book value), and the net
    position."""
    position = cash_position(company, on, branch_ids=branch_ids, today=on + timedelta(days=1))
    settled = defaultdict(lambda: ZERO)
    for entry in (
        Transaction.objects.filter(
            company=company,
            status=Status.POSTED,
            kind__in=(Kind.DEBT_PAYMENT, Kind.WRITE_OFF),
            occurred_on__lte=on,
        )
        .values("debt_id")
        .annotate(total=Sum("debt_amount"))
        .order_by()
    ):
        settled[entry["debt_id"]] = entry["total"] or ZERO
    owed = {direction: ZERO for direction in Debt.Direction.values}
    counts = {direction: 0 for direction in Debt.Direction.values}
    for debt in (
        scoped_debts(company, branch_ids=branch_ids)
        .exclude(status=Debt.Status.CANCELLED)
        .filter(issued_on__lte=on)
        .select_related("company")
    ):
        left = debt.amount - settled[debt.pk]
        if left > 0:
            owed[debt.direction] += book_value(debt, left)
            counts[debt.direction] += 1
    receivable = quantize(owed[Debt.Direction.RECEIVABLE])
    payable = quantize(owed[Debt.Direction.PAYABLE])
    return {
        **position,
        "receivable": {"total": receivable, "count": counts[Debt.Direction.RECEIVABLE]},
        "payable": {"total": payable, "count": counts[Debt.Direction.PAYABLE]},
        "net": quantize(position["total"] + receivable - payable),
    }


# Category trend ------------------------------------------------------------------------------


def category_trend(company, category: Category, months: int, *, branch_ids, today: date) -> dict:
    """A category (with its subcategories) month by month for the last `months` months,
    this one included, and the monthly average of the full months since the books began (months
    before the first ledger row would only drag the average down)."""
    months = max(1, min(int(months), 36))
    first = _add_months(date(today.year, today.month, 1), -(months - 1))
    rows = posted_rows(company, branch_ids=branch_ids).filter(
        Q(category=category) | Q(category__parent=category),
        kind__in=PNL_KINDS,
        occurred_on__range=(first, today),
    )
    sums = {
        entry["month"]: entry["total"]
        for entry in rows.annotate(month=TruncMonth("occurred_on"))
        .values("month")
        .annotate(total=Sum("base_amount"))
        .order_by()
    }
    sign = 1 if category.kind == Category.Kind.INCOME else -1
    series = []
    for index in range(months):
        month = _add_months(first, index)
        series.append(
            {"date": month.isoformat(), "amount": quantize(sign * (sums.get(month) or ZERO))}
        )
    began = posted_rows(company, branch_ids=branch_ids).aggregate(day=Min("occurred_on"))["day"]
    since = date(began.year, began.month, 1).isoformat() if began else first.isoformat()
    full = [point["amount"] for point in series[:-1] if point["date"] >= since] or [
        series[-1]["amount"]
    ]
    # This month is still running: compare it with the same days of last month, as the overview
    # does, not with the whole of last month.
    month_start = date(today.year, today.month, 1)
    last_start = _add_months(month_start, -1)
    last_end = min(
        last_start + timedelta(days=(today - month_start).days), month_start - timedelta(days=1)
    )
    same_days = (
        posted_rows(company, branch_ids=branch_ids)
        .filter(
            Q(category=category) | Q(category__parent=category),
            kind__in=PNL_KINDS,
            occurred_on__range=(last_start, last_end),
        )
        .aggregate(total=Sum("base_amount"))["total"]
    )
    return {
        "category": {"id": category.pk, "name": category.name, "kind": category.kind},
        "currency": company.base_currency,
        "series": series,
        "average": quantize(sum(full, ZERO) / len(full)),
        "total": quantize(sum((point["amount"] for point in series), ZERO)),
        "previous_same_days": {
            "from": last_start.isoformat(),
            "to": last_end.isoformat(),
            "amount": quantize(sign * (same_days or ZERO)),
        },
    }


# Overview ------------------------------------------------------------------------------------


def overview(company, *, branch_ids, today: date, mask_sensitive: bool = False) -> dict:
    """The finance overview (§4.7 `overview/`): cash now (in base and per currency), income,
    expenses and profit this month so far against the same days of last month, what is owed
    both ways with the overdue part, what falls due in the next 7 days, entries waiting for
    approval, the month's expenses by top-level category (all of them, biggest first, so they add
    up to the month's expenses), the rate and its stale flag."""
    position = cash_position(company, None, branch_ids=branch_ids, today=today)
    month_start = today.replace(day=1)
    last_start = _add_months(month_start, -1)
    last_end = min(
        last_start + timedelta(days=(today - month_start).days), month_start - timedelta(days=1)
    )
    current = totals(company, month_start, today, branch_ids=branch_ids)
    previous = totals(company, last_start, last_end, branch_ids=branch_ids)
    owed = debt_totals(company, branch_ids=branch_ids, today=today)
    soon = list(
        debts(company, None, branch_ids=branch_ids, today=today)
        .filter(due_on__range=(today, today + timedelta(days=7)))
        .select_related("company", "counterparty", "membership", "branch", "responsible")[:8]
    )
    pending = scope.restrict(
        Transaction.objects.for_company(company).filter(status=Status.PENDING), branch_ids
    )
    top = (
        posted_rows(company, branch_ids=branch_ids)
        .filter(
            kind__in=PNL_KINDS,
            occurred_on__range=(month_start, today),
            category__kind=Category.Kind.EXPENSE,
        )
        .annotate(
            group_id=Case(
                When(category__parent__isnull=False, then=F("category__parent_id")),
                default=F("category_id"),
            )
        )
        .values("group_id")
        .annotate(total=Sum("base_amount"))
        .order_by("total")
    )
    names = {
        category.pk: category
        for category in Category.objects.filter(pk__in=[entry["group_id"] for entry in top])
    }
    negative = [account for account in position["accounts"] if account["balance"] < 0]
    return {
        "currency": company.base_currency,
        "today": today,
        "cash": position,
        "month": {
            "from": month_start,
            "to": today,
            "income": current["income"],
            "expense": current["expense"],
            "profit": current["profit"],
            "previous": {
                "from": last_start,
                "to": last_end,
                "income": previous["income"],
                "expense": previous["expense"],
                "profit": previous["profit"],
            },
        },
        "receivable": owed[Debt.Direction.RECEIVABLE],
        "payable": owed[Debt.Direction.PAYABLE],
        "due_soon": soon,
        "pending": {
            "count": pending.count(),
            "total": quantize(-(pending.aggregate(total=Sum("base_amount"))["total"] or 0)),
        },
        "top_expenses": [
            {
                "id": entry["group_id"],
                "name": names[entry["group_id"]].name if entry["group_id"] in names else "",
                "color": names[entry["group_id"]].color if entry["group_id"] in names else "",
                "amount": quantize(-entry["total"]),
            }
            for entry in top
            if entry["total"] < 0
        ],
        "negative_accounts": negative,
        "rate": position["rate"],
    }


# Counterparties --------------------------------------------------------------------------------


def party_balances(parties: list[Counterparty], today: date, *, branch_ids) -> dict[int, dict]:
    """{counterparty id: {"owes_us", "we_owe", "overdue", "last_activity"}} at book value,
    from the debts and entries in `branch_ids` (the directory is company-wide, debts are not)."""
    if not parties:
        return {}
    ids = [party.pk for party in parties]
    figures = {
        pk: {"owes_us": ZERO, "we_owe": ZERO, "overdue": ZERO, "last_activity": None} for pk in ids
    }
    company = parties[0].company_id  # `filter(company=…)` takes the id as well
    open_debts = scoped_debts(company, branch_ids=branch_ids).filter(
        counterparty_id__in=ids, status=Debt.Status.OPEN
    )
    for debt in open_debts.select_related("company"):
        value = book_value(debt, debt.amount - debt.paid)
        entry = figures[debt.counterparty_id]
        entry["owes_us" if debt.direction == Debt.Direction.RECEIVABLE else "we_owe"] += value
        if days_overdue(debt, today):
            entry["overdue"] += value
    for entry in (
        posted_rows(company, branch_ids=branch_ids)
        .filter(counterparty_id__in=ids)
        .values("counterparty_id")
        .annotate(day=Max("occurred_on"))
        .order_by()
    ):
        figures[entry["counterparty_id"]]["last_activity"] = entry["day"]
    return figures


def party_totals(party: Counterparty, *, branch_ids) -> dict:
    """Lifetime money with a counterparty: income from them and expenses with them (P&L
    basis), and what moved through the accounts."""
    rows = posted_rows(party.company, branch_ids=branch_ids).filter(counterparty=party)
    pnl_part = _signed_pnl(rows.filter(kind__in=PNL_KINDS))
    flows = rows.filter(account__isnull=False).aggregate(
        money_in=Sum("base_amount", filter=Q(base_amount__gt=0)),
        money_out=Sum("base_amount", filter=Q(base_amount__lt=0)),
    )
    return {
        "income": pnl_part["income"],
        "expense": pnl_part["expense"],
        "money_in": quantize(flows["money_in"] or 0),
        "money_out": quantize(-(flows["money_out"] or 0)),
    }


# Search --------------------------------------------------------------------------------------


def search_transactions(
    rows: QuerySet[Transaction], q: str, limit: int, *, mask_sensitive: bool
) -> list:
    query = (
        Q(description__icontains=q)
        | Q(counterparty__name__icontains=q)
        | Q(category__name__icontains=q)
    )
    digits = "".join(ch for ch in q if ch.isdigit())
    if digits and len(digits) >= 3 and digits == q.replace(" ", ""):
        number = Decimal(digits)
        query |= (
            Q(base_amount=number) | Q(base_amount=-number) | Q(amount=number) | Q(amount=-number)
        )
    if mask_sensitive:
        query &= ~(Q(category__is_sensitive=True) & ~Q(category__name__icontains=q))
    return list(
        rows.filter(query)
        .exclude(status__in=(Status.VOID, Status.REJECTED))
        .select_related("category", "counterparty", "account", "debt")
        .order_by("-occurred_on", "-pk")[:limit]
    )


def search_counterparties(rows: QuerySet[Counterparty], q: str, limit: int) -> list:
    query = Q(name__icontains=q) | Q(contact_person__icontains=q) | Q(tin__startswith=q)
    digits = "".join(ch for ch in q if ch.isdigit())
    if len(digits) >= 4:
        query |= Q(phone__contains=digits)
    return list(rows.filter(query).order_by("-is_active", "name")[:limit])
