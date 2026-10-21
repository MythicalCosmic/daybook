"""The nightly check of the ledger's caches (`finance.tasks.verify_balances`, daily 03:00).

Account balances and debt totals are caches the services keep in step with the rows under row
locks. This check recomputes both from the ledger, corrects any drift (a manual database edit, a
bug) under the same locks, audits the correction and tells the owners. It never changes a row.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.audit import services as audit
from apps.companies.models import Company
from apps.console import pulse
from apps.core.money import quantize
from apps.finance import alerts, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import Debt, MoneyAccount, Receipt, Transaction
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

# A receipt uploaded for an entry that was never recorded (a quick add closed half-way) is kept
# this long, then deleted with its files.
ORPHAN_RECEIPT_AGE = timedelta(days=2)

Kind = Transaction.Kind
SETTLING = (Kind.DEBT_PAYMENT, Kind.WRITE_OFF)


def _account_truth(account_id: int):
    rows = Transaction.objects.filter(account_id=account_id, status=Transaction.Status.POSTED)
    return quantize(rows.aggregate(total=Sum("amount"))["total"] or 0)


def _debt_truth(debt_id: int):
    rows = Transaction.objects.filter(
        debt_id=debt_id, kind__in=SETTLING, status=Transaction.Status.POSTED
    )
    return quantize(rows.aggregate(total=Sum("debt_amount"))["total"] or 0)


def _status_for(debt: Debt, paid) -> str:
    if paid < debt.amount:
        return Debt.Status.OPEN
    if debt.status in (Debt.Status.PAID, Debt.Status.WRITTEN_OFF):
        return debt.status
    last = (
        Transaction.objects.filter(debt=debt, kind__in=SETTLING, status=Transaction.Status.POSTED)
        .order_by("-occurred_on", "-pk")
        .first()
    )
    return Debt.Status.WRITTEN_OFF if last and last.kind == Kind.WRITE_OFF else Debt.Status.PAID


def verify_company(company: Company, *, fix: bool = True) -> dict:
    """{"accounts": [...], "debts": [...]}: what drifted (and was fixed when `fix`).

    The first pass reads every cache against one grouped sum per table (a few queries however
    big the ledger is); only the suspects are re-read under the row locks and fixed.
    """
    report: dict = {"accounts": [], "debts": []}
    posted = Transaction.objects.filter(company=company, status=Transaction.Status.POSTED)
    account_sums = dict(
        posted.filter(account__isnull=False)
        .values("account_id")
        .annotate(total=Sum("amount"))
        .order_by()
        .values_list("account_id", "total")
    )
    suspects = [
        account.pk
        for account in MoneyAccount.objects.filter(company=company).only("pk", "balance")
        if account.balance != quantize(account_sums.get(account.pk) or 0)
    ]
    debt_sums = dict(
        posted.filter(kind__in=SETTLING, debt__isnull=False)
        .values("debt_id")
        .annotate(total=Sum("debt_amount"))
        .order_by()
        .values_list("debt_id", "total")
    )
    debt_suspects = [
        debt.pk
        for debt in Debt.objects.filter(company=company).exclude(status=Debt.Status.CANCELLED)
        if debt.paid != quantize(debt_sums.get(debt.pk) or 0)
        or debt.status != _status_for(debt, debt.paid)
    ]
    if not suspects and not debt_suspects:
        return report
    with transaction.atomic():
        services._hold_books(company)  # the ledger's lock order: settings, debts, accounts
        for debt in Debt.objects.select_for_update().filter(pk__in=debt_suspects).order_by("pk"):
            truth = _debt_truth(debt.pk)
            status = _status_for(debt, truth)
            if truth == debt.paid and status == debt.status:
                continue
            report["debts"].append(
                {
                    "id": debt.pk,
                    "paid": [str(debt.paid), str(truth)],
                    "status": [debt.status, status],
                }
            )
            if fix:
                debt.paid, debt.status = truth, status
                debt.save(update_fields=["paid", "status", "updated_at"])
        for account in (
            MoneyAccount.objects.select_for_update().filter(pk__in=suspects).order_by("pk")
        ):
            truth = _account_truth(account.pk)
            if truth == account.balance:
                continue
            report["accounts"].append(
                {
                    "id": account.pk,
                    "name": account.name,
                    "balance": [str(account.balance), str(truth)],
                }
            )
            if fix:
                MoneyAccount.objects.filter(pk=account.pk).update(balance=truth)
        if fix and (report["accounts"] or report["debts"]):
            audit.record(
                FinanceAction.BALANCES_FIXED,
                company_id=company.pk,
                actor=None,
                target=company,
                required_perm=Perm.FINANCE_VIEW,
                accounts=report["accounts"],
                debts=report["debts"],
            )
            alerts.send_drift(company, accounts=len(report["accounts"]), debts=len(report["debts"]))
            transaction.on_commit(lambda: pulse.bump(company.pk, "finance.ledger"))
    if report["accounts"] or report["debts"]:
        logger.warning("finance drift in company %s: %s", company.pk, report)
    return report


def verify_balances(*, fix: bool = True) -> dict[int, dict]:
    """Check every company with a ledger and the finance module on (jobs skip switched-off
    modules, §10.1); {company id: report} for those that drifted."""
    found = {}
    companies = (
        Company.objects.filter(features__contains=["finance"])
        .filter(Q(money_accounts__isnull=False) | Q(debts__isnull=False))
        .distinct()
    )
    for company in companies:
        try:
            report = verify_company(company, fix=fix)
        except Exception:
            logger.exception("finance balance check failed for company %s", company.pk)
            continue
        if report["accounts"] or report["debts"]:
            found[company.pk] = report
    return found


def purge_orphan_receipts(*, now=None) -> int:
    """Delete receipts uploaded on their own and never linked to an entry, with their files
    (after the delete commits). Returns how many were deleted."""
    cutoff = (now or timezone.now()) - ORPHAN_RECEIPT_AGE
    stale = list(Receipt.objects.filter(transaction__isnull=True, created_at__lt=cutoff)[:500])
    for receipt in stale:
        names = [name for name in (receipt.file.name, receipt.thumb.name) if name]
        storage = receipt.file.storage
        with transaction.atomic():
            receipt.delete()
            transaction.on_commit(
                lambda names=names, storage=storage: _delete_files(storage, names)
            )
    return len(stale)


def _delete_files(storage, names) -> None:
    for name in names:
        try:
            storage.delete(name)
        except OSError:
            logger.warning("could not delete the receipt file %s", name)
