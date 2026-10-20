"""What the finance ledger gives the shared registries (registered in `hooks.py`): palette
search, the overdue badge, branch cards, the briefing section, portfolio facts, calendar dates,
the offboarding step, the "Get started" step, file and history checks, and the receiver that
moves a leaver's cash.

Every provider applies the member's branch scope itself (§2.6) and returns money as strings.
"""

import logging
from datetime import date, timedelta

from django.db.models import Q
from django.utils import translation
from django.utils.translation import gettext as _

from apps.console.registry import CalendarItem, FieldSpec, OffboardStep, SearchHit
from apps.core.money import format_money, quantize
from apps.finance import access, queries
from apps.finance.models import Debt, MoneyAccount, Receipt, Transaction
from apps.finance.sources import Source
from apps.members import scope
from apps.members.models import Membership

logger = logging.getLogger(__name__)

OFFBOARD_SOURCE = "finance.offboard"


def _lang() -> str:
    return (translation.get_language() or "uz")[:2]


def _money(amount, currency: str) -> str:
    return format_money(amount, currency, _lang())


# Search ---------------------------------------------------------------------------------------


def search_transactions(member: Membership, q: str, limit: int) -> list[SearchHit]:
    rows = access.visible_transactions(member)
    mask = not access.sees_salary_detail(member)
    hits = []
    for row in queries.search_transactions(rows, q, limit, mask_sensitive=mask):
        masked = mask and access.is_sensitive_row(row)
        title = (
            row.category.name
            if masked and row.category_id
            else (
                row.description
                or (row.category.name if row.category_id else row.get_kind_display())
            )
        )
        parts = [row.occurred_on.strftime("%d.%m.%Y"), _money(row.amount, row.currency)]
        if row.account_id:
            parts.append(row.account.name)
        if row.counterparty_id and not masked:
            parts.append(row.counterparty.name)
        hits.append(
            SearchHit(
                type="finance.transaction",
                id=row.pk,
                title=title,
                subtitle=" · ".join(parts),
                url=f"/c/{member.company_id}/finance/transactions?txn={row.pk}",
            )
        )
    return hits


def search_counterparties(member: Membership, q: str, limit: int) -> list[SearchHit]:
    rows = access.visible_counterparties(member)
    hits = []
    for party in queries.search_counterparties(rows, q, limit):
        bits = [party.get_kind_display()]
        if party.phone:
            bits.append(party.phone)
        if party.tin:
            bits.append(party.tin)
        hits.append(
            SearchHit(
                type="finance.counterparty",
                id=party.pk,
                title=party.name,
                subtitle=" · ".join(bits),
                url=f"/c/{member.company_id}/finance/counterparties/{party.pk}",
            )
        )
    return hits


# Pulse ----------------------------------------------------------------------------------------


def overdue_count(member: Membership) -> int:
    company = member.company
    return queries.overdue_count(
        company, branch_ids=scope.branch_ids(member), today=queries.local_today(company)
    )


# Branch cards and portfolio -------------------------------------------------------------------


def branch_facts(company, day: date, now, branch_ids: list[int]) -> dict[int, dict]:
    """{branch id: {"cash": "…"}}: cash desks, safes and cash staff hold in the branch, in the
    base currency at today's rate."""
    if not branch_ids:
        return {}
    value = queries.valuation(company, day)
    totals = {branch_id: quantize(0) for branch_id in branch_ids}
    accounts = MoneyAccount.objects.filter(
        company=company, branch_id__in=branch_ids, kind__in=queries.CASH_KINDS
    ).only("branch_id", "balance", "currency")
    for account in accounts:
        base = value.to_base(account.balance, account.currency)
        if base is not None:
            totals[account.branch_id] += base
    return {branch_id: {"cash": str(quantize(total))} for branch_id, total in totals.items()}


def company_facts(company, range_, member: Membership) -> dict:
    """Portfolio card: cash now, and income, expenses and profit over the range."""
    member_scope = scope.branch_ids(member)
    today = queries.local_today(company)
    cash = queries.cash_position(company, None, branch_ids=member_scope, today=today)
    pnl = queries.totals(company, range_.start, range_.end, branch_ids=member_scope)
    return {
        "cash": str(cash["total"]),
        "income": str(pnl["income"]),
        "expenses": str(pnl["expense"]),
        "profit": str(pnl["profit"]),
    }


# Briefing -------------------------------------------------------------------------------------


