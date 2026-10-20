"""The nightly check of the ledger's caches (`finance.tasks.verify_balances`, daily 03:00).

Account balances and debt totals are caches the services keep in step with the rows under row
locks. This check recomputes both from the ledger, corrects any drift (a manual database edit, a
bug) under the same locks, audits the correction and tells the owners. It never changes a row.
"""

import logging

from django.db import transaction
from django.db.models import Q, Sum

from apps.audit import services as audit
from apps.companies.models import Company
from apps.console import pulse
from apps.core.money import quantize
from apps.finance import alerts, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import Debt, MoneyAccount, Transaction
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

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
    """{"accounts": [...], "debts": [...]}: what drifted (and was fixed when `fix`)."""
    report: dict = {"accounts": [], "debts": []}
    suspects = [
        account.pk
        for account in MoneyAccount.objects.filter(company=company).only("pk", "balance")
        if account.balance != _account_truth(account.pk)
    ]
    debt_suspects = [
        debt.pk
        for debt in Debt.objects.filter(company=company).exclude(status=Debt.Status.CANCELLED)
        if debt.paid != _debt_truth(debt.pk) or debt.status != _status_for(debt, debt.paid)
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
    """Check every company with a ledger; {company id: report} for those that drifted."""
    found = {}
    companies = Company.objects.filter(
        Q(money_accounts__isnull=False) | Q(debts__isnull=False)
    ).distinct()
    for company in companies:
        try:
            report = verify_company(company, fix=fix)
        except Exception:
            logger.exception("finance balance check failed for company %s", company.pk)
            continue
        if report["accounts"] or report["debts"]:
            found[company.pk] = report
    return found
