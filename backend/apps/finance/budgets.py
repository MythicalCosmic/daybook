"""Budgets against actual spending (Package I, §1.6): an amount per expense category and month,
80 % and 100 % alerts once per threshold and month, and "copy last month".

Actuals are the P&L's numbers (`queries.totals` basis): posted expense, write-off and exchange
rows by category, a parent category counting its own rows and its children's. So whatever the
P&L counts (depreciation too, once the ledger books it) shows in budgets the same way.

Budgets are company-wide. A member who sees only some branches sees the actuals of those
branches, so no other branch's spending leaks; alerts go to the people who see every branch.
"""

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import format_money, quantize
from apps.finance import queries, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import Budget, Category
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
WARNING = Decimal("0.80")
OVER = Decimal("1.00")
SHARE_STEP = Decimal("0.01")


def month_start(day: date) -> date:
    return day.replace(day=1)


def parse_month(value: str) -> date:
    try:
        year, month = (int(part) for part in value.split("-"))
        return date(year, month, 1)
    except TypeError, ValueError, AttributeError:
        raise DomainError(_("Give a month as YYYY-MM.")) from None


def previous_month(month: date) -> date:
    return (month.replace(day=1) - timedelta(days=1)).replace(day=1)


def month_end(month: date) -> date:
    return month.replace(day=monthrange(month.year, month.month)[1])


def actuals(company, month: date, *, branch_ids) -> dict[int, Decimal]:
    """{category id: spent in the month}, a parent with its children's spending added."""
    rows = (
        queries.posted_rows(company, branch_ids=branch_ids)
        .filter(
            kind__in=queries.PNL_KINDS,
            capitalized=False,  # bought as an asset: its depreciation counts instead
            category__kind=Category.Kind.EXPENSE,
            occurred_on__range=(month, month_end(month)),
        )
        .values("category_id", "category__parent_id")
        .annotate(total=Sum("base_amount"))
        .order_by()
    )
    spent: dict[int, Decimal] = {}
    for row in rows:
        amount = -(row["total"] or ZERO)
        for pk in (row["category_id"], row["category__parent_id"]):
            if pk is not None:
                spent[pk] = spent.get(pk, ZERO) + amount
    return {pk: quantize(amount) for pk, amount in spent.items()}


def status_of(budget: Decimal | None, actual: Decimal) -> tuple[Decimal | None, str]:
    if budget is None or budget <= 0:
        return None, "none"
    share = (actual / budget).quantize(SHARE_STEP)
    if share >= OVER:
        return share, "over"
    if share >= WARNING:
        return share, "warning"
    return share, "ok"


def month_view(company, month: date, *, branch_ids, today: date) -> dict:
    """Every active expense category (and any category with a budget) with its budget, actual,
    share of the budget used and status ("none", "ok", "warning" at 80 %, "over" at 100 %)."""
    budgets = {
        row.category_id: row
        for row in Budget.objects.filter(company=company, month=month).select_related("category")
    }
    categories = (
        Category.objects.for_company(company)
        .filter(kind=Category.Kind.EXPENSE)
        .filter(Q(is_active=True) | Q(pk__in=list(budgets)))
        .select_related("parent")
        .order_by("order", "name")
    )
    spent = actuals(company, month, branch_ids=branch_ids)
    parents = [category for category in categories if category.parent_id is None]
    children: dict[int, list[Category]] = {}
    for category in categories:
        if category.parent_id is not None:
            children.setdefault(category.parent_id, []).append(category)
    rows = []
    total_budget = total_actual = ZERO
    for parent in parents:
        for category in (parent, *children.get(parent.pk, [])):
            budget = budgets.get(category.pk)
            amount = budget.amount if budget is not None else None
            actual = spent.get(category.pk, ZERO)
            share, state = status_of(amount, actual)
            if category.parent_id is None:
                total_actual += actual
                if amount is not None:
                    total_budget += amount
            elif amount is not None and parent.pk not in budgets:
                total_budget += amount  # a child's budget counts when its parent has none
            rows.append(
                {
                    "category": {
                        "id": category.pk,
                        "name": category.name,
                        "kind": category.kind,
                        "color": category.color,
                        "parent_id": category.parent_id,
                        "parent_name": category.parent.name if category.parent_id else None,
                    },
                    "budget": str(amount) if amount is not None else None,
                    "actual": str(actual),
                    "share": str(share) if share is not None else None,
                    "status": state,
                }
            )
    last = month_end(month)
    if month_start(today) == month:
        days_left = (last - today).days + 1
    else:
        days_left = last.day if month > today else 0
    return {
        "month": f"{month:%Y-%m}",
        "currency": company.base_currency,
        "days_left": days_left,
        "days_in_month": last.day,
        "rows": rows,
        "totals": {"budget": str(quantize(total_budget)), "actual": str(quantize(total_actual))},
    }


