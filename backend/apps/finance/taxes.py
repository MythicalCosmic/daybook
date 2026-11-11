"""The tax calendar (v12, the owner's feature 5): what is due and when, for the company's regime
and what it has, with an estimate from its own books, a reminder before each deadline, and
"paid" linked to the payment in the ledger. Plus what turnover tax and VAT would have cost on its
last twelve months.

The rules (deadlines, rates, laws) live in `tax_rules`; this module applies them:
- `deadlines(company, start, end)`: each deadline in the window, with its period, due day (moved
  off weekends and the company's holidays, Tax Code art. 5), what to do (file, pay, both), an
  estimate and how it is worked out, and its state (done, overdue, due);
- an estimate comes from the books: VAT on sales less VAT on goods bought, turnover x rate, the
  quarter's profit x 15 %, the month's payroll taxes (payroll's own tax debts when it books them,
  else 12 % of the salaries); a tax debt due that day (booked by the company or payroll) replaces
  the estimate with its amount;
- a deadline is done when someone marked it (`TaxMark`, with the ledger row that paid it), when a
  tax debt due that day is paid, when payroll's tax debts of that month are paid, or when the
  tax calendar's recurring bill (`tax_calendar` templates) of that month was paid;
- `remind`: owners hear `tax_remind_days` days before and on the day, at the company's morning
  hour, unless a recurring tax bill already reminds them of that tax;
- `compare`: the last twelve full months under turnover tax, VAT 12 % (with profit tax) and the
  simplified 6 % VAT, with the formulas and the threshold that forces VAT.

Every figure is an estimate and every screen says so: "Check with your accountant".
"""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.exceptions import DomainError
from apps.core.money import format_money, quantize
from apps.finance import conf, queries, recurring, services, tax_rules
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    LIVE_STATUSES,
    Debt,
    FinanceSettings,
    MoneyAccount,
    RecurringRule,
    TaxMark,
    Transaction,
)
from apps.finance.sources import Source
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
HUNDRED = Decimal(100)
SOURCE = "finance.tax"  # a payment recorded from the calendar: id = TaxMark.pk
NOTIFICATION = "finance.tax_due"
WARNING = gettext_lazy("Check with your accountant.")
DEADLINE_STATUSES = ("due", "overdue", "done")
# The recurring tax bills of the tax calendar templates (`tax_calendar`) by the rule they stand for.
TEMPLATE_RULES = {
    "tax.vat": "vat",
    "tax.vat_simplified": "vat_simplified",
    "tax.turnover": "turnover",
    "tax.profit": "profit",
    "tax.income_tax": "income_tax",
    "tax.inps": "income_tax",
    "tax.social_tax": "social_tax",
}
PAYROLL_KEYS = {"income_tax": ("tax_withheld", "tax_on_top"), "social_tax": ("tax_social",)}
GOODS = "goods"
TAX_CODES = ("taxes",)


@dataclass
class Deadline:
    rule: tax_rules.Rule
    period_start: date
    period_end: date
    due_on: date
    estimate: Decimal | None = None
    basis: str = ""  # how the estimate is made
    booked: bool = False  # the amount is a booked tax debt, not an estimate
    status: str = "due"  # due, overdue, done
    done_on: date | None = None
    mark_id: int | None = None
    paid: Decimal | None = None
    transaction_id: int | None = None
    debt_id: int | None = None
    rule_id: int | None = None  # the recurring tax bill that reminds of it
    links: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.rule.key}:{self.period_start.isoformat()}"

    @property
    def mark_kind(self) -> str:
        return TaxMark.Kind.FILE if self.rule.action == "file" else TaxMark.Kind.PAY


# The company's profile -----------------------------------------------------------------------


def profile(company, today: date) -> dict:
    """What decides the company's deadlines: its regime, whether it pays people, owns premises
    or land, and had a big year."""
    settings_row = conf.get_settings(company)
    last_year = queries.totals(
        company, date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), branch_ids=None
    )["income"]
    return {
        "regime": settings_row.tax_regime,
        "payroll": company.has_feature("payroll") or _has_salaries(company, today),
        "property": settings_row.owns_property,
        "land": settings_row.owns_land,
        "big_income": last_year > tax_rules.PROFIT_ADVANCE_INCOME,
        "sells_medicines": sells_medicines(company),
    }


