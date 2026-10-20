"""Business logic of the finance ledger: every write, shared by the API, the bots and Celery.

This is the W0 finance contract (docs/PLAN-OWNER.md §3.7) that sales, payroll, invoices and
claims post through; finance never imports them. The rules every write follows:

- `by` is the acting `Membership`, or `None` for the system. A system write to the ledger must
  pass an idempotency `source`; `created_by` and the audit actor are `by.user`.
- The caller passes positive amounts and the service sets the sign (+ money in, - money out).
  `owner` and `opening` entries have no natural sign, so for those the sign of `amount` says
  the direction.
- A repeated `source` returns what the first call made. Voiding or rejecting frees the source,
  so a module can void a booking and book it again.
- Every write is atomic, checks that everything it links belongs to the company, refuses dates
  on or before `FinanceSettings.locked_until`, locks rows in one global order (debt, transfer,
  transaction, then accounts by id) and moves balances with `F()` under those locks.
- Each row freezes its rate and `base_amount`. Settling a debt at another value than it was
  opened at (another currency, or the same foreign currency at another rate) books the
  difference as an `fx` row, and so does a cross-currency transfer whose two sides differ in
  the base currency.
- Services don't check permissions: the API, the bots and the calling module do.
- Person-made changes without a source are audited here; sourced writes are part of an action
  their module audits (the rows keep `created_by` and the source either way).
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.core.exceptions import DomainError
from apps.core.money import Currency, format_money, quantize
from apps.finance import conf, defaults, sources
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    LIVE_STATUSES,
    Category,
    Debt,
    MoneyAccount,
    Transaction,
    Transfer,
)
from apps.finance.rates import RateQuote, convert, quoted_currency, rate_for
from apps.finance.sources import Source
from apps.members.models import Membership
from apps.members.permissions import Perm

__all__ = [
    "RateQuote",
    "Source",
    "account_for_branch",
    "account_for_holder",
    "approve_transaction",
    "cancel_debt",
    "create_account",
    "create_defaults",
    "get_settings",
    "lock_debt",
    "open_debt",
    "pay_debt",
    "rate_for",
    "record_transaction",
    "reject_transaction",
    "transfer",
    "unlock_debt",
    "void_transaction",
    "void_transfer",
    "write_off",
]

Kind = Transaction.Kind
Status = Transaction.Status

# Rows the ledger makes as a consequence of another row (the exchange difference of a debt
# payment) point back at it with this source type, registered in hooks.py.
ROW_SOURCE = "finance.transaction"

RECORDABLE_KINDS = (Kind.INCOME, Kind.EXPENSE, Kind.OWNER, Kind.OPENING)
SIGNED_KINDS = (Kind.OWNER, Kind.OPENING)
MAX_AMOUNT = Decimal("9999999999999999.99")
ZERO = Decimal(0)
ONE = Decimal(1)

get_settings = conf.get_settings


def create_defaults(company) -> None:
    """The cash desk and terminal accounts and the system categories (`defaults.ensure`)."""
    defaults.ensure(company)


# Accounts


@transaction.atomic
def create_account(
    company,
    *,
    by: Membership | None,
    kind: str,
    name: str,
    currency: str = Currency.UZS,
    branch=None,
    holder: Membership | None = None,
) -> MoneyAccount:
    user = _actor(company, by)
    if kind not in MoneyAccount.Kind.values:
        raise ValueError(f"Unknown account kind {kind!r}.")
    _check_currency(currency)
    _same_company(company, branch, holder)
    name = (name or "").strip()[:100]
    if not name:
        raise DomainError(_("Give the account a name."))
    if kind in MoneyAccount.HOLDER_KINDS and holder is None:
        raise DomainError(_("Pick the person who holds this money."))
    accounts = MoneyAccount.objects.filter(company=company)
    if accounts.filter(name__iexact=name).exists():
        raise DomainError(_("There is already an account called %(name)s.") % {"name": name})
    safes = accounts.filter(branch=branch, kind=kind, currency=currency)
    if kind == MoneyAccount.Kind.SAFE and branch is not None and safes.exists():
        raise DomainError(
            _("%(branch)s already has a safe in %(currency)s.")
            % {"branch": branch, "currency": currency}
        )
    if holder is not None and accounts.filter(holder=holder, kind=kind, currency=currency).exists():
        raise DomainError(
            _("%(person)s already has an account like this in %(currency)s.")
            % {"person": holder, "currency": currency}
        )
    try:
        with transaction.atomic():
            account = MoneyAccount.objects.create(
                company=company,
                kind=kind,
                name=name,
                currency=currency,
                branch=branch,
                holder=holder,
            )
    except IntegrityError:
        raise DomainError(_("An account like this already exists.")) from None
    _audit(FinanceAction.ACCOUNT_CREATED, company, user, account, kind=kind, currency=currency)
    return account


@transaction.atomic
def account_for_holder(
    company, membership: Membership, *, kind: str = "employee", currency: str = Currency.UZS
) -> MoneyAccount:
    """The account for money `membership` holds (an employee's cash, an owner's own money),
    made on first use. Exactly one per person, kind and currency, even under concurrency."""
    if kind not in MoneyAccount.HOLDER_KINDS:
        raise ValueError(f"A holder account is an employee or owner account, not {kind!r}.")
    _check_currency(currency)
    _same_company(company, membership)
    rows = MoneyAccount.objects.filter(company=company, holder=membership, kind=kind)
    found = rows.filter(currency=currency).first()
    if found is not None:
        return _reopen(company, found)
    with translation.override(company.default_language):
        if kind == MoneyAccount.Kind.OWNER:
            name = _("%(person)s, own money") % {"person": membership}
        else:
            name = _("%(person)s, cash on hand") % {"person": membership}
    if currency != company.base_currency:
        name = f"{name} ({currency})"
    try:
        with transaction.atomic():
            account = MoneyAccount.objects.create(
                company=company,
                kind=kind,
                name=defaults.free_name(MoneyAccount.objects.filter(company=company), name),
                currency=currency,
                holder=membership,
                branch=membership.home_branch,
            )
    except IntegrityError:
        found = rows.filter(currency=currency).first()
        if found is None:
            raise
        return _reopen(company, found)
    _audit(FinanceAction.ACCOUNT_CREATED, company, None, account, kind=kind, currency=currency)
    return account


@transaction.atomic
def account_for_branch(branch, *, kind: str = "safe", currency: str = Currency.UZS) -> MoneyAccount:
    """The branch's account of `kind` in `currency` (its safe by default), made on first use.
    Exactly one per branch, kind and currency, even under concurrency."""
    if kind not in MoneyAccount.Kind.values or kind in MoneyAccount.HOLDER_KINDS:
        raise ValueError(f"A branch account can't be of kind {kind!r}.")
    _check_currency(currency)
    company = branch.company
    rows = MoneyAccount.objects.filter(company=company, branch=branch, kind=kind, currency=currency)
    found = rows.order_by("pk").first()
    if found is not None:
        return _reopen(company, found)
    # Serialize the makers of this branch's accounts. NO KEY UPDATE leaves inserts of rows that
    # point at the branch alone.
    type(branch).objects.select_for_update(no_key=True).filter(pk=branch.pk).first()
    found = rows.order_by("pk").first()
    if found is not None:
        return _reopen(company, found)
    with translation.override(company.default_language):
        name = f"{branch.name}, {MoneyAccount.Kind(kind).label}"
    if currency != company.base_currency:
        name = f"{name} ({currency})"
    account = MoneyAccount.objects.create(
        company=company,
        kind=kind,
        name=defaults.free_name(MoneyAccount.objects.filter(company=company), name),
        currency=currency,
        branch=branch,
    )
    _audit(FinanceAction.ACCOUNT_CREATED, company, None, account, kind=kind, currency=currency)
    return account


def _reopen(company, account: MoneyAccount) -> MoneyAccount:
    """An archived account found by a get-or-create helper is put back to use."""
    if not account.is_active:
        account.is_active = True
        account.save(update_fields=["is_active", "updated_at"])
        _audit(FinanceAction.ACCOUNT_REOPENED, company, None, account)
    return account


# Transactions


@transaction.atomic
def record_transaction(
    company,
    *,
    by: Membership | None,
    kind: str,
    amount,
    occurred_on: date,
    account: MoneyAccount | None = None,
    currency: str | None = None,
    category: Category | str | None = None,  # a Category or a system_code
    counterparty=None,
    membership: Membership | None = None,
    branch=None,
    debt: Debt | None = None,
    debt_amount=None,
    description: str = "",
    rate=None,
    is_contra: bool = False,
    status: str = Status.POSTED,
    source: Source | None = None,
    project=None,
) -> Transaction:
    """Book an income, an expense, an owner contribution or draw, or an opening balance.

    Income and expense amounts are positive (the sign is set here; `is_contra` flips it: a
    refund reduces income). For `owner` and `opening` the sign says the direction. The money is
    on `account`, in its currency. `debt` only links the row to a debt it concerns (interest or
    a fee on a loan): payments go through `pay_debt`, and earning or spending on credit through
    `open_debt`. `status="pending"` books an income or expense that moves no balance until
    `approve_transaction`. Without `rate` the company's rate for the day is used.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    if source is not None and (found := _live_row(company, source)) is not None:
        return found
    user = _actor(company, by)
    if kind not in RECORDABLE_KINDS:
        raise ValueError(
            f"record_transaction books {', '.join(RECORDABLE_KINDS)}; use the debt or transfer "
            f"services for {kind!r}."
        )
    if status not in (Status.POSTED, Status.PENDING):
        raise ValueError(f"A new entry is posted or pending, not {status!r}.")
    if status == Status.PENDING and kind not in (Kind.INCOME, Kind.EXPENSE):
        raise ValueError("Only an income or an expense can wait for approval.")
    if is_contra and kind not in (Kind.INCOME, Kind.EXPENSE):
        raise ValueError("Only an income or an expense can be a contra entry.")
    _same_company(company, account, counterparty, membership, branch, debt, project)

    if kind in SIGNED_KINDS:
        signed = _money(amount, signed=True)
    else:
        signed = _money(amount)
        if (kind == Kind.EXPENSE) != is_contra:
            signed = -signed
    if account is None:
        raise DomainError(_("Pick the account the money went to or came from."))
    _check_active(account)
    if currency is not None and currency != account.currency:
        raise DomainError(
            _("%(account)s holds %(currency)s.")
            % {"account": account, "currency": account.currency}
        )
    currency = account.currency
    if debt is not None:
        if debt.status == Debt.Status.CANCELLED:
            raise DomainError(_("This debt was cancelled."))
        debt_amount = _money(debt_amount) if debt_amount is not None else None
    elif debt_amount is not None:
        raise ValueError("debt_amount needs a debt.")
    if kind in (Kind.INCOME, Kind.EXPENSE):
        category = _category(company, category, kind=kind, by=by)
    elif category is not None:
        raise DomainError(_("Owner and opening entries have no category."))
    if branch is None and account.branch_id:
        branch = account.branch
    _check_open(company, occurred_on)
    quote = _quote(company, currency, occurred_on, rate)

    def write() -> Transaction:
        posted = status == Status.POSTED
        locked = _lock_accounts(account.pk if posted else None)
        row = _row(
            company,
            user=user,
            kind=kind,
            status=status,
            amount=signed,
            occurred_on=occurred_on,
            currency=currency,
            quote=quote,
            account=account,
            category=category,
            counterparty=counterparty,
            membership=membership,
            branch=branch,
            project=project,
            debt=debt,
            debt_amount=debt_amount,
            is_contra=is_contra,
            description=description,
            source=source,
        )
        if posted:
            _move(locked, {account.pk: signed})
        if source is None:
            _audit(
                FinanceAction.TRANSACTION_RECORDED,
                company,
                user,
                row,
                sensitive=_is_sensitive(row),
                **_row_details(row),
            )
        return row

    return _write_once(write, lambda: _live_row(company, source), source)


