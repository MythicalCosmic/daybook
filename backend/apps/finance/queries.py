"""Read functions of the finance ledger, for other apps, the dashboard and the AI tools.

A function returning branch-bound data takes the required keyword
`branch_ids: list[int] | None` (callers pass `apps.members.scope.branch_ids(member)`).
"""

from datetime import date
from decimal import Decimal

from django.db.models import ExpressionWrapper, F, QuerySet, Sum

from apps.core.money import MoneyField, quantize
from apps.finance.models import Debt, MoneyAccount, Transaction, Transfer


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
    return debts.annotate(
        outstanding=ExpressionWrapper(F("amount") - F("paid"), output_field=MoneyField())
    ).order_by(F("due_on").asc(nulls_last=True), "issued_on", "pk")


def has_ledger_rows(company) -> bool:
    """Whether anything was booked in the company's base currency (its base currency is then
    locked): any transaction, transfer or debt, void ones included."""
    return (
        Transaction.objects.filter(company=company).exists()
        or Transfer.objects.filter(company=company).exists()
        or Debt.objects.filter(company=company).exists()
    )