def sells_medicines(company) -> bool:
    """Every kind of business this product knows (pharmacy, distributor or both) trades in
    medicines: Tax Code art. 461 part 2 item 14 bars them from turnover tax."""
    return bool(company.business_kind)


def _has_salaries(company, today: date) -> bool:
    start = today - timedelta(days=62)
    return (
        queries.posted_rows(company, branch_ids=None)
        .filter(occurred_on__gte=start, category__system_code__in=("salaries", "payroll_taxes"))
        .exists()
    )


def applies(rule: tax_rules.Rule, facts: dict, on: date) -> bool:
    if facts["regime"] not in rule.regimes or not tax_rules.in_force(rule, on):
        return False
    return not rule.needs or bool(facts.get(rule.needs))


# Periods and due days ------------------------------------------------------------------------


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = month - 1 + months
    return year + index // 12, index % 12 + 1


def periods(rule: tax_rules.Rule, first: date, last: date) -> list[tuple[date, date]]:
    """The rule's periods whose due day may fall from `first` to `last`."""
    # Look back far enough for the latest-due rules (a year's return is due in March).
    start = date(first.year - 1, 1, 1)
    found = []
    year, month = start.year, start.month
    while date(year, month, 1) <= last:
        if rule.period == "month":
            begin = date(year, month, 1)
            found.append((begin, _month_end(begin)))
            year, month = _add_months(year, month, 1)
        elif rule.period == "quarter":
            quarter = (month - 1) // 3 + 1
            begin = date(year, (quarter - 1) * 3 + 1, 1)
            end = _month_end(date(year, quarter * 3, 1))
            if quarter in rule.quarters:
                found.append((begin, end))
            year, month = _add_months(begin.year, begin.month, 3)
        else:
            found.append((date(year, 1, 1), date(year, 12, 31)))
            year, month = year + 1, 1
    return found


def nominal_due(rule: tax_rules.Rule, start: date, end: date) -> date:
    """The due day the law names, before a weekend or holiday moves it."""
    base = end if rule.anchor == "end" else start
    year, month = _add_months(base.year, base.month, rule.months)
    day = rule.january_day if (month == 1 and rule.january_day) else rule.day
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def working_day(day: date, days_off: set[date]) -> date:
    """Tax Code art. 5: a deadline on a day off moves to the next working day."""
    for _attempt in range(14):
        if day.weekday() < 5 and day not in days_off:
            return day
        day += timedelta(days=1)
    return day


# The calendar -------------------------------------------------------------------------------


def deadlines(
    company, first: date, last: date, *, today: date | None = None, facts: dict | None = None
) -> list[Deadline]:
    """Every deadline due from `first` to `last`, the soonest first, with estimates and states."""
    today = today or queries.local_today(company)
    facts = facts or profile(company, today)
    try:
        days_off = recurring.holidays(company, first, last + timedelta(days=14))
    except Exception:  # the time-off module is optional
        logger.exception("Holidays failed for company %s", company.pk)
        days_off = set()
    found: list[Deadline] = []
    for rule in tax_rules.RULES:
        for start, end in periods(rule, first, last):
            if not applies(rule, facts, end):
                continue
            due = working_day(nominal_due(rule, start, end), days_off)
            if first <= due <= last:
                found.append(Deadline(rule, start, end, due))
    found.sort(key=lambda item: (item.due_on, item.rule.key))
    _fill(company, found, today, facts)
    return found