@transaction.atomic
def set_budgets(company, *, by: Membership, month: date, rows) -> int:
    """Set (amount) or remove (None) the budgets of `month`; returns how many changed. A budget
    lowered or raised past a threshold may alert again; the check runs after commit."""
    services._need_actor(by)
    user = services._actor(company, by)
    month = month_start(month)
    changes = {}
    for category, amount in rows:
        services._same_company(company, category)
        if category.kind != Category.Kind.EXPENSE:
            raise DomainError(_("Budgets are set on expense categories."))
        current = (
            Budget.objects.select_for_update()
            .filter(company=company, month=month, category=category)
            .first()
        )
        if amount in (None, ""):
            if current is not None:
                changes[category.pk] = [str(current.amount), None]
                current.delete()
            continue
        value = services._money(amount)
        if current is None:
            Budget.objects.create(
                company=company, month=month, category=category, amount=value, created_by=user
            )
            changes[category.pk] = [None, str(value)]
        elif current.amount != value:
            changes[category.pk] = [str(current.amount), str(value)]
            current.amount = value
            # A new amount is a new budget: its thresholds may alert again.
            current.alerted_80_at = None
            current.alerted_100_at = None
            current.save(update_fields=["amount", "alerted_80_at", "alerted_100_at", "updated_at"])
    if changes:
        services._audit(
            FinanceAction.BUDGETS_SET,
            company,
            user,
            services.get_settings(company),
            month=f"{month:%Y-%m}",
            changes={str(pk): value for pk, value in changes.items()},
        )
        _check_later(company, month)
    return len(changes)


@transaction.atomic
def copy_budgets(company, *, by: Membership, month: date) -> int:
    """Copy the previous month's budgets into `month`, for categories without one yet."""
    services._need_actor(by)
    user = services._actor(company, by)
    month = month_start(month)
    source = previous_month(month)
    have = set(
        Budget.objects.filter(company=company, month=month).values_list("category_id", flat=True)
    )
    made = [
        Budget(
            company=company,
            month=month,
            category_id=row.category_id,
            amount=row.amount,
            created_by=user,
        )
        for row in Budget.objects.filter(company=company, month=source, category__is_active=True)
        if row.category_id not in have
    ]
    Budget.objects.bulk_create(made)
    if made:
        services._audit(
            FinanceAction.BUDGETS_COPIED,
            company,
            user,
            services.get_settings(company),
            month=f"{month:%Y-%m}",
            source=f"{source:%Y-%m}",
            count=len(made),
        )
        _check_later(company, month)
    return len(made)


# Alerts ---------------------------------------------------------------------------------------


def watch(row) -> None:
    """After a P&L row posts in a budgeted category, check that month's budgets on commit
    (called by the ledger services)."""
    category = row.category
    if category is None or category.kind != Category.Kind.EXPENSE:
        return
    month = month_start(row.occurred_on)
    ids = [pk for pk in (category.pk, category.parent_id) if pk is not None]
    if Budget.objects.filter(company_id=row.company_id, month=month, category_id__in=ids).exists():
        _check_later(row.company, month)