@transaction.atomic
def approve_transaction(txn: Transaction, *, by: Membership) -> Transaction:
    """Post a pending entry: it now moves its account's balance."""
    _need_actor(by)
    txn = _lock_row(txn)
    company = txn.company
    user = _actor(company, by)
    if txn.status != Status.PENDING:
        raise DomainError(_("This entry isn't waiting for approval."))
    _check_open(company, txn.occurred_on)
    locked = _lock_accounts(txn.account_id)
    if txn.account_id is not None:
        _check_active(locked[txn.account_id])
    txn.status = Status.POSTED
    txn.approved_by = user
    txn.approved_at = timezone.now()
    txn.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    if txn.account_id is not None:
        _move(locked, {txn.account_id: txn.amount})
    _audit(FinanceAction.TRANSACTION_APPROVED, company, user, txn, sensitive=_is_sensitive(txn))
    return txn


@transaction.atomic
def reject_transaction(txn: Transaction, *, by: Membership, reason: str) -> Transaction:
    """Turn down a pending entry. It never moved a balance, so a closed period doesn't stop it.
    The void fields record who rejected it and why."""
    _need_actor(by)
    reason = _reason(reason)
    txn = _lock_row(txn)
    company = txn.company
    user = _actor(company, by)
    if txn.status != Status.PENDING:
        raise DomainError(_("This entry isn't waiting for approval."))
    txn.status = Status.REJECTED
    txn.voided_by = user
    txn.voided_at = timezone.now()
    txn.void_reason = reason
    txn.save(update_fields=["status", "voided_by", "voided_at", "void_reason", "updated_at"])
    _audit(
        FinanceAction.TRANSACTION_REJECTED,
        company,
        user,
        txn,
        sensitive=_is_sensitive(txn),
        reason=reason,
    )
    return txn


