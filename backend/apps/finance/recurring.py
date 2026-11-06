"""Recurring payments (Package I, docs/PLAN-OWNER.md §1.6, §3.7, §10.1): bills that come back
(rent, utilities, internet, taxes) and automatic posts, through the ledger services.

The schedule: occurrences follow `frequency` times `interval` from `starts_on`, on `day` (a weekday
1-7 for weekly rules, else a day of the month; 31 means the month's last day). An occurrence on a
company holiday (`timeoff.Holiday`) moves to the working day before or after (`on_holiday`).
`RecurringRule.next_due_on` holds the *scheduled* day of the open occurrence; `due_on(rule)` is
the day it is due after the holiday move.

What an occurrence books is keyed by its scheduled day (`Source("finance.recurring", rule, day)`),
so it is idempotent per due date: a retried job, two people pressing "Paid" at once, or a run
right after a manual post never book twice.

- A **bill** stays open until someone pays it (`pay_occurrence`, with the real amount; for an
  amount that varies, the paid amount becomes the next estimate) or skips it.
- An **auto** rule posts itself on its due day (`run_due`, every 30 minutes) on its account.

A tax-calendar bill (`template_key` "tax.…") paid while the tax office has open tax payables
(payroll books the income tax and social tax it withholds as such debts) settles those first,
oldest first, so the tax is never counted twice; only the rest is booked as an expense.
"""

import logging
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.finance import conf, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    Category,
    Counterparty,
    Debt,
    MoneyAccount,
    RecurringRule,
    Transaction,
)
from apps.finance.sources import Source
from apps.members.models import Membership

logger = logging.getLogger(__name__)

SOURCE = "finance.recurring"
Frequency = RecurringRule.Frequency
Mode = RecurringRule.Mode
OnHoliday = RecurringRule.OnHoliday
STEP_MONTHS = {Frequency.MONTHLY: 1, Frequency.QUARTERLY: 3, Frequency.YEARLY: 12}
# A holiday move looks at most this many days away (a long Navruz break with a weekend).
MAX_SHIFT = 14
# An auto rule catches up at most this many missed occurrences per run.
MAX_CATCH_UP = 12
ZERO = Decimal(0)
RULE_FIELDS = (
    "name",
    "kind",
    "mode",
    "frequency",
    "interval",
    "day",
    "on_holiday",
    "category",
    "counterparty",
    "account",
    "branch",
    "amount",
    "amount_varies",
    "starts_on",
    "ends_on",
    "remind_days_before",
    "payer",
    "is_active",
)
SCHEDULE_FIELDS = ("frequency", "interval", "day", "starts_on", "ends_on")


# The schedule ---------------------------------------------------------------------------------


def _month_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, monthrange(year, month)[1]))