def brief_section(company, day: date, now, branch_ids: list[int] | None) -> dict | None:
    """Yesterday's income and expenses, cash now, overdue money owed to us and what falls due
    today. Silent for a company with no ledger yet."""
    if not queries.has_ledger_rows(company):
        return None
    yesterday = day - timedelta(days=1)
    pnl = queries.totals(company, yesterday, yesterday, branch_ids=branch_ids)
    cash = queries.cash_position(company, None, branch_ids=branch_ids, today=day)
    owed = queries.debt_totals(company, branch_ids=branch_ids, today=day)
    due_today = queries.debts(company, None, branch_ids=branch_ids, today=day).filter(due_on=day)
    receivable = owed[Debt.Direction.RECEIVABLE]
    payable = owed[Debt.Direction.PAYABLE]
    return {
        "currency": company.base_currency,
        "cash": str(cash["total"]),
        "income_yesterday": str(pnl["income"]),
        "expense_yesterday": str(pnl["expense"]),
        "receivable_overdue": str(quantize(receivable["overdue"])),
        "receivable_overdue_count": receivable["overdue_count"],
        "payable_overdue": str(quantize(payable["overdue"])),
        "payable_overdue_count": payable["overdue_count"],
        "due_today_count": due_today.count(),
        "stale_rate": bool(cash["rate"]["stale"]),
        "url": f"/c/{company.pk}/finance",
    }


# Calendar -------------------------------------------------------------------------------------


def calendar_events(company, start: date, end: date, member: Membership) -> list[CalendarItem]:
    """Due dates of open debts (and of their instalments) in the member's scope."""
    rows = (
        access.visible_debts(member)
        .filter(status=Debt.Status.OPEN)
        .filter(Q(due_on__range=(start, end)) | Q(installments__due_on__range=(start, end)))
        .select_related("counterparty", "membership", "company")
        .prefetch_related("installments")
        .distinct()
    )
    items = []
    for debt in rows:
        masked = access.masks_debt(member, debt)
        party = _("Hidden") if masked else (debt.counterparty or debt.membership)
        left = debt.amount - debt.paid
        receivable = debt.direction == Debt.Direction.RECEIVABLE
        color = "var(--c-success)" if receivable else "var(--c-danger)"
        kind = "finance.receivable" if receivable else "finance.payable"
        url = f"/c/{company.pk}/finance/debts?debt={debt.pk}"
        installments = [i for i in debt.installments.all() if start <= i.due_on <= end]
        if installments:
            for installment in installments:
                items.append(
                    CalendarItem(
                        id=f"installment-{installment.pk}",
                        kind=kind,
                        title=_debt_title(receivable, party, installment.amount, debt.currency),
                        start=installment.due_on,
                        end=None,
                        all_day=True,
                        color=color,
                        url=url,
                    )
                )
        elif debt.due_on and start <= debt.due_on <= end:
            items.append(
                CalendarItem(
                    id=f"debt-{debt.pk}",
                    kind=kind,
                    title=_debt_title(receivable, party, left, debt.currency),
                    start=debt.due_on,
                    end=None,
                    all_day=True,
                    color=color,
                    url=url,
                )
            )
    return items


def _debt_title(receivable: bool, party, amount, currency: str) -> str:
    amount_text = _money(amount, currency)
    if receivable:
        return _("%(party)s pays %(amount)s") % {"party": party, "amount": amount_text}
    return _("Pay %(party)s %(amount)s") % {"party": party, "amount": amount_text}


# Offboarding ----------------------------------------------------------------------------------