@transaction.atomic
def void_transaction(txn: Transaction, *, by: Membership, reason: str) -> Transaction:
    """Void a posted or pending entry and undo what it did to balances and its debt.

    Rows of a transfer are voided with `void_transfer`, and the rows that opened a debt with
    `cancel_debt`. Voiding a debt payment voids its exchange difference too and reopens the
    debt. A void may leave an account below zero: corrections must always be possible.
    """
    _need_actor(by)
    reason = _reason(reason)
    current = Transaction.objects.select_related("company").get(pk=txn.pk)
    company = current.company
    user = _actor(company, by)
    if current.transfer_id is not None:
        raise DomainError(_("This entry is part of a transfer: void the transfer instead."))
    if current.kind == Kind.DEBT_OPEN or (
        current.kind in (Kind.INCOME, Kind.EXPENSE)
        and current.account_id is None
        and current.debt_id is not None
    ):
        raise DomainError(_("This entry opened a debt: cancel the debt instead."))
    if current.kind == Kind.FX and current.source_type == ROW_SOURCE:
        raise DomainError(_("This exchange difference belongs to a payment: void the payment."))
    settles = current.kind in (Kind.DEBT_PAYMENT, Kind.WRITE_OFF)
    debt = _lock_debt(current.debt_id) if settles else None

    txn = _lock_row(current)
    if txn.status not in LIVE_STATUSES:
        raise DomainError(_("This entry is already void or rejected."))
    if debt is not None and debt.is_locked and not _same_source(debt, txn):
        raise DomainError(_reserved_message(debt))
    rows = [txn, *_follow_ups(company, txn)]
    _check_open(company, *(row.occurred_on for row in rows))
    _void_rows(rows, user=user, reason=reason)
    if debt is not None and txn.debt_amount:
        debt.paid -= txn.debt_amount
        debt.status = Debt.Status.OPEN
        debt.save(update_fields=["paid", "status", "updated_at"])
    _audit(
        FinanceAction.TRANSACTION_VOIDED,
        company,
        user,
        txn,
        sensitive=_is_sensitive(txn),
        reason=reason,
        **_row_details(txn),
    )
    return txn


# Transfers