def scheduled_after(rule: RecurringRule, after: date | None) -> date | None:
    """The first scheduled day of `rule` that is on or after `starts_on` and after `after`
    (the very first one when `after` is None); None once that would pass `ends_on`."""
    start = rule.starts_on
    if rule.frequency == Frequency.WEEKLY:
        first = start + timedelta(days=(rule.day - 1 - start.weekday()) % 7)
        step = 7 * rule.interval
        if after is None or after < first:
            candidate = first
        else:
            candidate = first + timedelta(days=((after - first).days // step + 1) * step)
    else:
        step = STEP_MONTHS[rule.frequency] * rule.interval
        anchor = start.year * 12 + start.month - 1

        def at(k: int) -> date:
            month = anchor + k * step
            return _month_day(month // 12, month % 12 + 1, rule.day)

        k = 1 if at(0) < start else 0
        if after is not None:
            k = max(k, (after.year * 12 + after.month - 1 - anchor) // step)
            while at(k) <= after:
                k += 1
        candidate = at(k)
    if rule.ends_on is not None and candidate > rule.ends_on:
        return None
    return candidate


def holidays(company, start: date, end: date) -> set[date]:
    """The company's holidays from `start` to `end`, with room for holiday moves."""
    from apps.timeoff.queries import holidays_between

    rows = holidays_between(
        company, start - timedelta(days=MAX_SHIFT), end + timedelta(days=MAX_SHIFT)
    )
    return set(rows.values_list("date", flat=True))


def shift(day: date, on_holiday: str, days_off: set[date]) -> date:
    """`day` moved off the company's holidays: to the working day before or after."""
    if on_holiday == OnHoliday.KEEP or day not in days_off:
        return day
    step = timedelta(days=-1 if on_holiday == OnHoliday.BEFORE else 1)
    moved = day
    for _attempt in range(MAX_SHIFT):
        moved += step
        if moved not in days_off:
            return moved
    return day


def due_on(rule: RecurringRule, days_off: set[date] | None = None) -> date | None:
    """The day the open occurrence is due, after the holiday move (None once the rule ended)."""
    if rule.next_due_on is None:
        return None
    if days_off is None:
        days_off = holidays(rule.company, rule.next_due_on, rule.next_due_on)
    return shift(rule.next_due_on, rule.on_holiday, days_off)


@dataclass(frozen=True)
class Occurrence:
    rule: RecurringRule
    scheduled: date
    due: date


def occurrences(
    rule: RecurringRule, until: date, days_off: set[date], *, limit: int = 400
) -> list[Occurrence]:
    """The open occurrence and the ones after it that are due on or before `until`."""
    found: list[Occurrence] = []
    scheduled = rule.next_due_on
    while scheduled is not None and len(found) < limit:
        due = shift(scheduled, rule.on_holiday, days_off)
        if due > until:
            break
        found.append(Occurrence(rule, scheduled, due))
        scheduled = scheduled_after(rule, scheduled)
    return found


def next_dates(rule: RecurringRule, count: int, days_off: set[date] | None = None) -> list[date]:
    """The next `count` due days (after holiday moves), the open occurrence first."""
    if rule.next_due_on is None:
        return []
    scheduled_days = []
    scheduled = rule.next_due_on
    while scheduled is not None and len(scheduled_days) < count:
        scheduled_days.append(scheduled)
        scheduled = scheduled_after(rule, scheduled)
    if days_off is None:
        days_off = holidays(rule.company, scheduled_days[0], scheduled_days[-1])
    return [shift(day, rule.on_holiday, days_off) for day in scheduled_days]


def first_open(rule: RecurringRule, today: date) -> date | None:
    """The first scheduled day on or after today and after the last settled occurrence."""
    after = today - timedelta(days=1)
    if rule.last_done_on is not None and rule.last_done_on > after:
        after = rule.last_done_on
    if rule.starts_on > after:
        after = rule.starts_on - timedelta(days=1)
    return scheduled_after(rule, after)


# Rules ----------------------------------------------------------------------------------------


def create_rule(company, *, by: Membership, **fields) -> RecurringRule:
    """A new recurring payment. Its first occurrence is the first scheduled day from today on
    (an occurrence before today was dealt with before the rule existed)."""
    _known(fields)
    template_key = fields.pop("template_key", "")
    rule = RecurringRule(company=company, created_by=by.user, template_key=template_key)
    with transaction.atomic():
        _apply(rule, fields, by=by, creating=True)
        rule.next_due_on = first_open(rule, _today(company))
        rule.save()
        services._audit(
            FinanceAction.RECURRING_CREATED,
            company,
            by.user,
            rule,
            name=rule.name,
            mode=rule.mode,
            amount=str(rule.amount),
        )
    return rule


def update_rule(rule: RecurringRule, *, by: Membership, **fields) -> RecurringRule:
    """Change a rule. A new schedule starts again from today; switching it back on too."""
    _known(fields)
    fields.pop("template_key", None)
    with transaction.atomic():
        rule = _lock(rule)
        before = _snapshot(rule)
        reschedule = any(
            key in fields and fields[key] != getattr(rule, key) for key in SCHEDULE_FIELDS
        ) or (fields.get("is_active") is True and not rule.is_active)
        _apply(rule, fields, by=by, creating=False)
        if reschedule:
            rule.next_due_on = first_open(rule, _today(rule.company))
        rule.save()
        changes = services._diff(before, _snapshot(rule))
        if changes:
            services._audit(
                FinanceAction.RECURRING_UPDATED, rule.company, by.user, rule, changes=changes
            )
    return rule


def stop_rule(rule: RecurringRule, *, by: Membership) -> RecurringRule:
    """Switch a rule off. What it booked stays in the ledger."""
    with transaction.atomic():
        rule = _lock(rule)
        if rule.is_active:
            rule.is_active = False
            rule.save(update_fields=["is_active", "updated_at"])
            services._audit(FinanceAction.RECURRING_STOPPED, rule.company, by.user, rule)
    return rule


class Settled(DomainError):
    """The occurrence the caller named was paid, posted or skipped meanwhile."""


def _need_occurrence(rule: RecurringRule, occurrence: date | None, message) -> None:
    """A caller that names the occurrence it acts on (a reminder's button, a dialog showing its
    due day, scheduled or after the holiday move) acts on that one only, checked under the
    rule's lock: a second press or a second person never settles the next one as well."""
    if occurrence is None:
        return
    if rule.next_due_on is None or occurrence not in (rule.next_due_on, due_on(rule)):
        raise Settled(message)


def skip_occurrence(
    rule: RecurringRule, *, by: Membership, occurrence: date | None = None
) -> RecurringRule:
    """Leave the open occurrence unpaid and move on to the next one."""
    with transaction.atomic():
        rule = _lock(rule)
        _need_occurrence(rule, occurrence, _("This has already been handled."))
        _need_open(rule)
        skipped = rule.next_due_on
        _advance(rule, skipped)
        services._audit(
            FinanceAction.RECURRING_SKIPPED,
            rule.company,
            by.user,
            rule,
            occurrence=skipped.isoformat(),
        )
    return rule


@dataclass(frozen=True)
class Payment:
    rule: RecurringRule
    rows: list[Transaction]

    @property
    def transaction(self) -> Transaction | None:
        return self.rows[-1] if self.rows else None


def pay_occurrence(
    rule: RecurringRule,
    *,
    by: Membership,
    account: MoneyAccount,
    amount=None,
    paid_on: date | None = None,
    occurrence: date | None = None,
) -> Payment:
    """Pay the open occurrence of a bill from `account` (its usual amount unless given), then
    move on to the next one. With `occurrence` (the due day the person saw), paying it again
    once it is settled is refused (`Settled`) instead of paying the next one."""
    company = rule.company
    paid_on = paid_on or _today(company)
    with transaction.atomic():
        rule = _lock(rule)
        if rule.mode != Mode.BILL:
            raise DomainError(_("This payment is posted automatically: run it instead."))
        _need_occurrence(rule, occurrence, _("Already paid."))
        _need_open(rule)
        value = services._money(amount if amount not in (None, "") else rule.amount)
        scheduled = rule.next_due_on
        key = scheduled.isoformat()
        rows = _settle_tax_debts(rule, by=by, account=account, amount=value, paid_on=paid_on)
        rest = value - sum((row.debt_amount or ZERO) for row in rows)
        if rest > 0:
            rows.append(
                services.record_transaction(
                    company,
                    by=by,
                    kind=rule.kind,
                    amount=rest,
                    occurred_on=paid_on,
                    account=account,
                    category=rule.category,
                    counterparty=rule.counterparty,
                    branch=rule.branch,
                    description=_occurrence_text(rule, scheduled),
                    source=Source(SOURCE, rule.pk, key),
                )
            )
        if rule.amount_varies:
            rule.amount = value  # the next estimate
        _advance(rule, scheduled)
        services._audit(
            FinanceAction.RECURRING_PAID,
            company,
            by.user,
            rule,
            occurrence=key,
            amount=str(value),
            account=account.pk,
            transactions=[row.pk for row in rows],
        )
    return Payment(rule, rows)


def run_now(rule: RecurringRule, *, by: Membership, occurrence: date | None = None) -> Payment:
    """Post the open occurrence of an automatic rule today instead of on its due day."""
    with transaction.atomic():
        rule = _lock(rule)
        if rule.mode != Mode.AUTO:
            raise DomainError(_("A bill is paid with the amount you paid, not run."))
        _need_occurrence(rule, occurrence, _("This has already been handled."))
        _need_open(rule)
        row = _post(rule, rule.next_due_on, _today(rule.company), by=by)
        _advance(rule, rule.next_due_on)
        services._audit(
            FinanceAction.RECURRING_POSTED,
            rule.company,
            by.user,
            rule,
            transaction=row.pk,
            amount=str(row.amount),
        )
    return Payment(rule, [row])


def run_due(now: datetime | None = None) -> int:
    """Every 30 minutes: post the automatic rules whose occurrence is due, on its due day,
    for the companies with the finance module on. Returns how many rows were posted."""
    now = now or timezone.now()
    posted = 0
    candidates = (
        RecurringRule.objects.filter(
            is_active=True,
            mode=Mode.AUTO,
            next_due_on__isnull=False,
            company__features__contains=["finance"],
        )
        .select_related("company")
        .order_by("company_id", "pk")
    )
    for rule in candidates:
        today = timezone.localdate(now, ZoneInfo(rule.company.timezone))
        if rule.next_due_on > today + timedelta(days=MAX_SHIFT):
            continue
        posted += _catch_up(rule, today)
    return posted


def _catch_up(rule: RecurringRule, today: date) -> int:
    posted = 0
    for _attempt in range(MAX_CATCH_UP):
        try:
            with transaction.atomic():
                locked = _lock(rule)
                if not locked.is_active or locked.next_due_on is None:
                    return posted
                due = due_on(locked)
                if due > today:
                    return posted
                _post(locked, locked.next_due_on, due, by=None)
                _advance(locked, locked.next_due_on)
                posted += 1
        except DomainError as error:
            # A closed period or an account without the money: it stays due, shows as overdue
            # in Upcoming and is reminded; the next run tries again.
            logger.info("Recurring rule %s not posted: %s", rule.pk, error)
            return posted
    return posted


def _post(rule: RecurringRule, scheduled: date, occurred_on: date, *, by) -> Transaction:
    if rule.account is None:
        raise DomainError(_("Pick the account it is posted on."))
    return services.record_transaction(
        rule.company,
        by=by,
        kind=rule.kind,
        amount=rule.amount,
        occurred_on=occurred_on,
        account=rule.account,
        category=rule.category,
        counterparty=rule.counterparty,
        branch=rule.branch,
        description=_occurrence_text(rule, scheduled),
        source=Source(SOURCE, rule.pk, scheduled.isoformat()),
    )


def _settle_tax_debts(
    rule: RecurringRule, *, by: Membership, account: MoneyAccount, amount: Decimal, paid_on: date
) -> list[Transaction]:
    """A tax-calendar bill first settles the open tax payables to its counterparty."""
    if not rule.template_key.startswith("tax.") or rule.counterparty_id is None:
        return []
    debts = Debt.objects.filter(
        company=rule.company,
        direction=Debt.Direction.PAYABLE,
        kind=Debt.Kind.TAX,
        status=Debt.Status.OPEN,
        counterparty_id=rule.counterparty_id,
        currency=account.currency,
        locked_by_type="",
        issued_on__lte=paid_on,
    ).order_by("issued_on", "pk")
    rows = []
    left = amount
    for debt in debts:
        if left <= 0:
            break
        part = min(left, debt.amount - debt.paid)
        if part <= 0:
            continue
        rows.append(
            services.pay_debt(
                debt,
                by=by,
                amount=part,
                paid_on=paid_on,
                account=account,
                source=Source(SOURCE, rule.pk, f"{rule.next_due_on.isoformat()}:d{debt.pk}"),
            )
        )
        left -= part
    return rows


def _advance(rule: RecurringRule, settled: date) -> None:
    rule.last_done_on = settled
    rule.next_due_on = scheduled_after(rule, settled)
    rule.last_reminded_on = None
    rule.save(
        update_fields=["last_done_on", "next_due_on", "last_reminded_on", "amount", "updated_at"]
    )


def _need_open(rule: RecurringRule) -> None:
    if not rule.is_active:
        raise DomainError(_("This recurring payment is switched off."))
    if rule.next_due_on is None:
        raise DomainError(_("This recurring payment has ended."))


def _lock(rule: RecurringRule) -> RecurringRule:
    return (
        RecurringRule.objects.select_for_update(of=("self",))
        .select_related("company", "category", "counterparty", "account", "branch")
        .get(pk=rule.pk)
    )


def _occurrence_text(rule: RecurringRule, scheduled: date) -> str:
    return f"{rule.name} · {scheduled:%d.%m.%Y}"[:300]


def _today(company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def _known(fields: dict) -> None:
    unknown = set(fields) - set(RULE_FIELDS) - {"template_key"}
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}.")


def _apply(rule: RecurringRule, fields: dict, *, by: Membership, creating: bool) -> None:
    """Check and set `fields` on `rule` (every rule a rule must keep, whatever changed)."""
    company = rule.company
    for key, value in fields.items():
        if key in ("category", "counterparty", "account", "branch", "payer"):
            services._same_company(company, value)
        setattr(rule, key, value)
    rule.name = (rule.name or "").strip()[:100]
    if not rule.name:
        raise DomainError(_("Give it a name, like Rent."))
    if rule.kind not in Category.Kind.values:
        raise ValueError(f"Unknown kind {rule.kind!r}.")
    if rule.mode not in Mode.values:
        raise ValueError(f"Unknown mode {rule.mode!r}.")
    if rule.frequency not in Frequency.values:
        raise ValueError(f"Unknown frequency {rule.frequency!r}.")
    if rule.on_holiday not in OnHoliday.values:
        raise ValueError(f"Unknown holiday rule {rule.on_holiday!r}.")
    if not isinstance(rule.interval, int) or not 1 <= rule.interval <= 24:
        raise DomainError(_("Repeat every 1 to 24 periods."))
    top_day = 7 if rule.frequency == Frequency.WEEKLY else 31
    if not isinstance(rule.day, int) or not 1 <= rule.day <= top_day:
        if rule.frequency == Frequency.WEEKLY:
            raise DomainError(_("Pick a weekday from 1 (Monday) to 7 (Sunday)."))
        raise DomainError(_("Pick a day of the month from 1 to 31."))
    if not isinstance(rule.remind_days_before, int) or not 0 <= rule.remind_days_before <= 30:
        raise DomainError(_("Remind 0 to 30 days before."))
    if rule.category_id is None:
        raise DomainError(_("Pick a category."))
    category = services._category(company, rule.category, kind=rule.kind, by=by)
    rule.category = category
    if rule.account is not None:
        if creating or "account" in fields:
            services._check_active(rule.account)
        rule.currency = rule.account.currency
    else:
        rule.currency = company.base_currency
    if rule.amount_varies:
        rule.amount = services._money(rule.amount or 0, allow_zero=True)
    else:
        rule.amount = services._money(rule.amount if rule.amount is not None else 0)
    if rule.mode == Mode.AUTO:
        if rule.account is None:
            raise DomainError(_("An automatic payment needs the account it is posted on."))
        if rule.amount_varies:
            raise DomainError(_("An automatic payment needs a fixed amount."))
    if rule.starts_on is None:
        raise DomainError(_("Pick the day it starts."))
    if rule.ends_on is not None and rule.ends_on < rule.starts_on:
        raise DomainError(_("It can't end before it starts."))
    if rule.payer is not None and rule.payer.status != Membership.Status.APPROVED:
        raise DomainError(_("Pick someone who works here."))


def _snapshot(rule: RecurringRule) -> dict:
    return {
        "name": rule.name,
        "kind": rule.kind,
        "mode": rule.mode,
        "frequency": rule.frequency,
        "interval": rule.interval,
        "day": rule.day,
        "on_holiday": rule.on_holiday,
        "category": rule.category_id,
        "counterparty": rule.counterparty_id,
        "account": rule.account_id,
        "branch": rule.branch_id,
        "amount": str(quantize(rule.amount)),
        "amount_varies": rule.amount_varies,
        "starts_on": rule.starts_on.isoformat() if rule.starts_on else None,
        "ends_on": rule.ends_on.isoformat() if rule.ends_on else None,
        "remind_days_before": rule.remind_days_before,
        "payer": rule.payer_id,
        "is_active": rule.is_active,
    }


# Queries --------------------------------------------------------------------------------------


def visible_rules(company, *, branch_ids):
    """Rules in the member's branch scope (a rule without a branch only for every branch)."""
    rows = RecurringRule.objects.for_company(company)
    if branch_ids is None:
        return rows
    return rows.filter(branch_id__in=branch_ids)


def due_items(company, today: date, until: date, *, branch_ids) -> list[Occurrence]:
    """Open occurrences of active rules due on or before `until` (overdue bills included)."""
    rules = list(
        visible_rules(company, branch_ids=branch_ids)
        .filter(is_active=True, next_due_on__isnull=False)
        .filter(Q(next_due_on__lte=until + timedelta(days=MAX_SHIFT)))
        .select_related("category", "counterparty", "account", "branch", "company")
    )
    if not rules:
        return []
    start = min(rule.next_due_on for rule in rules)
    days_off = holidays(company, min(start, today), until)
    found: list[Occurrence] = []
    for rule in rules:
        found.extend(occurrences(rule, until, days_off))
    found.sort(key=lambda item: (item.due, item.rule.name, item.rule.pk))
    return found


def tax_office(company, *, by: Membership | None) -> Counterparty:
    """The tax office counterparty (the same one payroll books its tax debts to)."""
    from django.utils import translation

    with translation.override(company.default_language or "uz"):
        name = _("Tax office")
    found = (
        Counterparty.objects.for_company(company)
        .filter(kind=Counterparty.Kind.STATE, name=name)
        .first()
    )
    if found is not None:
        return found
    if by is None:
        raise DomainError(_("Add the tax office to the counterparties first."))
    return services.create_counterparty(company, by=by, name=name, kind=Counterparty.Kind.STATE)


def settings_for(company):
    return conf.get_settings(company)
