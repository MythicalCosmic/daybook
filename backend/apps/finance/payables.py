"""Paying distributors (Package I, §14.8): the open payables owed to counterparties, grouped by
distributor and due date (overdue, this week, later), paid several at once from one account.

Each debt is paid with `services.pay_debt` (one ledger row and one audit row per debt); the
whole batch is one transaction, so either every debt is paid or none is. Wholesale of marked
goods is paid by bank transfer only (§14.4 row 25): a goods-receipt payable paid from a cash
desk, a safe, an employee's or the owner's money gets a warning (it isn't refused: the law is
the company's to follow, and a correction must stay possible).
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError
from apps.core.money import quantize
from apps.finance import queries, services
from apps.finance.models import Debt, MoneyAccount, Transaction
from apps.members.models import Membership

ZERO = Decimal(0)
GOODS_RECEIPT = "inventory.goodsreceipt"
CASH_KINDS = (
    MoneyAccount.Kind.CASH,
    MoneyAccount.Kind.SAFE,
    MoneyAccount.Kind.EMPLOYEE,
    MoneyAccount.Kind.OWNER,
)
WEEK = 7


def bank_only(debt: Debt) -> bool:
    """A payable for goods received against a distributor's invoice (J1's goods receipts)."""
    return debt.source_type == GOODS_RECEIPT


def bucket(debt: Debt, today: date) -> str:
    if debt.due_on is not None and debt.due_on < today:
        return "overdue"
    if debt.due_on is None or debt.due_on <= today + timedelta(days=WEEK):
        return "week"
    return "later"


def open_payables(company, *, branch_ids):
    return (
        queries.scoped_debts(company, branch_ids=branch_ids)
        .filter(
            direction=Debt.Direction.PAYABLE,
            status=Debt.Status.OPEN,
            counterparty__isnull=False,
        )
        .select_related("counterparty", "branch", "responsible", "company")
    )


def grouped(debts: list[Debt], today: date) -> dict:
    """{groups: [{counterparty, total, overdue, debts}], totals} in the base currency."""
    value = queries.valuation(company=debts[0].company, day=today) if debts else None
    groups: OrderedDict[int, dict] = OrderedDict()
    totals = {"overdue": ZERO, "week": ZERO, "later": ZERO, "all": ZERO}
    ordered = sorted(
        debts, key=lambda d: (d.due_on is None, d.due_on or today, d.counterparty.name, d.pk)
    )
    for debt in ordered:
        part = bucket(debt, today)
        base = value.to_base(debt.amount - debt.paid, debt.currency) if value else None
        group = groups.setdefault(
            debt.counterparty_id,
            {
                "counterparty": {"id": debt.counterparty_id, "name": debt.counterparty.name},
                "total": ZERO,
                "overdue": ZERO,
                "debts": [],
            },
        )
        group["debts"].append((debt, part))
        if base is not None:
            group["total"] += base
            totals[part] += base
            totals["all"] += base
            if part == "overdue":
                group["overdue"] += base
    rows = sorted(
        groups.values(), key=lambda g: (-g["overdue"], -g["total"], g["counterparty"]["name"])
    )
    return {
        "groups": rows,
        "totals": {key: str(quantize(amount)) for key, amount in totals.items()},
    }


def warnings(debts: list[Debt], account: MoneyAccount) -> list[str]:
    if account.kind not in CASH_KINDS or not any(bank_only(debt) for debt in debts):
        return []
    return [
        _(
            "Goods with marking are paid to the distributor by bank transfer only: %(account)s "
            "is cash."
        )
        % {"account": account.name}
    ]


def pay(
    company,
    *,
    by: Membership,
    account: MoneyAccount,
    paid_on: date,
    items: list[tuple[Debt, Decimal]],
) -> list[Transaction]:
    """Pay each (debt, amount) from `account`, all or none."""
    if not items:
        raise DomainError(_("Pick at least one debt."))
    services._same_company(company, account)
    rows = []
    with transaction.atomic():
        for debt, amount in items:
            services._same_company(company, debt)
            if debt.direction != Debt.Direction.PAYABLE:
                raise DomainError(_("Only debts the company owes are paid here."))
            rows.append(
                services.pay_debt(debt, by=by, amount=amount, paid_on=paid_on, account=account)
            )
    return rows