@transaction.atomic
def transfer(
    company,
    *,
    by: Membership | None,
    from_account: MoneyAccount,
    to_account: MoneyAccount,
    amount_out,
    occurred_on: date,
    amount_in=None,
    rate=None,
    fee=ZERO,
    description: str = "",
    source: Source | None = None,
) -> Transfer:
    """Move money between two accounts of the company.

    In one currency the whole amount arrives. Across currencies, `amount_in` is what arrived;
    without it, `amount_out` is converted at `rate` (UZS per 1 USD) or else the company's rate
    for the day, and the exchange rate is kept on the transfer. Each side is valued at the
    company's rate for the day, and a difference between them is booked as an `fx` row. A fee
    is charged on `from_account` in its currency, as a `bank_fees` expense.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    if source is not None and (found := _posted_transfer(company, source)) is not None:
        return found
    user = _actor(company, by)
    _same_company(company, from_account, to_account)
    if from_account.pk == to_account.pk:
        raise DomainError(_("Pick two different accounts."))
    _check_active(from_account)
    _check_active(to_account)
    amount_out = _money(amount_out)
    fee = _money(fee, allow_zero=True)
    base = company.base_currency
    exchange_rate = None
    if from_account.currency == to_account.currency:
        if rate is not None:
            raise DomainError(_("A transfer in one currency has no exchange rate."))
        if amount_in is not None and _money(amount_in) != amount_out:
            raise DomainError(
                _("In one currency the whole amount arrives. Record a fee for the difference.")
            )
        amount_in = amount_out
    elif amount_in is not None:
        amount_in = _money(amount_in)
        exchange_rate = _implied_rate(from_account.currency, amount_out, amount_in)
    else:
        if rate is not None:
            exchange_rate = _rate(rate)
        else:
            foreign = (
                from_account.currency if from_account.currency != base else to_account.currency
            )
            exchange_rate = rate_for(company, foreign, occurred_on).rate
        amount_in = convert(amount_out, from_account.currency, to_account.currency, exchange_rate)
        if amount_in <= 0:
            raise DomainError(_("That's too little to exchange."))
    _check_open(company, occurred_on)
    quote_out = _side_quote(company, from_account.currency, occurred_on, exchange_rate)
    quote_in = _side_quote(company, to_account.currency, occurred_on, exchange_rate)
    fee_category = _category(company, "bank_fees", kind=Category.Kind.EXPENSE) if fee else None
    description = (description or "").strip()[:300]

    def write() -> Transfer:
        locked = _lock_accounts(from_account.pk, to_account.pk)
        moved = Transfer.objects.create(
            company=company,
            occurred_on=occurred_on,
            from_account=from_account,
            to_account=to_account,
            amount_out=amount_out,
            amount_in=amount_in,
            exchange_rate=exchange_rate,
            fee=fee,
            description=description,
            source_type=source.type if source else "",
            source_id=source.id if source else None,
            source_key=source.key if source else "",
            created_by=user,
        )
        common = {"user": user, "occurred_on": occurred_on, "transfer": moved}
        out_row = _row(
            company,
            **common,
            kind=Kind.TRANSFER,
            account=from_account,
            amount=-amount_out,
            currency=from_account.currency,
            quote=quote_out,
            branch=from_account.branch,
            description=description,
        )
        in_row = _row(
            company,
            **common,
            kind=Kind.TRANSFER,
            account=to_account,
            amount=amount_in,
            currency=to_account.currency,
            quote=quote_in,
            branch=to_account.branch,
            description=description,
        )
        deltas = {from_account.pk: -amount_out, to_account.pk: amount_in}
        if fee:
            _row(
                company,
                **common,
                kind=Kind.EXPENSE,
                account=from_account,
                amount=-fee,
                currency=from_account.currency,
                quote=quote_out,
                category=fee_category,
                branch=from_account.branch,
                description=description,
            )
            deltas[from_account.pk] -= fee
        difference = out_row.base_amount + in_row.base_amount
        if difference:
            _row(
                company,
                **common,
                kind=Kind.FX,
                amount=difference,
                currency=base,
                quote=RateQuote(ONE, False, "base"),
                category=_category(company, "fx_diff"),
                branch=from_account.branch or to_account.branch,
                description=description,
            )
        _move(locked, deltas)
        if source is None:
            _audit(
                FinanceAction.TRANSFER_MADE,
                company,
                user,
                moved,
                from_account=from_account.pk,
                to_account=to_account.pk,
                amount_out=str(amount_out),
                amount_in=str(amount_in),
                fee=str(fee),
            )
        return moved

    return _write_once(write, lambda: _posted_transfer(company, source), source)


@transaction.atomic
def void_transfer(transfer: Transfer, *, by: Membership, reason: str) -> Transfer:
    """Void a transfer and every row it made, putting both balances back."""
    _need_actor(by)
    reason = _reason(reason)
    moved = (
        Transfer.objects.select_for_update(of=("self",))
        .select_related("company")
        .get(pk=transfer.pk)
    )
    company = moved.company
    user = _actor(company, by)
    if moved.status != Transfer.Status.POSTED:
        raise DomainError(_("This transfer is already void."))
    _check_open(company, moved.occurred_on)
    rows = list(
        Transaction.objects.select_for_update()
        .filter(transfer=moved, status__in=LIVE_STATUSES)
        .order_by("pk")
    )
    _void_rows(rows, user=user, reason=reason)
    moved.status = Transfer.Status.VOID
    moved.voided_by = user
    moved.voided_at = timezone.now()
    moved.void_reason = reason
    moved.save(update_fields=["status", "voided_by", "voided_at", "void_reason", "updated_at"])
    _audit(FinanceAction.TRANSFER_VOIDED, company, user, moved, reason=reason)
    return moved


# Debts


@transaction.atomic
def open_debt(
    company,
    *,
    by: Membership | None,
    direction: str,
    kind: str,
    amount,
    currency: str,
    issued_on: date,
    counterparty=None,
    membership: Membership | None = None,
    due_on: date | None = None,
    account: MoneyAccount | None = None,
    category: Category | str | None = None,
    branch=None,
    description: str = "",
    responsible: Membership | None = None,
    is_opening: bool = False,
    source: Source | None = None,
    project=None,
) -> Debt:
    """Record money owed to the company (`receivable`) or by it (`payable`).

    The debt is owed by or to exactly one counterparty or employee. With `account`, money moved
    now: a loan given or an advance paid leaves the account, a loan taken arrives on it (a
    `debt_open` row). With `category`, something was earned or spent on credit: the income or
    expense is booked now as an accrual tied to the debt, with no account (an invoice, a salary,
    a reimbursement). With neither, only the debt is recorded (an opening debt from before the
    books moved here). The rate of the day is frozen on the debt.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    if source is not None and (found := _live_debt(company, source)) is not None:
        return found
    user = _actor(company, by)
    if direction not in Debt.Direction.values:
        raise ValueError(f"Unknown debt direction {direction!r}.")
    if kind not in Debt.Kind.values:
        raise ValueError(f"Unknown debt kind {kind!r}.")
    _check_currency(currency)
    if (counterparty is None) == (membership is None):
        raise DomainError(_("A debt is owed by or to one counterparty or one employee."))
    _same_company(company, counterparty, membership, account, branch, responsible, project)
    amount = _money(amount)
    if due_on is not None and due_on < issued_on:
        raise DomainError(_("The due date can't be before the day it was issued."))
    if account is not None and category is not None:
        raise DomainError(
            _("Pick an account (money moved now) or a category (earned or spent on credit).")
        )
    if is_opening and (account is not None or category is not None):
        raise DomainError(_("An opening debt moves no money and books no income or expense."))
    receivable = direction == Debt.Direction.RECEIVABLE
    if account is not None:
        _check_active(account)
        if account.currency != currency:
            raise DomainError(
                _("%(account)s holds %(currency)s.")
                % {"account": account, "currency": account.currency}
            )
    if category is not None:
        category = _category(
            company,
            category,
            kind=Category.Kind.INCOME if receivable else Category.Kind.EXPENSE,
            by=by,
        )
    if branch is None and account is not None and account.branch_id:
        branch = account.branch
    _check_open(company, issued_on)
    quote = _quote(company, currency, issued_on)
    description = (description or "").strip()[:300]

    def write() -> Debt:
        locked = _lock_accounts(account.pk if account is not None else None)
        debt = Debt.objects.create(
            company=company,
            direction=direction,
            kind=kind,
            counterparty=counterparty,
            membership=membership,
            currency=currency,
            amount=amount,
            rate=quote.rate,
            issued_on=issued_on,
            due_on=due_on,
            description=description,
            branch=branch,
            project=project,
            responsible=responsible,
            is_opening=is_opening,
            source_type=source.type if source else "",
            source_id=source.id if source else None,
            source_key=source.key if source else "",
            created_by=user,
        )
        common = {
            "user": user,
            "occurred_on": issued_on,
            "currency": currency,
            "quote": quote,
            "counterparty": counterparty,
            "membership": membership,
            "branch": branch,
            "project": project,
            "debt": debt,
            "debt_amount": amount,
            "description": description,
            "source": source,
        }
        if account is not None:
            signed = -amount if receivable else amount
            _row(company, **common, kind=Kind.DEBT_OPEN, account=account, amount=signed)
            _move(locked, {account.pk: signed})
        elif category is not None:
            accrual = Kind.INCOME if receivable else Kind.EXPENSE
            signed = amount if receivable else -amount
            _row(company, **common, kind=accrual, amount=signed, category=category)
        if source is None:
            _audit(
                FinanceAction.DEBT_OPENED,
                company,
                user,
                debt,
                sensitive=kind in Debt.SENSITIVE_KINDS,
                direction=direction,
                kind=kind,
                amount=str(amount),
                currency=currency,
            )
        return debt

    return _write_once(write, lambda: _live_debt(company, source), source)