def offboard_preview(membership: Membership) -> OffboardStep:
    """Money the leaver holds (a blocker while there is any, with "transfer to …" as the
    answer), and their open advances, loans and money owed to them (settled by the final
    payslip). Per-person salary amounts stay out: the payroll step shows them to those who may
    see them."""
    company = membership.company
    lines: list[str] = []
    blockers: list[str] = []
    held = list(
        MoneyAccount.objects.filter(company=company, holder=membership, is_active=True).order_by(
            "currency", "name"
        )
    )
    holding = [account for account in held if account.balance > 0]
    for account in held:
        lines.append(
            _("%(account)s: %(balance)s")
            % {"account": account.name, "balance": _money(account.balance, account.currency)}
        )
    if holding:
        total = ", ".join(_money(account.balance, account.currency) for account in holding)
        blockers.append(
            _("%(person)s holds %(amount)s. Choose where to move it, or move it first.")
            % {"person": membership, "amount": total}
        )
    receivable = Debt.objects.filter(
        company=company,
        membership=membership,
        status=Debt.Status.OPEN,
        direction=Debt.Direction.RECEIVABLE,
    )
    if count := receivable.count():
        lines.append(
            _("%(count)s open advance(s) or loan(s): the final payslip deducts them.")
            % {"count": count}
        )
    payable = Debt.objects.filter(
        company=company,
        membership=membership,
        status=Debt.Status.OPEN,
        direction=Debt.Direction.PAYABLE,
    )
    if count := payable.count():
        lines.append(
            _(
                "%(count)s amount(s) we still owe them (reimbursements, pay): "
                "paid on the final payslip."
            )
            % {"count": count}
        )
    if not lines:
        lines.append(_("Holds no company money and owes nothing."))
    fields = []
    defaults = {}
    if holding:
        currencies = {account.currency for account in holding}
        targets = (
            MoneyAccount.objects.filter(company=company, is_active=True, currency__in=currencies)
            .exclude(holder=membership)
            .exclude(kind__in=MoneyAccount.HOLDER_KINDS)
            .order_by("order", "name")
        )
        choices = tuple(
            (str(account.pk), f"{account.name} ({account.currency})") for account in targets
        )
        fields.append(
            FieldSpec(
                name="transfer_to",
                label=_("Move their money to"),
                kind="choice",
                required=False,
                choices=choices,
                help=_("Each balance moves on the last working day to this account."),
            )
        )
        preferred = next(
            (
                account
                for account in targets
                if account.branch_id == membership.home_branch_id
                and account.kind in (MoneyAccount.Kind.SAFE, MoneyAccount.Kind.CASH)
            ),
            targets.first(),
        )
        if preferred is not None:
            defaults["transfer_to"] = str(preferred.pk)
    return OffboardStep(lines=lines, blockers=blockers, fields=fields, defaults=defaults)


def on_member_left(sender, membership, reason, by, details, **kwargs) -> None:
    """Move what the leaver held to the account chosen in the offboarding wizard (one transfer
    per account, idempotent per account), then archive their emptied accounts."""
    from apps.finance import services

    answer = (details or {}).get("finance") or {}
    target_id = answer.get("transfer_to")
    if not target_id or by is None:
        return
    company = membership.company
    target = MoneyAccount.objects.filter(company=company, pk=target_id, is_active=True).first()
    if target is None:
        logger.warning("offboarding %s: transfer target %s not found", membership.pk, target_id)
        return
    today = queries.local_today(company)
    for account in MoneyAccount.objects.filter(company=company, holder=membership, is_active=True):
        try:
            if account.balance > 0 and account.currency == target.currency:
                services.transfer(
                    company,
                    by=by,
                    from_account=account,
                    to_account=target,
                    amount_out=account.balance,
                    occurred_on=today,
                    description=_("Handed over on leaving"),
                    source=Source(OFFBOARD_SOURCE, membership.pk, f"a{account.pk}"),
                )
            account.refresh_from_db()
            if not account.balance:
                services.archive_account(account, by=by)
        except Exception:
            logger.exception("offboarding %s: moving account %s failed", membership.pk, account.pk)


# Get started ----------------------------------------------------------------------------------


def opening_balances_done(company) -> bool:
    return (
        Transaction.objects.filter(
            company=company, kind=Transaction.Kind.OPENING, status=Transaction.Status.POSTED
        ).exists()
        or Debt.objects.filter(company=company, is_opening=True)
        .exclude(status=Debt.Status.CANCELLED)
        .exists()
    )


# Private files and record history -------------------------------------------------------------


def _member(user, company_id: int) -> Membership | None:
    return (
        Membership.objects.select_related("role", "company")
        .filter(company_id=company_id, user=user, status=Membership.Status.APPROVED)
        .first()
    )


def receipt_check(user, company_id: int, object_id) -> bool:
    """A signed receipt link opens for whoever may still see its entry (or uploaded it)."""
    receipt = (
        Receipt.objects.filter(company_id=company_id, pk=object_id)
        .select_related("transaction")
        .first()
    )
    if receipt is None:
        return False
    if receipt.uploaded_by_id == user.pk:
        return True
    member = _member(user, company_id)
    if member is None or receipt.transaction_id is None:
        return False
    return access.visible_transactions(member).filter(pk=receipt.transaction_id).exists()


def transaction_history_check(member: Membership, target_id: int) -> bool:
    return access.visible_transactions(member).filter(pk=target_id).exists()


def debt_history_check(member: Membership, target_id: int) -> bool:
    return access.visible_debts(member).filter(pk=target_id).exists()


def account_history_check(member: Membership, target_id: int) -> bool:
    return access.visible_accounts(member).filter(pk=target_id).exists()


def transfer_history_check(member: Membership, target_id: int) -> bool:
    return access.visible_transfers(member).filter(pk=target_id).exists()


def company_row_check(model):
    def check(member: Membership, target_id: int) -> bool:
        return model.objects.filter(company=member.company, pk=target_id).exists()

    return check