def _fill(company, rows: list[Deadline], today: date, facts: dict) -> None:
    if not rows:
        return
    marks = {
        (mark.tax, mark.kind, mark.period_start): mark
        for mark in TaxMark.objects.filter(
            company=company,
            period_start__gte=min(row.period_start for row in rows),
            period_start__lte=max(row.period_start for row in rows),
        )
    }
    tax_debts = list(
        Debt.objects.filter(
            company=company,
            kind=Debt.Kind.TAX,
            direction=Debt.Direction.PAYABLE,
            status__in=(Debt.Status.OPEN, Debt.Status.PAID),
        )
        .select_related("company")
        .filter(
            Q(due_on__range=(rows[0].due_on, rows[-1].due_on))
            | Q(
                source_type="payroll.run",
                issued_on__range=(
                    min(row.period_start for row in rows),
                    max(row.period_end for row in rows) + timedelta(days=45),
                ),
            )
        )
    )
    templates = {
        TEMPLATE_RULES[rule.template_key]: rule
        for rule in RecurringRule.objects.filter(
            company=company, is_active=True, template_key__in=list(TEMPLATE_RULES)
        )
    }
    # The months each template bill was paid in (its occurrence's due day starts its key).
    paid_months: dict[int, set[date]] = defaultdict(set)
    for rule_id, key in Transaction.objects.filter(
        company=company,
        source_type=recurring.SOURCE,
        source_id__in=[rule.pk for rule in templates.values()],
        status__in=LIVE_STATUSES,
    ).values_list("source_id", "source_key"):
        try:
            paid_months[rule_id].add(date.fromisoformat(key[:10]).replace(day=1))
        except ValueError:
            continue
    settings_row = conf.get_settings(company)
    figures: dict[tuple[date, date], dict] = {}
    # A tax debt due on a day stands for that day's deadline only when nothing else is due then
    # (VAT and profit tax are both due on the 20th: then the debt is not guessed at).
    paying = defaultdict(int)
    for row in rows:
        if row.rule.action != "file" and row.rule.key not in PAYROLL_KEYS:
            paying[row.due_on] += 1
    for row in rows:
        if row.period_start <= today:  # a period not begun has no books to estimate from
            _estimate(company, row, settings_row, figures)
        mark = marks.get((row.rule.key, row.mark_kind, row.period_start))
        if row.rule.key in templates:
            row.rule_id = templates[row.rule.key].pk
        _booked(row, tax_debts, alone=paying[row.due_on] == 1)
        if mark is not None:
            row.status = "done"
            row.done_on = mark.done_on
            row.mark_id = mark.pk
            row.paid = mark.amount
            row.transaction_id = mark.transaction_id
        elif row.debt_id is not None and row.status == "done":
            pass  # its tax debt is paid
        elif row.rule.key in templates and _template_paid(
            templates[row.rule.key], row, paid_months
        ):
            row.status = "done"
        else:
            row.status = "overdue" if row.due_on < today else "due"


def _booked(row: Deadline, tax_debts: list[Debt], *, alone: bool = True) -> None:
    """A tax debt for this deadline: payroll's tax debts of the period (income and social tax),
    or the one tax debt due on its day when this is the only deadline paid that day."""
    if row.rule.action == "file":
        return
    keys = PAYROLL_KEYS.get(row.rule.key)
    if keys and row.rule.period == "month":
        mine = [
            debt
            for debt in tax_debts
            if debt.source_type == "payroll.run"
            and debt.source_key in keys
            and row.period_start <= debt.issued_on <= row.period_end + timedelta(days=10)
        ]
    else:
        mine = [
            debt
            for debt in tax_debts
            if debt.source_type != "payroll.run" and debt.due_on == row.due_on
        ]
        if len(mine) != 1 or not alone:
            return
    if not mine:
        return
    row.estimate = quantize(sum((queries.book_value(debt, debt.amount) for debt in mine), ZERO))
    row.booked = True
    row.basis = _("Booked as a tax debt")
    row.debt_id = mine[0].pk
    if all(debt.status == Debt.Status.PAID for debt in mine):
        row.status = "done"
        row.paid = row.estimate


def _template_paid(rule: RecurringRule, row: Deadline, paid_months: dict) -> bool:
    """The recurring tax bill of that month was paid (or skipped)."""
    month = row.due_on.replace(day=1)
    if month in paid_months.get(rule.pk, ()):
        return True
    return bool(rule.last_done_on and rule.last_done_on.replace(day=1) >= month)


# Estimates from the books ------------------------------------------------------------------


def _money_text(amount: Decimal, currency: str) -> str:
    return format_money(quantize(amount), currency, translation.get_language() or "uz")


def _goods(company, start: date, end: date) -> Decimal:
    """Goods bought (the "goods" expense tree), in the base currency."""
    total = (
        queries.posted_rows(company, branch_ids=None)
        .filter(kind__in=queries.PNL_KINDS, capitalized=False, occurred_on__range=(start, end))
        .filter(Q(category__system_code=GOODS) | Q(category__parent__system_code=GOODS))
        .aggregate(total=Sum("base_amount"))["total"]
    )
    return quantize(-(total or ZERO))