@transaction.atomic
def pay_debt(
    debt: Debt,
    *,
    by: Membership | None,
    amount,
    paid_on: date,
    account: MoneyAccount | None = None,
    debt_amount=None,
    source: Source | None = None,
) -> Transaction:
    """Pay (part of) a debt: money arrives on `account` for a receivable, leaves it for a payable.

    `amount` is in the account's currency. When that differs from the debt's, `debt_amount`
    says how much of the debt it settles (default: `amount` at the company's rate for the day).
    Without an account the payment is an offset (a salary advance deducted on a payslip): it
    moves no money and is in the debt's currency. The settled part is valued at the debt's
    frozen rate; a payment worth more or less in the base currency books the difference as an
    `fx` row. A debt reserved with `lock_debt` takes payments only from that source.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    company = Debt.objects.select_related("company").get(pk=debt.pk).company
    if source is not None and (found := _live_row(company, source)) is not None:
        return found
    user = _actor(company, by)
    _same_company(company, account)
    if account is not None:
        _check_active(account)
    amount = _money(amount)
    debt_amount = _money(debt_amount) if debt_amount is not None else None
    base = company.base_currency

    def write() -> Transaction:
        locked_debt = _lock_debt(debt.pk)
        if locked_debt.status != Debt.Status.OPEN:
            raise DomainError(_("This debt is already settled or cancelled."))
        if locked_debt.is_locked and (
            source is None
            or (source.type, source.id) != (locked_debt.locked_by_type, locked_debt.locked_by_id)
        ):
            raise DomainError(_reserved_message(locked_debt))
        if paid_on < locked_debt.issued_on:
            raise DomainError(_("A debt can't be paid before the day it was issued."))
        _check_open(company, paid_on)
        if account is None:
            if debt_amount is not None and debt_amount != amount:
                raise DomainError(_("An offset is in the debt's currency: the amounts must match."))
            currency, settled = locked_debt.currency, amount
            quote = RateQuote(locked_debt.rate, False, "debt")
        elif account.currency == locked_debt.currency:
            if debt_amount is not None and debt_amount != amount:
                raise DomainError(_("In the debt's own currency the two amounts must match."))
            currency, settled = account.currency, amount
            quote = _quote(company, currency, paid_on)
        else:
            currency = account.currency
            quote = _quote(company, currency, paid_on)
            if debt_amount is not None:
                settled = debt_amount
            else:
                foreign = currency if currency != base else locked_debt.currency
                exchange = rate_for(company, foreign, paid_on).rate
                settled = convert(amount, currency, locked_debt.currency, exchange)
                if settled <= 0:
                    raise DomainError(_("That's too little to settle any of the debt."))
        left = locked_debt.amount - locked_debt.paid
        if settled > left:
            raise DomainError(
                _("That's more than the %(left)s still owed.")
                % {"left": _format(left, locked_debt.currency)}
            )
        sign = 1 if locked_debt.direction == Debt.Direction.RECEIVABLE else -1
        locked = _lock_accounts(account.pk if account is not None else None)
        branch = account.branch if account is not None and account.branch_id else locked_debt.branch
        common = {
            "user": user,
            "occurred_on": paid_on,
            "counterparty": locked_debt.counterparty,
            "membership": locked_debt.membership,
            "branch": branch,
            "project": locked_debt.project,
            "debt": locked_debt,
        }
        row = _row(
            company,
            **common,
            kind=Kind.DEBT_PAYMENT,
            account=account,
            amount=sign * amount,
            currency=currency,
            quote=quote,
            debt_amount=settled,
            source=source,
        )
        if account is not None:
            _move(locked, {account.pk: sign * amount})
        book_value = convert(settled, locked_debt.currency, base, locked_debt.rate)
        difference = row.base_amount - sign * book_value
        if difference:
            _row(
                company,
                **common,
                kind=Kind.FX,
                amount=difference,
                currency=base,
                quote=RateQuote(ONE, False, "base"),
                category=_category(company, "fx_diff"),
                source=Source(ROW_SOURCE, row.pk, "fx"),
            )
        locked_debt.paid += settled
        if locked_debt.paid == locked_debt.amount:
            locked_debt.status = Debt.Status.PAID
        locked_debt.save(update_fields=["paid", "status", "updated_at"])
        if source is None:
            _audit(
                FinanceAction.DEBT_PAID,
                company,
                user,
                locked_debt,
                sensitive=locked_debt.kind in Debt.SENSITIVE_KINDS,
                transaction=row.pk,
                amount=str(amount),
                currency=currency,
                debt_amount=str(settled),
            )
        return row

    return _write_once(write, lambda: _live_row(company, source), source)


@transaction.atomic
def write_off(debt: Debt, *, by: Membership, reason: str, amount=None) -> Transaction:
    """Give up on (part of) a debt today, at its book value: a receivable becomes a bad debt
    expense, a payable nobody will collect becomes other income."""
    _need_actor(by)
    reason = _reason(reason)
    locked_debt = _lock_debt(debt.pk)
    company = locked_debt.company
    user = _actor(company, by)
    if locked_debt.status != Debt.Status.OPEN:
        raise DomainError(_("This debt is already settled or cancelled."))
    if locked_debt.is_locked:
        raise DomainError(_reserved_message(locked_debt))
    left = locked_debt.amount - locked_debt.paid
    settled = _money(amount) if amount is not None else left
    if settled > left:
        raise DomainError(
            _("That's more than the %(left)s still owed.")
            % {"left": _format(left, locked_debt.currency)}
        )
    today = _local_today(company)
    _check_open(company, today)
    receivable = locked_debt.direction == Debt.Direction.RECEIVABLE
    row = _row(
        company,
        user=user,
        kind=Kind.WRITE_OFF,
        occurred_on=today,
        amount=-settled if receivable else settled,
        currency=locked_debt.currency,
        quote=RateQuote(locked_debt.rate, False, "debt"),
        category=_category(company, "bad_debts" if receivable else "other_income"),
        counterparty=locked_debt.counterparty,
        membership=locked_debt.membership,
        branch=locked_debt.branch,
        project=locked_debt.project,
        debt=locked_debt,
        debt_amount=settled,
        description=reason,
    )
    locked_debt.paid += settled
    if locked_debt.paid == locked_debt.amount:
        locked_debt.status = Debt.Status.WRITTEN_OFF
    locked_debt.save(update_fields=["paid", "status", "updated_at"])
    _audit(
        FinanceAction.DEBT_WRITTEN_OFF,
        company,
        user,
        locked_debt,
        sensitive=locked_debt.kind in Debt.SENSITIVE_KINDS,
        amount=str(settled),
        reason=reason,
    )
    return row


@transaction.atomic
def cancel_debt(debt: Debt, *, by: Membership, reason: str) -> Debt:
    """Cancel a debt recorded by mistake: every row it has (the accrual or the money that moved
    when it opened, payments, write-offs, exchange differences) is voided and balances move
    back. A reserved debt is released by its source first."""
    _need_actor(by)
    reason = _reason(reason)
    locked_debt = _lock_debt(debt.pk)
    company = locked_debt.company
    user = _actor(company, by)
    if locked_debt.status == Debt.Status.CANCELLED:
        raise DomainError(_("This debt is already cancelled."))
    if locked_debt.is_locked:
        raise DomainError(_reserved_message(locked_debt))
    rows = list(
        Transaction.objects.select_for_update()
        .filter(debt=locked_debt, status__in=LIVE_STATUSES)
        .order_by("pk")
    )
    _check_open(company, locked_debt.issued_on, *(row.occurred_on for row in rows))
    _void_rows(rows, user=user, reason=reason)
    locked_debt.status = Debt.Status.CANCELLED
    locked_debt.paid = ZERO
    locked_debt.save(update_fields=["status", "paid", "updated_at"])
    _audit(
        FinanceAction.DEBT_CANCELLED,
        company,
        user,
        locked_debt,
        sensitive=locked_debt.kind in Debt.SENSITIVE_KINDS,
        reason=reason,
    )
    return locked_debt


@transaction.atomic
def lock_debt(debt: Debt, *, source: Source) -> Debt:
    """Reserve an open debt for `source` (a finalized payslip that will pay it): until it's
    unlocked, only payments from that source are taken and nobody writes it off or cancels it.
    Locking again for the same source changes nothing."""
    source = sources.check(source)
    if source is None:
        raise ValueError("lock_debt needs a source.")
    locked_debt = _lock_debt(debt.pk)
    if locked_debt.is_locked:
        if (locked_debt.locked_by_type, locked_debt.locked_by_id) == (source.type, source.id):
            return locked_debt
        raise DomainError(_reserved_message(locked_debt))
    if locked_debt.status != Debt.Status.OPEN:
        raise DomainError(_("This debt is already settled or cancelled."))
    locked_debt.locked_by_type = source.type
    locked_debt.locked_by_id = source.id
    locked_debt.save(update_fields=["locked_by_type", "locked_by_id", "updated_at"])
    return locked_debt


@transaction.atomic
def unlock_debt(debt: Debt, *, source: Source) -> Debt:
    """Release a debt `source` reserved. Unlocking a debt nobody reserved changes nothing."""
    source = sources.check(source)
    if source is None:
        raise ValueError("unlock_debt needs a source.")
    locked_debt = _lock_debt(debt.pk)
    if not locked_debt.is_locked:
        return locked_debt
    if (locked_debt.locked_by_type, locked_debt.locked_by_id) != (source.type, source.id):
        raise DomainError(_reserved_message(locked_debt))
    locked_debt.locked_by_type = ""
    locked_debt.locked_by_id = None
    locked_debt.save(update_fields=["locked_by_type", "locked_by_id", "updated_at"])
    return locked_debt


# Helpers


def _need_actor(by) -> None:
    if by is None:
        raise ValueError("This change is made by a person: pass by=<Membership>.")


def _need_actor_or_source(by, source) -> None:
    if by is None and source is None:
        raise ValueError("A system write to the ledger needs an idempotency source.")


def _actor(company, by: Membership | None):
    """The user behind `by` (None for the system), after checking `by` is of this company."""
    if by is None:
        return None
    if not isinstance(by, Membership):
        raise TypeError(f"by is a Membership or None, not {type(by).__name__}.")
    if by.company_id != company.pk:
        raise DomainError(_("Everything in a ledger entry must belong to the same company."))
    return by.user


def _same_company(company, *objects) -> None:
    for obj in objects:
        if obj is not None and obj.company_id != company.pk:
            raise DomainError(_("Everything in a ledger entry must belong to the same company."))


def _check_currency(currency) -> None:
    if currency not in Currency.values:
        raise ValueError(f"Unknown currency {currency!r}.")


def _check_active(account: MoneyAccount) -> None:
    if not account.is_active:
        raise DomainError(_("%(account)s is archived.") % {"account": account})


def _money(value, *, signed: bool = False, allow_zero: bool = False) -> Decimal:
    """An amount from the caller: a positive Decimal of cents (any sign when `signed`)."""
    if isinstance(value, float):
        value = str(value)
    try:
        amount = quantize(Decimal(value))
    except InvalidOperation, TypeError, ValueError:
        raise DomainError(_("Enter an amount of money.")) from None
    if not amount.is_finite():
        raise DomainError(_("Enter an amount of money."))
    if abs(amount) > MAX_AMOUNT:
        raise DomainError(_("This amount is too large."))
    if amount == 0 and not allow_zero:
        raise DomainError(_("The amount can't be zero."))
    if amount < 0 and not signed:
        raise DomainError(_("Enter the amount without a minus sign."))
    return amount


def _rate(value) -> Decimal:
    try:
        rate = Decimal(str(value) if isinstance(value, float) else value)
    except InvalidOperation, TypeError, ValueError:
        raise DomainError(_("Enter an exchange rate.")) from None
    if not rate.is_finite() or rate <= 0:
        raise DomainError(_("An exchange rate is more than zero."))
    return rate.quantize(Decimal("0.000001"))


def _implied_rate(from_currency: str, amount_out: Decimal, amount_in: Decimal) -> Decimal:
    """UZS per 1 USD implied by the two sides of a cross-currency transfer."""
    som, dollars = (
        (amount_out, amount_in) if from_currency == Currency.UZS else (amount_in, amount_out)
    )
    return _rate(som / dollars)


def _reason(reason: str) -> str:
    reason = (reason or "").strip()[:300]
    if not reason:
        raise DomainError(_("Say why."))
    return reason


def _local_today(company) -> date:
    return timezone.localdate(timezone=ZoneInfo(company.timezone))


def _check_open(company, *days: date) -> None:
    """Refuse dates on or before the period lock."""
    locked_until = conf.get_settings(company).locked_until
    if locked_until is not None and any(day <= locked_until for day in days):
        raise DomainError(
            _("The books are closed up to %(date)s. Pick a later date or reopen the period.")
            % {"date": locked_until.strftime("%d.%m.%Y")}
        )


def _quote(company, currency: str, day: date, rate=None) -> RateQuote:
    if currency == company.base_currency:
        if rate is not None and _rate(rate) != ONE:
            raise DomainError(_("Amounts in the base currency need no exchange rate."))
        return RateQuote(ONE, False, "base")
    if rate is not None:
        return RateQuote(_rate(rate), False, "given")
    return rate_for(company, currency, day)


def _side_quote(company, currency: str, day: date, exchange_rate) -> RateQuote:
    """The rate one side of a transfer is valued at: the company's for the day, or the
    transfer's own exchange rate when there is no rate at all yet."""
    try:
        return _quote(company, currency, day)
    except DomainError:
        if exchange_rate is None or quoted_currency(company.base_currency, currency) is None:
            raise
        return RateQuote(exchange_rate, False, "given")