def _check_later(company, month: date) -> None:
    from apps.finance import tasks  # tasks never import this module

    transaction.on_commit(lambda: tasks.check_budgets.delay(company.pk, month.isoformat()))


def check(company, month: date, now: datetime | None = None) -> int:
    """Send the 80 % and 100 % alerts of `month` that are due, once each; returns how many
    budgets alerted. Reaching 100 % at once sends only the 100 % alert."""
    if not company.has_feature("finance"):
        return 0
    now = now or timezone.now()
    today = timezone.localdate(now, ZoneInfo(company.timezone))
    spent = actuals(company, month, branch_ids=None)
    alerted = 0
    for budget in Budget.objects.filter(company=company, month=month).select_related("category"):
        share, state = status_of(budget.amount, spent.get(budget.category_id, ZERO))
        level = None
        with transaction.atomic():
            locked = Budget.objects.select_for_update().get(pk=budget.pk)
            if state == "over" and locked.alerted_100_at is None:
                level = 100
                locked.alerted_100_at = now
                locked.alerted_80_at = locked.alerted_80_at or now
            elif state in ("over", "warning") and locked.alerted_80_at is None:
                level = 80
                locked.alerted_80_at = now
            if level is not None:
                locked.save(update_fields=["alerted_80_at", "alerted_100_at", "updated_at"])
                _notify(company, locked, share, month, today)
                alerted += 1
    return alerted


def check_all(now: datetime | None = None) -> int:
    """Daily 03:30: this month's budgets of every company with the finance module on."""
    now = now or timezone.now()
    from apps.companies.models import Company

    total = 0
    companies = Company.objects.filter(
        features__contains=["finance"], finance_budgets__isnull=False
    ).distinct()
    for company in companies:
        month = month_start(timezone.localdate(now, ZoneInfo(company.timezone)))
        try:
            total += check(company, month, now)
        except Exception:  # one company's trouble never stops the others
            logger.exception("Budget check failed for company %s", company.pk)
    return total


def recipients(company) -> list[Membership]:
    """finance.manage holders who see every branch (budgets are company-wide)."""
    from apps.members.queries import members_with_perm

    people = members_with_perm(company, Perm.FINANCE_MANAGE).select_related("user", "role")
    return [person for person in people if scope.branch_ids(person) is None]


def _notify(company, budget: Budget, share: Decimal, month: date, today: date) -> None:
    from apps.inbox.services import notify

    people = recipients(company)
    if not people:
        return
    left = max((month_end(month) - today).days + 1, 0) if month_start(today) == month else 0
    percent = int((share * 100).to_integral_value()) if share is not None else 0

    def title(person: Membership) -> str:
        with translation.override(person.user.language):
            return budget_title(budget.category.name, percent, month, left)

    def body(person: Membership) -> str:
        with translation.override(person.user.language):
            return _("Budget %(budget)s.") % {
                "budget": format_money(
                    budget.amount, company.base_currency, (person.user.language or "uz")[:2]
                )
            }

    notify(
        people,
        "finance.budget",
        title=title,
        body=body,
        url=f"/c/{company.pk}/finance/budgets?month={month:%Y-%m}",
        target=budget,
        severity="warning" if percent < 100 else "critical",
        # A new amount is a new budget, so its alerts may come again.
        dedupe_key=f"finance:budget:{budget.pk}:{100 if percent >= 100 else 80}:{budget.amount}",
    )


def budget_title(category: str, percent: int, month: date, days_left: int) -> str:
    month_name = date_format(month, "F")
    if days_left > 0:
        return _("%(category)s: %(percent)s%% of the %(month)s budget used, %(days)s days left") % {
            "category": category,
            "percent": percent,
            "month": month_name,
            "days": days_left,
        }
    return _("%(category)s: %(percent)s%% of the %(month)s budget used") % {
        "category": category,
        "percent": percent,
        "month": month_name,
    }