def _taxes_booked(company, start: date, end: date) -> Decimal:
    """Taxes booked as expenses (VAT and profit tax are not costs of the business)."""
    total = (
        queries.posted_rows(company, branch_ids=None)
        .filter(kind__in=queries.PNL_KINDS, capitalized=False, occurred_on__range=(start, end))
        .filter(
            Q(category__system_code__in=TAX_CODES) | Q(category__parent__system_code__in=TAX_CODES)
        )
        .aggregate(total=Sum("base_amount"))["total"]
    )
    return quantize(-(total or ZERO))


def _salaries(company, start: date, end: date) -> Decimal:
    total = (
        queries.posted_rows(company, branch_ids=None)
        .filter(kind__in=queries.PNL_KINDS, occurred_on__range=(start, end))
        .filter(category__system_code="salaries")
        .aggregate(total=Sum("base_amount"))["total"]
    )
    return quantize(-(total or ZERO))


def books(company, start: date, end: date) -> dict:
    """The period's figures the estimates use, in the base currency."""
    totals = queries.totals(company, start, end, branch_ids=None)
    return {
        "income": totals["income"],
        "expense": totals["expense"],
        "goods": _goods(company, start, end),
        "taxes": _taxes_booked(company, start, end),
        "salaries": _salaries(company, start, end),
    }


def vat_part(amount: Decimal, percent: Decimal) -> Decimal:
    """The VAT inside a price that includes it: amount x r / (100 + r)."""
    return quantize(amount * percent / (HUNDRED + percent))


def _estimate(company, row: Deadline, settings_row, cache: dict | None = None) -> None:
    rule = row.rule
    if rule.action == "file":
        return
    currency = company.base_currency
    key = rule.key
    if key not in ("vat", "vat_simplified", "turnover", "profit", "income_tax", "social_tax"):
        return  # property, land, profit advances and the year's balance: no estimate
    period = (row.period_start, row.period_end)
    cache = cache if cache is not None else {}
    if period not in cache:
        cache[period] = books(company, *period)
    figures = cache[period]
    if key == "vat":
        rate = settings_row.vat_percent or tax_rules.TAXES["vat"].rate
        output = vat_part(figures["income"], rate)
        credit = vat_part(figures["goods"], rate)
        row.estimate = max(output - credit, ZERO)
        row.basis = _(
            "VAT in sales %(output)s less VAT in goods bought %(input)s (%(rate)s %% inside prices)"
        ) % {
            "output": _money_text(output, currency),
            "input": _money_text(credit, currency),
            "rate": _number(rate),
        }
    elif key == "vat_simplified":
        rate = tax_rules.TAXES["vat_simplified"].rate
        row.estimate = vat_part(figures["income"], rate)
        row.basis = _("%(rate)s %% inside sales of %(income)s, no VAT credit") % {
            "rate": _number(rate),
            "income": _money_text(figures["income"], currency),
        }
    elif key == "turnover":
        rate = settings_row.turnover_tax_percent
        row.estimate = quantize(figures["income"] * rate / HUNDRED)
        row.basis = _("%(rate)s %% of income %(income)s") % {
            "rate": _number(rate),
            "income": _money_text(figures["income"], currency),
        }
    elif key == "profit":
        rate = tax_rules.TAXES["profit"].rate
        vat_rate = settings_row.vat_percent or tax_rules.TAXES["vat"].rate
        net_vat = vat_part(figures["income"], vat_rate) - vat_part(figures["goods"], vat_rate)
        base = figures["income"] - figures["expense"] + figures["taxes"] - net_vat
        row.estimate = quantize(max(base, ZERO) * rate / HUNDRED)
        row.basis = _("%(rate)s %% of the quarter's profit before taxes %(profit)s") % {
            "rate": _number(rate),
            "profit": _money_text(base, currency),
        }
    else:  # income_tax, social_tax
        rate = tax_rules.TAXES[key].rate
        if not figures["salaries"]:
            return
        row.estimate = quantize(figures["salaries"] * rate / HUNDRED)
        row.basis = _("%(rate)s %% of salaries %(salaries)s") % {
            "rate": _number(rate),
            "salaries": _money_text(figures["salaries"], currency),
        }