def _category(company, category, *, kind: str | None = None, by=None) -> Category:
    """`category` (a Category or a system_code) after checking its company and kind."""
    if category is None:
        raise DomainError(_("Pick a category."))
    if isinstance(category, str):
        code = category
        rows = Category.objects.filter(company=company, system_code=code)
        category = rows.first()
        if category is None and code in defaults.SYSTEM_CODES:
            defaults.ensure(company)  # a company made before its defaults were
            category = rows.first()
        if category is None:
            raise ValueError(f"No category with system code {code!r}.")
    elif not isinstance(category, Category):
        raise TypeError(f"category is a Category or a system code, not {type(category).__name__}.")
    else:
        _same_company(company, category)
        if by is not None and not category.is_active:
            raise DomainError(_("The category %(category)s is archived.") % {"category": category})
    if kind is not None and category.kind != kind:
        if kind == Kind.INCOME:
            raise DomainError(_("Pick an income category."))
        raise DomainError(_("Pick an expense category."))
    return category


def _lock_accounts(*ids: int | None) -> dict[int, MoneyAccount]:
    """Lock the accounts in id order (one global order, so two writes never deadlock)."""
    wanted = sorted({pk for pk in ids if pk is not None})
    if not wanted:
        return {}
    return {
        account.pk: account
        for account in MoneyAccount.objects.select_for_update().filter(pk__in=wanted).order_by("pk")
    }


