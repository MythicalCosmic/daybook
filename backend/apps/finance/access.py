"""Who sees and records what in the finance ledger (docs/PLAN-OWNER.md §2.6, §5).

- `finance.view` sees accounts, entries and debts of the branches in the member's scope; rows
  with no branch (company-level accounts) only when the scope is every branch.
- `finance.record` records on the accounts the member operates or holds (and, with
  `finance.manage`, on any account in scope). A recorder always sees their own accounts and
  the entries on them or made by them, even without `finance.view`.
- Per-person detail of salaries, advances and reimbursements (rows of `is_sensitive`
  categories and of sensitive debts) needs `payroll.view`; the amounts stay, so totals add up.

Every function takes the acting `Membership`; nothing here trusts ids from a request alone.
"""

from django.db.models import Q, QuerySet

from apps.finance.models import Category, Counterparty, Debt, MoneyAccount, Transaction, Transfer
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm


def can_view(member: Membership) -> bool:
    return member.has_perm(Perm.FINANCE_VIEW)


def can_record(member: Membership) -> bool:
    return member.has_perm(Perm.FINANCE_RECORD)


def can_manage(member: Membership) -> bool:
    return member.has_perm(Perm.FINANCE_MANAGE)


def sees_salary_detail(member: Membership) -> bool:
    return member.has_perm(Perm.PAYROLL_VIEW)


def own_accounts_q(member: Membership) -> Q:
    """Accounts the member holds or operates."""
    return Q(holder=member) | Q(operators=member)


def visible_accounts(member: Membership) -> QuerySet[MoneyAccount]:
    """Accounts the member may see: in scope with `finance.view`, plus their own."""
    accounts = MoneyAccount.objects.for_company(member.company)
    mine = accounts.filter(own_accounts_q(member)) if can_record(member) else accounts.none()
    if not can_view(member):
        return accounts.filter(pk__in=mine.values("pk"))
    in_scope = scope.restrict(accounts, scope.branch_ids(member))
    return accounts.filter(Q(pk__in=in_scope.values("pk")) | Q(pk__in=mine.values("pk")))


def recordable_accounts(member: Membership) -> QuerySet[MoneyAccount]:
    """Active accounts the member may record on."""
    if not can_record(member):
        return MoneyAccount.objects.none()
    accounts = MoneyAccount.objects.for_company(member.company).filter(is_active=True)
    if can_manage(member):
        in_scope = scope.restrict(accounts, scope.branch_ids(member))
        return accounts.filter(Q(pk__in=in_scope.values("pk")) | own_accounts_q(member)).distinct()
    return accounts.filter(own_accounts_q(member)).distinct()


def may_record_on(member: Membership, account: MoneyAccount) -> bool:
    return recordable_accounts(member).filter(pk=account.pk).exists()


def transfer_targets(member: Membership) -> QuerySet[MoneyAccount]:
    """Accounts money may be moved to: every active account in the member's branch scope (a
    cashier hands cash to the branch safe) plus their own."""
    accounts = MoneyAccount.objects.for_company(member.company).filter(is_active=True)
    in_scope = scope.restrict(accounts, scope.branch_ids(member))
    return accounts.filter(Q(pk__in=in_scope.values("pk")) | own_accounts_q(member)).distinct()


def visible_transactions(member: Membership) -> QuerySet[Transaction]:
    """Ledger rows the member may see."""
    rows = Transaction.objects.for_company(member.company)
    own = Q(created_by=member.user)
    if can_record(member):
        own |= Q(account__in=MoneyAccount.objects.filter(own_accounts_q(member)))
    if not can_view(member):
        return rows.filter(own) if can_record(member) else rows.none()
    member_scope = scope.branch_ids(member)
    if member_scope is None:
        return rows
    return rows.filter(Q(branch_id__in=member_scope) | own)


def visible_transfers(member: Membership) -> QuerySet[Transfer]:
    transfers = Transfer.objects.for_company(member.company)
    accounts = visible_accounts(member)
    return transfers.filter(Q(from_account__in=accounts) | Q(to_account__in=accounts))


def visible_debts(member: Membership) -> QuerySet[Debt]:
    if not can_view(member):
        return Debt.objects.none()
    return scope.restrict(Debt.objects.for_company(member.company), scope.branch_ids(member))


def visible_counterparties(member: Membership) -> QuerySet[Counterparty]:
    """The party directory is company-wide (a supplier serves every branch)."""
    if not (can_view(member) or can_record(member)):
        return Counterparty.objects.none()
    return Counterparty.objects.for_company(member.company)


def visible_categories(member: Membership) -> QuerySet[Category]:
    return Category.objects.for_company(member.company)


def is_sensitive_row(row: Transaction) -> bool:
    """Salaries, advances and reimbursements: per-person detail needs payroll.view."""
    if row.category_id is not None and row.category.is_sensitive:
        return True
    return row.debt_id is not None and row.debt.kind in Debt.SENSITIVE_KINDS


def is_sensitive_debt(debt: Debt) -> bool:
    return debt.kind in Debt.SENSITIVE_KINDS


def masks_row(member: Membership, row: Transaction) -> bool:
    return is_sensitive_row(row) and not sees_salary_detail(member)


def masks_debt(member: Membership, debt: Debt) -> bool:
    return is_sensitive_debt(debt) and not sees_salary_detail(member)


def sensitive_rows_q() -> Q:
    """Rows whose per-person detail is hidden without payroll.view (for searches)."""
    return Q(category__is_sensitive=True) | Q(debt__kind__in=Debt.SENSITIVE_KINDS)


def branch_filter(member_scope: list[int] | None, wanted: list[int]) -> list[int] | None:
    """The member's scope narrowed to the branches a request asks for (§4: `branch` is
    intersected with the caller's scope). None means every branch."""
    if not wanted:
        return member_scope
    if member_scope is None:
        return sorted(set(wanted))
    return sorted(set(wanted) & set(member_scope))
