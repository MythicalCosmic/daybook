"""Read functions of business contracts, for the owner endpoints, the registries and the AI.

Branch scope (docs/PLAN-OWNER.md §2.6): a contract of a branch is seen by whoever sees that
branch; a company-wide one (no branch) only with every branch in sight. Query functions take
`branch_ids` as a required keyword.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Q, QuerySet

from apps.contracts import conf, services
from apps.contracts.models import BusinessContract
from apps.core.money import quantize
from apps.members import scope

ZERO = Decimal(0)
RECURRING_SOURCE = "finance.recurring"
# A month's share of one payment, by period (the "costs a month" figure).
PER_MONTH = {
    BusinessContract.Period.MONTHLY: Decimal(1),
    BusinessContract.Period.QUARTERLY: Decimal(1) / Decimal(3),
    BusinessContract.Period.YEARLY: Decimal(1) / Decimal(12),
}
RELATIONS = ("company", "branch", "counterparty", "responsible", "rule")


def scoped(company, *, branch_ids) -> QuerySet[BusinessContract]:
    return scope.restrict(BusinessContract.objects.for_company(company), branch_ids)


def visible(member) -> QuerySet[BusinessContract]:
    return scoped(member.company, branch_ids=scope.branch_ids(member))


def attention(company, *, branch_ids, today: date) -> list[BusinessContract]:
    """Contracts in force that end within the warning days or whose renewal decision is due,
    soonest first."""
    settings = conf.get_settings(company)
    rows = (
        scoped(company, branch_ids=branch_ids)
        .filter(status__in=BusinessContract.IN_FORCE, ends_on__isnull=False)
        .select_related(*RELATIONS)
    )
    found = [row for row in rows if services.needs_attention(row, today, settings)]
    return sorted(found, key=lambda row: (key_day(row) or row.ends_on, row.title))


def attention_count(member) -> int:
    """The sidebar badge: what needs a look in the caller's scope."""
    company = member.company
    return len(
        attention(company, branch_ids=scope.branch_ids(member), today=services.local_today(company))
    )


def key_day(contract: BusinessContract) -> date | None:
    """The next date that matters: the notice deadline of an auto-renewing contract while it
    is ahead, else the end."""
    deadline = contract.notice_deadline
    if deadline is not None and contract.renewal_confirmed_for != contract.ends_on:
        return deadline
    return contract.ends_on


def per_month(contract: BusinessContract) -> Decimal | None:
    """What it costs a month in its own currency (None: no amount, or paid once)."""
    share = PER_MONTH.get(contract.period)
    if share is None or not contract.amount:
        return None
    return quantize(contract.amount * share)


def summary(company, *, branch_ids, today: date) -> dict:
    """The counts the list's chips show and what contracts in force cost a month, in the
    base currency (foreign amounts at today's rate; left out without one)."""
    from apps.finance import queries as finance

    settings = conf.get_settings(company)
    rows = list(scoped(company, branch_ids=branch_ids).select_related("company"))
    value = finance.valuation(company, today)
    counts = dict.fromkeys(BusinessContract.Status.values, 0)
    monthly = ZERO
    unpriced = 0
    ending = notice = 0
    for row in rows:
        counts[row.status] += 1
        if row.status not in BusinessContract.IN_FORCE:
            continue
        ending += services.ends_soon(row, today, settings.remind_days)
        notice += services.notice_due(row, today, settings.notice_remind_days)
        share = per_month(row)
        if share is None:
            continue
        base = value.to_base(share, row.currency)
        if base is None:
            unpriced += 1
        else:
            monthly += base
    return {
        "today": today,
        "counts": counts,
        "total": len(rows),
        "in_force": counts["active"] + counts["ending"],
        "ending_soon": ending,
        "notice_due": notice,
        "monthly_cost": quantize(monthly),
        "currency": company.base_currency,
        "unpriced": unpriced,
        "remind_days": settings.remind_days,
        "notice_remind_days": settings.notice_remind_days,
    }


def payments(contract: BusinessContract, *, branch_ids, today: date, limit: int = 50) -> dict:
    """What was paid under the contract: the ledger rows of its recurring payment, and the
    money that went to its counterparty while it was in force (on its branch or on none), in
    the caller's scope, newest first; with the totals in the base currency and the next bill."""
    from apps.finance import recurring
    from apps.finance.models import Transaction

    company = contract.company
    rows = Transaction.objects.for_company(company).filter(status=Transaction.Status.POSTED)
    match = Q(pk__in=[])
    if contract.rule_id is not None:
        match |= Q(source_type=RECURRING_SOURCE, source_id=contract.rule_id)
    if contract.counterparty_id is not None and contract.starts_on is not None:
        party = Q(
            counterparty_id=contract.counterparty_id,
            occurred_on__gte=contract.starts_on,
            occurred_on__lte=min(contract.ends_on or today, today),
            kind__in=(Transaction.Kind.EXPENSE, Transaction.Kind.DEBT_PAYMENT),
            amount__lt=0,
        )
        if contract.branch_id is not None:
            party &= Q(branch_id=contract.branch_id) | Q(branch__isnull=True)
        match |= party
    rows = scope.restrict(rows.filter(match), branch_ids).select_related("account")
    total = this_year = ZERO
    items = []
    last_paid = None
    count = 0
    for row in rows.order_by("-occurred_on", "-pk"):
        count += 1
        total += -row.base_amount
        if row.occurred_on.year == today.year:
            this_year += -row.base_amount
        last_paid = last_paid or row.occurred_on
        if len(items) < limit:
            items.append(
                {
                    "id": row.pk,
                    "occurred_on": row.occurred_on,
                    "amount": quantize(-row.amount),
                    "currency": row.currency,
                    "base_amount": quantize(-row.base_amount),
                    "description": row.description,
                    "account": row.account.name if row.account_id else None,
                    "by_rule": row.source_type == RECURRING_SOURCE
                    and row.source_id == contract.rule_id,
                }
            )
    rule = contract.rule if contract.rule_id is not None else None
    next_bill = None
    if rule is not None and rule.is_active and rule.next_due_on is not None:
        next_bill = {
            "due_on": recurring.due_on(rule),
            "amount": quantize(rule.amount),
            "currency": rule.currency,
        }
    return {
        "items": items,
        "count": count,
        "total": quantize(total),
        "this_year": quantize(this_year),
        "currency": company.base_currency,
        "last_paid_on": last_paid,
        "next": next_bill,
    }


def dates(contract: BusinessContract, today: date) -> list[dict]:
    """The contract's dates in order, for its timeline: signed, starts, renewed, notice
    deadline, ends (or terminated), each marked past or ahead."""
    found = []

    def add(key: str, day: date | None) -> None:
        if day is not None:
            found.append({"key": key, "day": day, "past": day < today})

    add("signed", contract.signed_on)
    add("starts", contract.starts_on)
    add("renewed", contract.last_renewed_on)
    if contract.status in BusinessContract.IN_FORCE:
        add("notice", contract.notice_deadline)
    if contract.terminated_on is not None:
        add("terminated", contract.terminated_on)
    elif contract.auto_renews and contract.status in BusinessContract.IN_FORCE:
        add("renews", contract.ends_on)
    else:
        add("ends", contract.ends_on)
    order = {"signed": 0, "starts": 1, "renewed": 2, "notice": 3}
    return sorted(found, key=lambda item: (item["day"], order.get(item["key"], 9)))