def _move(locked: dict[int, MoneyAccount], deltas: dict[int, Decimal], *, check=True) -> None:
    """Add `deltas` to the locked accounts' balances. With `check`, an account that doesn't
    allow it may not go below zero."""
    now = timezone.now()
    for pk in sorted(deltas):
        delta = deltas[pk]
        if not delta:
            continue
        account = locked[pk]
        new_balance = account.balance + delta
        if check and delta < 0 and new_balance < 0 and not account.allow_negative:
            raise DomainError(
                _("Not enough money on %(account)s: %(balance)s left.")
                % {"account": account, "balance": _format(account.balance, account.currency)}
            )
        MoneyAccount.objects.filter(pk=pk).update(balance=F("balance") + delta, updated_at=now)
        account.balance = new_balance


def _void_rows(rows: list[Transaction], *, user, reason: str) -> None:
    """Void `rows` (already locked) and take the posted ones off their accounts."""
    deltas: dict[int, Decimal] = {}
    for row in rows:
        if row.status == Status.POSTED and row.account_id is not None:
            deltas[row.account_id] = deltas.get(row.account_id, ZERO) - row.amount
    locked = _lock_accounts(*deltas)
    now = timezone.now()
    for row in rows:
        row.status = Status.VOID
        row.voided_by = user
        row.voided_at = now
        row.void_reason = reason
        row.save(update_fields=["status", "voided_by", "voided_at", "void_reason", "updated_at"])
    _move(locked, deltas, check=False)