def _number(value: Decimal) -> str:
    text = format(Decimal(value).normalize(), "f")
    return text.replace(".", ",") if translation.get_language() in ("uz", "ru") else text


# Marking a deadline done ---------------------------------------------------------------------


def find(company, rule_key: str, period_start: date) -> Deadline:
    """The deadline of `rule_key` for the period starting `period_start` (DomainError if the rule
    doesn't apply to the company)."""
    rule = tax_rules.RULES_BY_KEY.get(rule_key)
    if rule is None:
        raise DomainError(_("There is no such tax deadline."))
    found = [
        row
        for row in deadlines(company, period_start, period_start + timedelta(days=500), today=None)
        if row.rule.key == rule_key and row.period_start == period_start
    ]
    if not found:
        raise DomainError(_("There is no such tax deadline."))
    return found[0]


@transaction.atomic
def mark(
    company,
    *,
    by: Membership,
    rule_key: str,
    period_start: date,
    done_on: date,
    transaction_row: Transaction | None = None,
    account: MoneyAccount | None = None,
    amount=None,
    note: str = "",
) -> TaxMark:
    """Mark a deadline done: filed, or paid. A payment is linked to a ledger row that paid it
    (`transaction_row`), or recorded now from `account` (an expense "Taxes" or "Payroll taxes"
    to the tax office), or only marked."""
    deadline = find(company, rule_key, period_start)
    if transaction_row is not None and account is not None:
        raise DomainError(_("Link a payment or record one, not both."))
    if transaction_row is not None:
        services._same_company(company, transaction_row)
        if transaction_row.status not in LIVE_STATUSES or transaction_row.base_amount >= 0:
            raise DomainError(_("Pick a payment that went out."))
    paid = services._money(amount, allow_zero=True) if amount not in (None, "") else None
    if account is not None and not paid:
        raise DomainError(_("Enter how much was paid."))
    try:
        with transaction.atomic():
            row = TaxMark.objects.create(
                company=company,
                tax=deadline.rule.key,
                kind=deadline.mark_kind,
                period_start=deadline.period_start,
                period_end=deadline.period_end,
                due_on=deadline.due_on,
                done_on=done_on,
                transaction=transaction_row,
                amount=paid
                if paid is not None
                else (abs(transaction_row.base_amount) if transaction_row is not None else None),
                note=(note or "").strip()[:300],
                created_by=by.user,
            )
    except IntegrityError:
        raise DomainError(_("This deadline is already marked.")) from None
    if account is not None:
        code = "payroll_taxes" if deadline.rule.tax in ("income_tax", "social_tax") else "taxes"
        with translation.override(company.default_language or "uz"):
            text = f"{deadline.rule.name}: {label(deadline)}"
        booked = services.record_transaction(
            company,
            by=by,
            kind=Transaction.Kind.EXPENSE,
            amount=paid,
            occurred_on=done_on,
            account=account,
            category=code,
            counterparty=recurring.tax_office(company, by=by),
            description=text[:300],
            source=Source(SOURCE, row.pk, deadline.rule.key[:32]),
        )
        row.transaction = booked
        row.save(update_fields=["transaction", "updated_at"])
    services._audit(
        FinanceAction.TAX_MARKED,
        company,
        by.user,
        conf.get_settings(company),
        tax=deadline.rule.key,
        period=deadline.period_start.isoformat(),
        kind=row.kind,
        transaction=row.transaction_id,
        amount=str(row.amount) if row.amount is not None else None,
    )
    return row


@transaction.atomic
def unmark(row: TaxMark, *, by: Membership, reason: str = "") -> None:
    """Take a mark back; a payment recorded from the calendar is voided with it."""
    row = TaxMark.objects.select_for_update().get(pk=row.pk)
    company = row.company
    booked = row.transaction
    details = {"tax": row.tax, "period": row.period_start.isoformat(), "kind": row.kind}
    if booked is not None and booked.source_type == SOURCE and booked.status in LIVE_STATUSES:
        row.transaction = None
        row.save(update_fields=["transaction", "updated_at"])
        services.void_transaction(booked, by=by, reason=reason or _("Tax mark taken back"))
    row.delete()
    services._audit(
        FinanceAction.TAX_UNMARKED, company, by.user, conf.get_settings(company), **details
    )


def candidates(company, deadline: Deadline) -> list[Transaction]:
    """Ledger rows that may be this deadline's payment: money out in a tax category or to a tax
    debt, from the period's start to a month after the due day, not yet linked."""
    linked = TaxMark.objects.filter(company=company, transaction__isnull=False).values_list(
        "transaction_id", flat=True
    )
    taxes = Q(category__system_code__in=("taxes", "payroll_taxes")) | Q(
        category__parent__system_code__in=("taxes", "payroll_taxes")
    )
    return list(
        Transaction.objects.filter(
            company=company,
            status__in=LIVE_STATUSES,
            account__isnull=False,
            base_amount__lt=0,
            occurred_on__range=(deadline.period_start, deadline.due_on + timedelta(days=31)),
        )
        .filter(taxes | Q(debt__kind=Debt.Kind.TAX))
        .exclude(pk__in=linked)
        .select_related("account", "category__parent", "counterparty", "debt")
        .order_by("-occurred_on", "-pk")[:20]
    )


# Words ---------------------------------------------------------------------------------------


MONTHS = {
    "uz": (
        "yanvar", "fevral", "mart", "aprel", "may", "iyun",
        "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
    ),
    "ru": (
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}  # fmt: skip


def label(row: Deadline) -> str:
    """The period in words, in the active language: "oktabr 2026", "2026, 3-chorak", "2026"."""
    language = (translation.get_language() or "uz")[:2]
    months = MONTHS.get(language, MONTHS["en"])
    if row.rule.period == "month":
        return f"{months[row.period_start.month - 1]} {row.period_start.year}"
    if row.rule.period == "quarter":
        return _("Q%(quarter)s %(year)s") % {
            "quarter": (row.period_start.month - 1) // 3 + 1,
            "year": row.period_start.year,
        }
    return str(row.period_start.year)


ACTION_LABELS = {
    "file_pay": gettext_lazy("File the return and pay"),
    "file": gettext_lazy("File the return"),
    "pay": gettext_lazy("Pay"),
}


def as_dict(row: Deadline, company) -> dict:
    rule = row.rule
    tax = tax_rules.TAXES[rule.tax]
    return {
        "key": row.key,
        "rule": rule.key,
        "tax": rule.tax,
        "tax_name": str(tax.name),
        "name": str(rule.name),
        "period": rule.period,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "period_label": label(row),
        "due_on": row.due_on,
        "action": rule.action,
        "action_label": str(ACTION_LABELS[rule.action]),
        "estimate": quantize(row.estimate) if row.estimate is not None else None,
        "basis": row.basis,
        "booked": row.booked,
        "currency": company.base_currency,
        "status": row.status,
        "done_on": row.done_on,
        "mark_id": row.mark_id,
        "paid": quantize(row.paid) if row.paid is not None else None,
        "transaction_id": row.transaction_id,
        "debt_id": row.debt_id,
        "rule_id": row.rule_id,
        "rate": str(tax.rate) if tax.rate is not None else None,
        "law": rule.law,
        "url": rule.url,
        "confidence": rule.confidence,
        "note": str(rule.note) if rule.note else "",
    }


def calendar_view(company, today: date, *, months_back: int = 1, months_ahead: int = 12) -> dict:
    """The calendar the dashboard shows: deadlines from `months_back` months ago to
    `months_ahead` months ahead, and what decides them."""
    first_year, first_month = _add_months(today.year, today.month, -months_back)
    first = date(first_year, first_month, 1)
    last_year, last_month = _add_months(today.year, today.month, months_ahead)
    last = _month_end(date(last_year, last_month, 1))
    facts = profile(company, today)
    settings_row = conf.get_settings(company)
    rows = deadlines(company, first, last, today=today, facts=facts)
    return {
        "today": today,
        "from": first,
        "to": last,
        "currency": company.base_currency,
        "regime": settings_row.tax_regime,
        "regime_label": str(FinanceSettings.TaxRegime(settings_row.tax_regime).label),
        "profile": {
            "payroll": bool(facts["payroll"]),
            "property": bool(facts["property"]),
            "land": bool(facts["land"]),
            "big_income": bool(facts["big_income"]),
        },
        "remind_days": settings_row.tax_remind_days,
        "warnings": regime_warnings(company, settings_row, facts),
        "deadlines": [as_dict(row, company) for row in rows],
        "checked_on": tax_rules.CHECKED_ON,
        "sources": list(tax_rules.SOURCES),
        "disclaimer": str(WARNING),
    }


def regime_warnings(company, settings_row: FinanceSettings, facts: dict) -> list[str]:
    found = []
    if settings_row.tax_regime == tax_rules.TURNOVER and facts["sells_medicines"]:
        found.append(
            _(
                "Since 1 April 2025 a business that sells medicines can't pay turnover tax (Tax "
                "Code art. 461, part 2, item 14): VAT and profit tax, or the simplified 6 % VAT."
            )
        )
    return found


# Reminders (at the company's morning hour, `deadline_reminders`) ----------------------------


def recipients(company) -> list[Membership]:
    """The people who manage the whole company's money."""
    from apps.members import scope
    from apps.members.queries import members_with_perm

    people = members_with_perm(company, Perm.FINANCE_MANAGE).select_related("user", "role")
    return [person for person in people if scope.branch_ids(person) is None]


def remind(company, today: date) -> int:
    """Each deadline `tax_remind_days` days before and on its day, unless done or a recurring
    tax bill already reminds of it; an overdue one the day after. Returns how many sent."""
    from apps.inbox.services import notify

    days_before = conf.get_settings(company).tax_remind_days
    days = sorted({today, today + timedelta(days=days_before), today - timedelta(days=1)})
    rows = [
        row
        for row in deadlines(company, days[0], days[-1], today=today)
        if row.due_on in days and row.status != "done" and row.rule_id is None
    ]
    if not rows:
        return 0
    people = recipients(company)
    if not people:
        return 0
    sent = 0
    for row in rows:
        made = notify(
            people,
            NOTIFICATION,
            title=lambda person, row=row: reminder_title(row, today, company, person),
            body=lambda person, row=row: reminder_body(row, company, person),
            url=f"/c/{company.pk}/finance/taxes?deadline={row.key}",
            dedupe_key=f"finance:tax:{row.key}:{today.isoformat()}",
            severity="warning" if row.due_on < today else None,
        )
        sent += len(made)
    return sent


def reminder_title(row: Deadline, today: date, company, person: Membership) -> str:
    from apps.finance.reminders import due_text

    with translation.override(person.user.language):
        parts = [f"{tax_rules.TAXES[row.rule.tax].name}, {label(row)}"]
        if row.estimate:
            amount = format_money(row.estimate, company.base_currency, person.user.language or "uz")
            parts.append(f"≈ {amount}" if not row.booked else amount)
        parts.append(due_text(row.due_on, today))
        return " · ".join(parts)


def reminder_body(row: Deadline, company, person: Membership) -> str:
    with translation.override(person.user.language):
        lines = [f"{ACTION_LABELS[row.rule.action]}: {row.rule.name}."]
        if row.basis:
            lines.append(row.basis)
        lines.append(str(WARNING))
        return "\n".join(lines)


# Turnover tax or VAT -------------------------------------------------------------------------


def compare(company, today: date) -> dict:
    """What the last twelve full months would have cost under each regime, from the books."""
    end = today.replace(day=1) - timedelta(days=1)
    year, month = _add_months(end.year, end.month, -11)
    start = date(year, month, 1)
    settings_row = conf.get_settings(company)
    figures = books(company, start, end)
    currency = company.base_currency
    income = figures["income"]
    vat_rate = tax_rules.TAXES["vat"].rate
    profit_rate = tax_rules.TAXES["profit"].rate
    simple_rate = tax_rules.TAXES["vat_simplified"].rate
    turnover_rate = settings_row.turnover_tax_percent
    output = vat_part(income, vat_rate)
    credit = vat_part(figures["goods"], vat_rate)
    vat_due = max(output - credit, ZERO)
    profit_base = income - figures["expense"] + figures["taxes"] - (output - credit)
    profit_tax = quantize(max(profit_base, ZERO) * profit_rate / HUNDRED)
    threshold, unit, threshold_law = tax_rules.turnover_threshold(today)
    if settings_row.turnover_threshold and settings_row.base_value and unit == "base_values":
        threshold = quantize(Decimal(settings_row.turnover_threshold) * settings_row.base_value)
    facts = {"sells_medicines": sells_medicines(company)}
    turnover_blocked = ""
    if facts["sells_medicines"]:
        turnover_blocked = _(
            "Not for a business that sells medicines (Tax Code art. 461, part 2, item 14)."
        )
    elif income > threshold:
        turnover_blocked = _("Income is over the threshold: VAT is due from the day it is reached.")
    options = [
        {
            "regime": tax_rules.TURNOVER,
            "label": str(FinanceSettings.TaxRegime.TURNOVER.label),
            "total": quantize(income * turnover_rate / HUNDRED),
            "parts": [
                {
                    "name": str(tax_rules.TAXES["turnover"].name),
                    "amount": quantize(income * turnover_rate / HUNDRED),
                    "formula": _("%(rate)s %% × income %(income)s")
                    % {"rate": _number(turnover_rate), "income": _money_text(income, currency)},
                }
            ],
            "available": not turnover_blocked,
            "why_not": turnover_blocked,
            "law": "Tax Code arts. 461, 467",
        },
        {
            "regime": tax_rules.VAT,
            "label": str(FinanceSettings.TaxRegime.VAT.label),
            "total": quantize(vat_due + profit_tax),
            "parts": [
                {
                    "name": str(tax_rules.TAXES["vat"].name),
                    "amount": quantize(vat_due),
                    "formula": _(
                        "%(rate)s/%(gross)s of sales %(income)s less %(rate)s/%(gross)s of goods "
                        "bought %(goods)s"
                    )
                    % {
                        "rate": _number(vat_rate),
                        "gross": _number(HUNDRED + vat_rate),
                        "income": _money_text(income, currency),
                        "goods": _money_text(figures["goods"], currency),
                    },
                },
                {
                    "name": str(tax_rules.TAXES["profit"].name),
                    "amount": profit_tax,
                    "formula": _("%(rate)s %% × profit before taxes %(profit)s")
                    % {
                        "rate": _number(profit_rate),
                        "profit": _money_text(max(profit_base, ZERO), currency),
                    },
                },
            ],
            "available": True,
            "why_not": "",
            "law": "Tax Code arts. 258, 337",
        },
        {
            "regime": tax_rules.VAT_SIMPLIFIED,
            "label": str(FinanceSettings.TaxRegime.VAT_SIMPLIFIED.label),
            "total": vat_part(income, simple_rate),
            "parts": [
                {
                    "name": str(tax_rules.TAXES["vat_simplified"].name),
                    "amount": vat_part(income, simple_rate),
                    "formula": _(
                        "%(rate)s/%(gross)s of sales %(income)s, no VAT credit, no profit tax"
                    )
                    % {
                        "rate": _number(simple_rate),
                        "gross": _number(HUNDRED + simple_rate),
                        "income": _money_text(income, currency),
                    },
                }
            ],
            "available": today < date(2030, 1, 1) and today >= date(2026, 6, 1),
            "why_not": "",
            "law": "Decree UP-100, items 5–6",
        },
    ]
    available = [row for row in options if row["available"]]
    cheapest = (
        min(available, key=lambda row: row["total"])["regime"] if available and income else None
    )
    for row in options:
        row["current"] = row["regime"] == settings_row.tax_regime
        row["cheapest"] = row["regime"] == cheapest
    days = (end - start).days + 1
    return {
        "from": start,
        "to": end,
        "days": days,
        "currency": currency,
        "income": income,
        "goods": figures["goods"],
        "expense": figures["expense"],
        "profit": quantize(income - figures["expense"] + figures["taxes"]),
        "enough": queries.posted_rows(company, branch_ids=None)
        .filter(occurred_on__lte=start + timedelta(days=60))
        .exists(),
        "threshold": threshold,
        "threshold_law": threshold_law,
        "over_threshold": income > threshold,
        "regime": settings_row.tax_regime,
        "options": options,
        "assumptions": [
            _("Prices include VAT, and every purchase of goods comes with a VAT invoice."),
            _("Payroll, property and land taxes are the same under every regime and left out."),
            _("Taxes booked as expenses are added back to the profit."),
        ],
        "disclaimer": str(WARNING),
    }