def _follow_ups(company, row: Transaction) -> list[Transaction]:
    """Rows the ledger made because of `row` (its exchange difference), locked."""
    return list(
        Transaction.objects.select_for_update()
        .filter(
            company=company,
            source_type=ROW_SOURCE,
            source_id=row.pk,
            status__in=LIVE_STATUSES,
        )
        .order_by("pk")
    )


def _lock_row(txn: Transaction) -> Transaction:
    return (
        Transaction.objects.select_for_update(of=("self",)).select_related("company").get(pk=txn.pk)
    )


def _lock_debt(pk: int) -> Debt:
    return Debt.objects.select_for_update(of=("self",)).select_related("company").get(pk=pk)


def _row(
    company,
    *,
    user,
    kind: str,
    amount: Decimal,
    occurred_on: date,
    currency: str,
    quote: RateQuote,
    status: str = Status.POSTED,
    account=None,
    category=None,
    counterparty=None,
    membership=None,
    branch=None,
    project=None,
    debt=None,
    debt_amount=None,
    transfer=None,
    is_contra: bool = False,
    description: str = "",
    source: Source | None = None,
) -> Transaction:
    return Transaction.objects.create(
        company=company,
        kind=kind,
        status=status,
        occurred_on=occurred_on,
        account=account,
        amount=amount,
        currency=currency,
        rate=quote.rate,
        rate_stale=quote.stale,
        base_amount=convert(amount, currency, company.base_currency, quote.rate),
        category=category,
        counterparty=counterparty,
        membership=membership,
        branch=branch,
        project=project,
        debt=debt,
        debt_amount=debt_amount,
        transfer=transfer,
        is_contra=is_contra,
        description=(description or "").strip()[:300],
        source_type=source.type if source else "",
        source_id=source.id if source else None,
        source_key=source.key if source else "",
        created_by=user,
    )


def _write_once(write, find, source: Source | None):
    """Run `write()`. With a source, a concurrent call that booked it first wins: its rows come
    back instead of an error."""
    if source is None:
        return write()
    try:
        with transaction.atomic():
            return write()
    except IntegrityError:
        found = find()
        if found is None:
            raise
        return found


def _source_filter(source: Source) -> dict:
    return {"source_type": source.type, "source_id": source.id, "source_key": source.key}


def _live_row(company, source: Source) -> Transaction | None:
    return (
        Transaction.objects.filter(
            company=company, status__in=LIVE_STATUSES, **_source_filter(source)
        )
        .order_by("pk")
        .first()
    )


def _posted_transfer(company, source: Source) -> Transfer | None:
    return Transfer.objects.filter(
        company=company, status=Transfer.Status.POSTED, **_source_filter(source)
    ).first()


def _live_debt(company, source: Source) -> Debt | None:
    return (
        Debt.objects.filter(company=company, **_source_filter(source))
        .exclude(status=Debt.Status.CANCELLED)
        .first()
    )


def _same_source(debt: Debt, row: Transaction) -> bool:
    return (row.source_type, row.source_id) == (debt.locked_by_type, debt.locked_by_id)


def _reserved_message(debt: Debt) -> str:
    return _("This debt is reserved by %(source)s #%(id)s.") % {
        "source": sources.label(debt.locked_by_type),
        "id": debt.locked_by_id,
    }


def _format(amount: Decimal, currency: str) -> str:
    language = (translation.get_language() or "en")[:2]
    return format_money(amount, currency, language)


def _is_sensitive(row: Transaction) -> bool:
    """Per-person detail of salaries, advances and reimbursements needs payroll.view."""
    if row.category_id is not None and row.category.is_sensitive:
        return True
    return row.debt_id is not None and row.debt.kind in Debt.SENSITIVE_KINDS


def _row_details(row: Transaction) -> dict:
    return {
        "kind": row.kind,
        "amount": str(row.amount),
        "currency": row.currency,
        "occurred_on": row.occurred_on.isoformat(),
        "account": row.account_id,
    }


def _audit(action, company, user, target, *, sensitive: bool = False, **details) -> None:
    audit.record(
        action,
        company_id=company.pk,
        actor=user,
        target=target,
        required_perm=Perm.PAYROLL_VIEW if sensitive else Perm.FINANCE_VIEW,
        **details,
    )
