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
- One source (type, id, key) books one thing: a repeat that doesn't match what the source
  booked (another debt, account or kind) raises `ValueError` instead of returning it.
- Every write is atomic, checks that everything it links belongs to the company, refuses dates
  on or before `FinanceSettings.locked_until`, locks rows in one global order (the company's
  finance settings row FOR SHARE, then debt, transfer, transaction, then accounts by id) and
  moves balances with `F()` under those locks. The share lock on the settings row makes closing
  a period wait for the writes already running, so nothing lands in a period being closed.
- Each row freezes its rate and `base_amount`. Settling a debt at another value than it was
  opened at (another currency, or the same foreign currency at another rate) books the
  difference as an `fx` row, and so does a cross-currency transfer whose two sides differ in
  the base currency. What a settlement takes off a debt is valued as the difference of the
  running totals at the debt's rate, so the parts of a debt add up to its whole to the tiyin.
- Services don't check permissions: the API, the bots and the calling module do.
- Person-made changes without a source are audited here; sourced writes are part of an action
  their module audits (the rows keep `created_by` and the source either way).
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import IntegrityError, connection, transaction
from django.db.models import F, Max, ProtectedError, RestrictedError
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.core.exceptions import DomainError
from apps.core.money import Currency, format_money, quantize
from apps.core.uploads import accept_document, make_thumb
from apps.finance import conf, defaults, sources
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    COLOR_PATTERN,
    LIVE_STATUSES,
    Category,
    CompanyRate,
    Counterparty,
    Debt,
    DebtInstallment,
    FinanceSettings,
    MoneyAccount,
    RateSource,
    Receipt,
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
    "archive_account",
    "attach_receipts",
    "bulk_transactions",
    "cancel_debt",
    "copy_categories",
    "create_account",
    "create_category",
    "create_counterparty",
    "create_defaults",
    "delete_category",
    "delete_company_rate",
    "get_settings",
    "lock_debt",
    "lock_period",
    "merge_category",
    "move_category",
    "normalize_phone",
    "open_debt",
    "pay_debt",
    "rate_for",
    "record_entry",
    "record_transaction",
    "reject_transaction",
    "remove_receipt",
    "reopen_account",
    "set_company_rate",
    "set_installments",
    "transfer",
    "unlock_debt",
    "update_account",
    "update_category",
    "update_counterparty",
    "update_debt",
    "update_settings",
    "update_transaction",
    "upload_receipt",
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
MAX_AMOUNT = Decimal("9999999999999999.99")  # what Decimal(18, 2) holds
MAX_RATE = Decimal("999999999999.999999")  # what Decimal(18, 6) holds
RATE_STEP = Decimal("0.000001")
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
    a fee on a loan) and never settles it, so `debt_amount` is refused: payments go through
    `pay_debt`, and earning or spending on credit through `open_debt`. `status="pending"` books
    an income or expense that moves no balance until `approve_transaction`. Without `rate` the
    company's rate for the day is used.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    booked = {"kind": kind, "account_id": account.pk if account is not None else None}
    if source is not None and (found := _live_row(company, source)) is not None:
        return _same_booking(found, source, booked)
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
    if debt_amount is not None:
        raise ValueError(
            "record_transaction never settles a debt (debt only links the row): pay it with "
            "pay_debt, which takes debt_amount."
        )
    if debt is not None and debt.status == Debt.Status.CANCELLED:
        raise DomainError(_("This debt was cancelled."))
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
        if posted:
            _check_active(locked[account.pk])
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

    return _write_once(
        write, lambda: _same_booking(_live_row(company, source), source, booked), source
    )


@transaction.atomic
def approve_transaction(txn: Transaction, *, by: Membership) -> Transaction:
    """Post a pending entry: it now moves its account's balance."""
    _need_actor(by)
    company = txn.company
    user = _actor(company, by)
    _hold_books(company)
    txn = _lock_row(txn)
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
    _hold_books(company)
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
    booked = {"from_account_id": from_account.pk, "to_account_id": to_account.pk}
    if source is not None and (found := _posted_transfer(company, source)) is not None:
        return _same_booking(found, source, booked)
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
        _check_size(amount_in)
    _check_open(company, occurred_on)
    quote_out = _side_quote(company, from_account.currency, occurred_on, exchange_rate)
    quote_in = _side_quote(company, to_account.currency, occurred_on, exchange_rate)
    fee_category = _category(company, "bank_fees", kind=Category.Kind.EXPENSE) if fee else None
    description = (description or "").strip()[:300]

    def write() -> Transfer:
        locked = _lock_accounts(from_account.pk, to_account.pk)
        _check_active(locked[from_account.pk])
        _check_active(locked[to_account.pk])
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

    return _write_once(
        write, lambda: _same_booking(_posted_transfer(company, source), source, booked), source
    )


@transaction.atomic
def void_transfer(transfer: Transfer, *, by: Membership, reason: str) -> Transfer:
    """Void a transfer and every row it made, putting both balances back."""
    _need_actor(by)
    reason = _reason(reason)
    company = transfer.company
    user = _actor(company, by)
    _hold_books(company)
    moved = (
        Transfer.objects.select_for_update(of=("self",))
        .select_related("company")
        .get(pk=transfer.pk)
    )
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
    a reimbursement). With neither, only the debt is recorded: that is an opening debt from
    before the books moved here, so it needs `is_opening=True` (a debt that is neither would
    later bring in or pay out money that no income or expense ever accounted for). The rate of
    the day is frozen on the debt.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    booked = {
        "direction": direction,
        "kind": kind,
        "currency": currency,
        "counterparty_id": counterparty.pk if counterparty is not None else None,
        "membership_id": membership.pk if membership is not None else None,
    }
    if source is not None and (found := _live_debt(company, source)) is not None:
        return _same_booking(found, source, booked)
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
    if not is_opening and account is None and category is None:
        raise DomainError(
            _(
                "Pick an account (money moved now) or a category (earned or spent on credit), "
                "or record it as an opening debt."
            )
        )
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
        if account is not None:
            _check_active(locked[account.pk])
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

    return _write_once(
        write, lambda: _same_booking(_live_debt(company, source), source, booked), source
    )


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

    One source pays one debt once, so a payslip that pays several debts gives each its own key.
    """
    _need_actor_or_source(by, source)
    source = sources.check(source)
    company = Debt.objects.select_related("company").get(pk=debt.pk).company
    booked = {"kind": Kind.DEBT_PAYMENT, "debt_id": debt.pk}
    if source is not None and (found := _live_row(company, source)) is not None:
        return _same_booking(found, source, booked)
    user = _actor(company, by)
    _same_company(company, account)
    if account is not None:
        _check_active(account)
    amount = _money(amount)
    debt_amount = _money(debt_amount) if debt_amount is not None else None
    base = company.base_currency
    _check_open(company, paid_on)

    def write() -> Transaction:
        locked_debt = _lock_debt(debt.pk)
        # A retry racing the first call waited for the debt's lock: what it booked is visible now
        # (a full payment would otherwise read as "already settled").
        if source is not None and (found := _live_row(company, source)) is not None:
            return _same_booking(found, source, booked)
        if locked_debt.status != Debt.Status.OPEN:
            raise DomainError(_("This debt is already settled or cancelled."))
        if locked_debt.is_locked and (
            source is None
            or (source.type, source.id) != (locked_debt.locked_by_type, locked_debt.locked_by_id)
        ):
            raise DomainError(_reserved_message(locked_debt))
        if paid_on < locked_debt.issued_on:
            raise DomainError(_("A debt can't be paid before the day it was issued."))
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
        if account is not None:
            _check_active(locked[account.pk])
        book_value = _book_value(locked_debt, settled)
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
            # An offset moves no money: it takes exactly its book value off the debt.
            base_amount=sign * book_value if account is None else None,
            debt_amount=settled,
            source=source,
        )
        if account is not None:
            _move(locked, {account.pk: sign * amount})
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

    return _write_once(
        write, lambda: _same_booking(_live_row(company, source), source, booked), source
    )


@transaction.atomic
def write_off(debt: Debt, *, by: Membership, reason: str, amount=None) -> Transaction:
    """Give up on (part of) a debt today, at its book value: a receivable becomes a bad debt
    expense, a payable nobody will collect becomes other income."""
    _need_actor(by)
    reason = _reason(reason)
    company = debt.company
    user = _actor(company, by)
    today = _local_today(company)
    _check_open(company, today)
    locked_debt = _lock_debt(debt.pk)
    if locked_debt.status != Debt.Status.OPEN:
        raise DomainError(_("This debt is already settled or cancelled."))
    if locked_debt.is_locked:
        raise DomainError(_reserved_message(locked_debt))
    if today < locked_debt.issued_on:
        raise DomainError(_("A debt can't be written off before the day it was issued."))
    left = locked_debt.amount - locked_debt.paid
    settled = _money(amount) if amount is not None else left
    if settled > left:
        raise DomainError(
            _("That's more than the %(left)s still owed.")
            % {"left": _format(left, locked_debt.currency)}
        )
    receivable = locked_debt.direction == Debt.Direction.RECEIVABLE
    book_value = _book_value(locked_debt, settled)
    row = _row(
        company,
        user=user,
        kind=Kind.WRITE_OFF,
        occurred_on=today,
        amount=-settled if receivable else settled,
        currency=locked_debt.currency,
        quote=RateQuote(locked_debt.rate, False, "debt"),
        base_amount=-book_value if receivable else book_value,
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
    company = debt.company
    user = _actor(company, by)
    _hold_books(company)
    locked_debt = _lock_debt(debt.pk)
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


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The bookkeeping services of the owner dashboard (Package D). Everything below is made by a
# person (`by` is required) and audited here; the ledger rules above still apply underneath.
# ─────────────────────────────────────────────────────────────────────────────────────────────

ACCOUNT_FIELDS = (
    "name",
    "color",
    "order",
    "bank_name",
    "number_last4",
    "allow_negative",
    "branch",
    "operators",
)
CATEGORY_FIELDS = ("name", "color", "icon", "is_capex", "is_sensitive", "is_active")
PARTY_FIELDS = (
    "name",
    "kind",
    "phone",
    "tin",
    "contact_person",
    "telegram_username",
    "address",
    "bank_details",
    "notes",
    "default_category",
    "credit_limit",
    "credit_blocked",
    "birthday",
    "tags",
    "is_active",
)
TRANSACTION_FIELDS = (
    "description",
    "category",
    "counterparty",
    "membership",
    "branch",
    "project",
    "occurred_on",
    "amount",
    "account",
)
MONEY_CHANGES = ("occurred_on", "amount", "account")
SETTINGS_FIELDS = (
    "rate_source",
    "approval_threshold",
    "receipt_required_over",
    "large_expense_alert",
    "reimburse_via",
)
DEBT_FIELDS = ("due_on", "description", "responsible", "branch")
BULK_ACTIONS = ("categorize", "void")
MAX_BULK = 200
MAX_RECEIPTS = 10
MAX_TAGS = 10
MAX_INSTALLMENTS = 60
PHONE_DIGITS = re.compile(r"\D+")


# Accounts


@transaction.atomic
def update_account(account: MoneyAccount, *, by: Membership, **fields) -> MoneyAccount:
    """Change an account's name, colour, order, bank details, overdraft rule, branch or the
    people who operate it. Its kind, currency and holder never change (archive it and open
    another instead), so its history keeps meaning what it meant."""
    _need_actor(by)
    _known(fields, ACCOUNT_FIELDS)
    account = MoneyAccount.objects.select_for_update().select_related("company").get(pk=account.pk)
    company = account.company
    user = _actor(company, by)
    before = _account_snapshot(account)
    if "name" in fields:
        name = (fields["name"] or "").strip()[:100]
        if not name:
            raise DomainError(_("Give the account a name."))
        taken = MoneyAccount.objects.filter(company=company, name__iexact=name)
        if taken.exclude(pk=account.pk).exists():
            raise DomainError(_("There is already an account called %(name)s.") % {"name": name})
        account.name = name
    if "color" in fields:
        account.color = _color(fields["color"])
    if "order" in fields:
        account.order = max(0, int(fields["order"] or 0))
    if "bank_name" in fields:
        account.bank_name = (fields["bank_name"] or "").strip()[:100]
    if "number_last4" in fields:
        last4 = (fields["number_last4"] or "").strip()
        if last4 and not re.fullmatch(r"\d{4}", last4):
            raise DomainError(_("Only the last 4 digits."))
        account.number_last4 = last4
    if "allow_negative" in fields:
        account.allow_negative = bool(fields["allow_negative"])
    if "branch" in fields:
        branch = fields["branch"]
        _same_company(company, branch)
        if account.kind == MoneyAccount.Kind.SAFE and branch is not None:
            clash = MoneyAccount.objects.filter(
                company=company, branch=branch, kind=account.kind, currency=account.currency
            ).exclude(pk=account.pk)
            if clash.exists():
                raise DomainError(
                    _("%(branch)s already has a safe in %(currency)s.")
                    % {"branch": branch, "currency": account.currency}
                )
        account.branch = branch
    account.save()
    if "operators" in fields:
        operators = list(fields["operators"] or [])
        _same_company(company, *operators)
        account.operators.set(operators)
    changes = _diff(before, _account_snapshot(account))
    if changes:
        _audit(FinanceAction.ACCOUNT_UPDATED, company, user, account, changes=changes)
    return account


@transaction.atomic
def archive_account(account: MoneyAccount, *, by: Membership) -> MoneyAccount:
    """Hide an account that is no longer used. Its balance must be zero: move the money first."""
    _need_actor(by)
    company = account.company
    user = _actor(company, by)
    locked = _lock_accounts(account.pk)[account.pk]
    if not locked.is_active:
        return locked
    if locked.balance:
        raise DomainError(
            _("%(account)s still holds %(balance)s. Move the money to another account first.")
            % {"account": locked, "balance": _format(locked.balance, locked.currency)}
        )
    if Transaction.objects.filter(account=locked, status=Status.PENDING).exists():
        raise DomainError(_("Entries on this account wait for approval: decide them first."))
    locked.is_active = False
    locked.save(update_fields=["is_active", "updated_at"])
    _audit(FinanceAction.ACCOUNT_ARCHIVED, company, user, locked)
    return locked


@transaction.atomic
def reopen_account(account: MoneyAccount, *, by: Membership) -> MoneyAccount:
    _need_actor(by)
    company = account.company
    user = _actor(company, by)
    if account.is_active:
        return account
    account.is_active = True
    account.save(update_fields=["is_active", "updated_at"])
    _audit(FinanceAction.ACCOUNT_REOPENED, company, user, account)
    return account


def _account_snapshot(account: MoneyAccount) -> dict:
    snapshot = {
        "name": account.name,
        "color": account.color,
        "order": account.order,
        "bank_name": account.bank_name,
        "number_last4": account.number_last4,
        "allow_negative": account.allow_negative,
        "branch": str(account.branch) if account.branch_id else None,
    }
    if account.pk:
        snapshot["operators"] = sorted(str(person) for person in account.operators.all())
    return snapshot


# Categories


@transaction.atomic
def create_category(
    company,
    *,
    by: Membership,
    name: str,
    kind: str,
    parent: Category | None = None,
    color: str = "",
    icon: str = "",
    is_capex: bool = False,
    is_sensitive: bool = False,
) -> Category:
    """A new income or expense category, at the top or under a top-level one of its kind."""
    _need_actor(by)
    user = _actor(company, by)
    if kind not in Category.Kind.values:
        raise ValueError(f"Unknown category kind {kind!r}.")
    name = _category_name(name)
    _check_parent(company, parent, kind)
    _check_free_name(company, parent, name)
    order = Category.objects.filter(company=company, parent=parent, kind=kind).aggregate(
        top=Max("order")
    )["top"]
    try:
        with transaction.atomic():
            category = Category.objects.create(
                company=company,
                name=name,
                kind=kind,
                parent=parent,
                color=_color(color),
                icon=(icon or "").strip()[:40],
                is_capex=bool(is_capex),
                is_sensitive=bool(is_sensitive),
                order=(order + 1) if order is not None else 0,
            )
    except IntegrityError:
        raise DomainError(
            _("There is already a category called %(name)s here.") % {"name": name}
        ) from None
    _audit(FinanceAction.CATEGORY_CREATED, company, user, category, name=name, kind=kind)
    return category


@transaction.atomic
def update_category(category: Category, *, by: Membership, **fields) -> Category:
    """Rename or recolour a category, flag it as equipment (capex) or salary-sensitive, or
    archive it (with its subcategories). System categories can be renamed, never archived; the
    salaries category always stays sensitive."""
    _need_actor(by)
    _known(fields, CATEGORY_FIELDS)
    category = Category.objects.select_for_update().select_related("company").get(pk=category.pk)
    company = category.company
    user = _actor(company, by)
    before = _category_snapshot(category)
    if "name" in fields:
        name = _category_name(fields["name"])
        if name.lower() != category.name.lower():
            _check_free_name(company, category.parent, name, exclude=category)
        category.name = name
    if "color" in fields:
        category.color = _color(fields["color"])
    if "icon" in fields:
        category.icon = (fields["icon"] or "").strip()[:40]
    if "is_capex" in fields:
        category.is_capex = bool(fields["is_capex"])
    if "is_sensitive" in fields:
        sensitive = bool(fields["is_sensitive"])
        if category.system_code == "salaries" and not sensitive:
            raise DomainError(_("Salaries always stay hidden from people without payroll access."))
        category.is_sensitive = sensitive
    if "is_active" in fields:
        active = bool(fields["is_active"])
        if not active and category.system_code:
            raise DomainError(_("System categories can be renamed, but not archived or deleted."))
        if not active and category.children.filter(system_code__gt="").exists():
            raise DomainError(_("A system category sits under this one: move it out first."))
        category.is_active = active
        if not active:
            category.children.update(is_active=False, updated_at=timezone.now())
    try:
        with transaction.atomic():
            category.save()
    except IntegrityError:
        raise DomainError(
            _("There is already a category called %(name)s here.") % {"name": category.name}
        ) from None
    changes = _diff(before, _category_snapshot(category))
    if changes:
        _audit(FinanceAction.CATEGORY_UPDATED, company, user, category, changes=changes)
    return category


@transaction.atomic
def move_category(
    category: Category, *, by: Membership, parent: Category | None, index: int
) -> Category:
    """Drag a category in the tree: to another top-level parent of its kind (or to the top),
    at `index` among its new siblings. Categories go two levels deep at most."""
    _need_actor(by)
    category = Category.objects.select_for_update().select_related("company").get(pk=category.pk)
    company = category.company
    user = _actor(company, by)
    if parent is not None:
        if parent.pk == category.pk:
            raise DomainError(_("Categories go two levels deep at most."))
        _check_parent(company, parent, category.kind)
        if category.children.exists():
            raise DomainError(_("A category with subcategories stays at the top."))
    if (parent.pk if parent else None) != category.parent_id:
        _check_free_name(company, parent, category.name, exclude=category)
    old_parent = str(category.parent) if category.parent_id else None
    siblings = list(
        Category.objects.select_for_update()
        .filter(company=company, parent=parent, kind=category.kind)
        .exclude(pk=category.pk)
        .order_by("order", "name", "pk")
    )
    index = max(0, min(int(index), len(siblings)))
    siblings.insert(index, category)
    category.parent = parent
    category.save(update_fields=["parent", "updated_at"])
    for position, sibling in enumerate(siblings):
        if sibling.order != position:
            Category.objects.filter(pk=sibling.pk).update(order=position)
            sibling.order = position
    _audit(
        FinanceAction.CATEGORY_MOVED,
        company,
        user,
        category,
        changes={"parent": [old_parent, str(parent) if parent else None]},
    )
    return category


@transaction.atomic
def merge_category(source: Category, *, into: Category, by: Membership) -> Category:
    """Fold `source` into `into`: its entries, subcategories and counterparty defaults move
    over and `source` is deleted. Entries in a closed period keep their category, so a merge
    that would change them is refused."""
    _need_actor(by)
    company = source.company
    user = _actor(company, by)
    _same_company(company, into)
    locked_until = _hold_books(company)
    source = Category.objects.select_for_update().get(pk=source.pk)
    into = Category.objects.select_for_update().get(pk=into.pk)
    if source.pk == into.pk:
        raise DomainError(_("Pick another category to merge into."))
    if source.kind != into.kind:
        raise DomainError(
            _("Merge an income category into an income one, an expense into an expense.")
        )
    if source.system_code:
        raise DomainError(_("System categories can be renamed, but not merged away."))
    if into.parent_id == source.pk:
        raise DomainError(_("Pick a category outside this one."))
    children = list(source.children.all())
    if children and into.parent_id is not None:
        raise DomainError(_("This category has subcategories: merge it into a top-level one."))
    rows = Transaction.objects.filter(category=source)
    if locked_until is not None and rows.filter(occurred_on__lte=locked_until).exists():
        raise DomainError(
            _("Entries up to %(date)s use this category and the books are closed for them.")
            % {"date": locked_until.strftime("%d.%m.%Y")}
        )
    names = set(Category.objects.filter(parent=into).values_list("name", flat=True))
    for child in children:
        if child.name in names:
            raise DomainError(
                _("%(into)s already has a subcategory called %(name)s.")
                % {"into": into, "name": child.name}
            )
    moved = rows.update(category=into, updated_at=timezone.now())
    for child in children:
        child.parent = into
        child.save(update_fields=["parent", "updated_at"])
    Counterparty.objects.filter(default_category=source).update(default_category=into)
    name = source.name
    _audit(
        FinanceAction.CATEGORY_MERGED,
        company,
        user,
        into,
        merged=name,
        entries=moved,
        subcategories=len(children),
    )
    source.delete()
    return into


@transaction.atomic
def delete_category(category: Category, *, by: Membership) -> None:
    """Delete a category nothing uses. One with entries is merged or archived instead."""
    _need_actor(by)
    company = category.company
    user = _actor(company, by)
    category = Category.objects.select_for_update().get(pk=category.pk)
    if category.system_code:
        raise DomainError(_("System categories can be renamed, but not archived or deleted."))
    if category.children.exists():
        raise DomainError(_("Move or delete its subcategories first."))
    if Transaction.objects.filter(category=category).exists():
        raise DomainError(_("This category has entries: merge it into another or archive it."))
    _audit(
        FinanceAction.CATEGORY_DELETED,
        company,
        user,
        category,
        name=category.name,
        kind=category.kind,
    )
    try:
        with transaction.atomic():
            Counterparty.objects.filter(default_category=category).update(default_category=None)
            category.delete()
    except ProtectedError, RestrictedError:
        raise DomainError(_("This category is still in use: archive it instead.")) from None


def copy_categories(source, target, by: Membership) -> int:
    """ "Copy setup from another company": `source`'s own categories that `target` doesn't have
    yet (matched by kind and name; under the matching parent). Returns how many were made."""
    created = 0
    with transaction.atomic():
        defaults.ensure(target)
        rows = Category.objects.filter(company=source, is_active=True, system_code="")
        own = {
            (c.kind, c.parent_id, c.name.lower()): c
            for c in Category.objects.filter(company=target)
        }

        def target_parent(parent: Category | None) -> Category | None:
            if parent is None:
                return None
            if parent.system_code:
                return Category.objects.filter(
                    company=target, system_code=parent.system_code
                ).first()
            return own.get((parent.kind, None, parent.name.lower()))

        for category in rows.filter(parent=None).order_by("kind", "order", "name"):
            if (category.kind, None, category.name.lower()) in own:
                continue
            made = Category.objects.create(
                company=target,
                name=category.name,
                kind=category.kind,
                color=category.color,
                icon=category.icon,
                is_capex=category.is_capex,
                is_sensitive=category.is_sensitive,
                order=category.order,
            )
            own[(made.kind, None, made.name.lower())] = made
            created += 1
        for category in (
            rows.exclude(parent=None).select_related("parent").order_by("order", "name")
        ):
            parent = target_parent(category.parent)
            if parent is None or (category.kind, parent.pk, category.name.lower()) in own:
                continue
            made = Category.objects.create(
                company=target,
                name=category.name,
                kind=category.kind,
                parent=parent,
                color=category.color,
                icon=category.icon,
                is_capex=category.is_capex,
                is_sensitive=category.is_sensitive,
                order=category.order,
            )
            own[(made.kind, parent.pk, made.name.lower())] = made
            created += 1
        if created:
            _audit(
                FinanceAction.CATEGORY_CREATED,
                target,
                _actor(target, by),
                target,
                copied_from=source.pk,
                categories=created,
            )
    return created


def _category_name(name) -> str:
    name = (name or "").strip()[:100]
    if not name:
        raise DomainError(_("Give the category a name."))
    return name


def _check_parent(company, parent: Category | None, kind: str) -> None:
    if parent is None:
        return
    _same_company(company, parent)
    if parent.parent_id is not None:
        raise DomainError(_("Categories go two levels deep at most."))
    if parent.kind != kind:
        raise DomainError(_("A subcategory has its parent's kind."))


def _check_free_name(company, parent, name: str, *, exclude: Category | None = None) -> None:
    taken = Category.objects.filter(company=company, parent=parent, name__iexact=name)
    if exclude is not None:
        taken = taken.exclude(pk=exclude.pk)
    if taken.exists():
        raise DomainError(_("There is already a category called %(name)s here.") % {"name": name})


def _category_snapshot(category: Category) -> dict:
    return {
        "name": category.name,
        "color": category.color,
        "icon": category.icon,
        "is_capex": category.is_capex,
        "is_sensitive": category.is_sensitive,
        "is_active": category.is_active,
    }


# Counterparties


def normalize_phone(value) -> str:
    """An Uzbek number as +998XXXXXXXXX ("" stays ""); anything else is refused."""
    digits = PHONE_DIGITS.sub("", str(value or ""))
    if not digits:
        return ""
    if len(digits) == 9:
        digits = f"998{digits}"
    if len(digits) != 12 or not digits.startswith("998"):
        raise DomainError(_("A number like +998 90 123 45 67."))
    return f"+{digits}"


@transaction.atomic
def create_counterparty(company, *, by: Membership, name: str, **fields) -> Counterparty:
    """A customer, supplier, landlord or state body in the one party directory."""
    _need_actor(by)
    _known(fields, PARTY_FIELDS)
    user = _actor(company, by)
    party = Counterparty(company=company)
    _apply_party(party, {"name": name, **fields})
    _save_party(party)
    _audit(
        FinanceAction.COUNTERPARTY_CREATED, company, user, party, name=party.name, kind=party.kind
    )
    return party


@transaction.atomic
def update_counterparty(party: Counterparty, *, by: Membership, **fields) -> Counterparty:
    _need_actor(by)
    _known(fields, PARTY_FIELDS)
    party = Counterparty.objects.select_for_update().select_related("company").get(pk=party.pk)
    company = party.company
    user = _actor(company, by)
    before = _party_snapshot(party)
    _apply_party(party, fields)
    _save_party(party)
    changes = _diff(before, _party_snapshot(party))
    if changes:
        _audit(FinanceAction.COUNTERPARTY_UPDATED, company, user, party, changes=changes)
    return party


def _apply_party(party: Counterparty, fields: dict) -> None:
    company = party.company
    for key, value in fields.items():
        match key:
            case "name":
                name = (value or "").strip()[:200]
                if not name:
                    raise DomainError(_("Give the counterparty a name."))
                party.name = name
            case "kind":
                if value not in Counterparty.Kind.values:
                    raise ValueError(f"Unknown counterparty kind {value!r}.")
                party.kind = value
            case "phone":
                party.phone = normalize_phone(value)
            case "tin":
                tin = PHONE_DIGITS.sub("", str(value or ""))
                if tin and len(tin) not in (9, 14):
                    raise DomainError(_("A taxpayer number has 9 digits (a person's PINFL 14)."))
                party.tin = tin
            case "telegram_username":
                party.telegram_username = (value or "").strip().lstrip("@")[:64]
            case "contact_person":
                party.contact_person = (value or "").strip()[:100]
            case "address":
                party.address = (value or "").strip()[:255]
            case "bank_details" | "notes":
                setattr(party, key, (value or "").strip()[:4000])
            case "default_category":
                if value is not None:
                    _same_company(company, value)
                party.default_category = value
            case "credit_limit":
                party.credit_limit = (
                    _money(value, allow_zero=True) if value not in (None, "") else None
                )
            case "credit_blocked" | "is_active":
                setattr(party, key, bool(value))
            case "birthday":
                party.birthday = value or None
            case "tags":
                tags = []
                for tag in value or []:
                    tag = str(tag).strip()[:32]
                    if tag and tag.lower() not in {t.lower() for t in tags}:
                        tags.append(tag)
                party.tags = tags[:MAX_TAGS]


def _save_party(party: Counterparty) -> None:
    others = Counterparty.objects.filter(company=party.company).exclude(pk=party.pk)
    if party.phone and others.filter(phone=party.phone).exists():
        raise DomainError(_("Another counterparty already has this phone number."))
    if party.tin and others.filter(tin=party.tin).exists():
        raise DomainError(_("Another counterparty already has this taxpayer number."))
    try:
        with transaction.atomic():
            party.save()
    except IntegrityError:
        raise DomainError(
            _("Another counterparty already has this phone or taxpayer number.")
        ) from None


def _party_snapshot(party: Counterparty) -> dict:
    return {
        "name": party.name,
        "kind": party.kind,
        "phone": party.phone,
        "tin": party.tin,
        "contact_person": party.contact_person,
        "telegram_username": party.telegram_username,
        "address": party.address,
        "default_category": str(party.default_category) if party.default_category_id else None,
        "credit_limit": str(party.credit_limit) if party.credit_limit is not None else None,
        "credit_blocked": party.credit_blocked,
        "birthday": party.birthday.isoformat() if party.birthday else None,
        "tags": list(party.tags),
        "is_active": party.is_active,
    }


# Entries made by a person


@transaction.atomic
def record_entry(
    company,
    *,
    by: Membership,
    kind: str,
    amount,
    occurred_on: date,
    account: MoneyAccount,
    category: Category | None = None,
    counterparty: Counterparty | None = None,
    membership: Membership | None = None,
    branch=None,
    project=None,
    description: str = "",
    direction: str = "in",
    receipts=(),
    receipt_files=(),
) -> Transaction:
    """Record an income, an expense, an owner's contribution or draw, or an opening balance
    from the dashboard, with its receipts.

    `amount` is positive; for owner and opening entries `direction` ("in" or "out") says which
    way the money went. `receipts` are receipts uploaded beforehand by the same person
    (`upload_receipt`), `receipt_files` new uploads. An expense above the company's
    `receipt_required_over` needs at least one receipt; one above `large_expense_alert` made by
    someone who isn't an owner tells the owners.
    """
    _need_actor(by)
    if kind not in RECORDABLE_KINDS:
        raise ValueError(f"record_entry books {', '.join(RECORDABLE_KINDS)}, not {kind!r}.")
    if direction not in ("in", "out"):
        raise ValueError(f"direction is 'in' or 'out', not {direction!r}.")
    value = _money(amount)
    if kind in SIGNED_KINDS and direction == "out":
        value = -value
    receipts = list(receipts)
    files = list(receipt_files)
    if len(receipts) + len(files) > MAX_RECEIPTS:
        raise DomainError(_("Attach at most %(n)s receipts.") % {"n": MAX_RECEIPTS})
    row = record_transaction(
        company,
        by=by,
        kind=kind,
        amount=value,
        occurred_on=occurred_on,
        account=account,
        category=category,
        counterparty=counterparty,
        membership=membership,
        branch=branch,
        project=project,
        description=description,
    )
    settings_row = conf.get_settings(company)
    threshold = settings_row.receipt_required_over
    needs_receipt = threshold is not None and abs(row.base_amount) > threshold
    if kind == Kind.EXPENSE and needs_receipt and not (receipts or files):
        raise DomainError(
            _("Expenses over %(limit)s need a receipt: attach a photo or a PDF.")
            % {"limit": _format(threshold, company.base_currency)}
        )
    attach_receipts(row, receipts, by=by)
    for file in files:
        upload_receipt(company, by=by, file=file, txn=row)
    _queue_large_expense(row, by, settings_row)
    return row


def _queue_large_expense(row: Transaction, by: Membership, settings_row: FinanceSettings) -> None:
    limit = settings_row.large_expense_alert
    if limit is None or row.kind != Kind.EXPENSE or row.status != Status.POSTED:
        return
    if abs(row.base_amount) < limit or (by.role is not None and by.role.is_owner):
        return
    from apps.finance import tasks  # tasks never import services; this side may import tasks

    transaction.on_commit(lambda: tasks.alert_large_expense.delay(row.pk))


@transaction.atomic
def update_transaction(txn: Transaction, *, by: Membership, **changes) -> Transaction:
    """Correct an entry, with every change in its audit history.

    An entry made by hand (income, expense, owner, opening; not from another module, a
    transfer or a debt) may change everything: amount, day, account, category, party, branch,
    project, description. A changed amount, day or account moves the balances under the same
    locks as a new entry, and a new day or currency takes the rate of that day. Entries made by
    another module (a shift, a payslip), transfers and debt rows only take a new description:
    they are corrected where they come from. Nothing in a closed period changes.
    """
    _need_actor(by)
    _known(changes, TRANSACTION_FIELDS)
    company = Transaction.objects.select_related("company").get(pk=txn.pk).company
    user = _actor(company, by)
    _hold_books(company)
    row = _lock_row(txn)
    if row.status not in LIVE_STATUSES:
        raise DomainError(_("A void or rejected entry can't be changed."))
    if not _is_manual(row) and set(changes) - {"description"}:
        raise DomainError(_manual_only_message(row))
    before = _row_snapshot(row)
    new_day = changes.get("occurred_on", row.occurred_on)
    _check_open(company, row.occurred_on, new_day)

    if "description" in changes:
        row.description = (changes["description"] or "").strip()[:300]
    if "category" in changes:
        if row.kind not in (Kind.INCOME, Kind.EXPENSE):
            raise DomainError(_("Owner and opening entries have no category."))
        row.category = _category(company, changes["category"], kind=row.kind, by=by)
    for field in ("counterparty", "membership", "branch", "project"):
        if field in changes:
            _same_company(company, changes[field])
            setattr(row, field, changes[field])

    if any(field in changes for field in MONEY_CHANGES):
        old_account_id, old_amount = row.account_id, row.amount
        account = changes.get("account", row.account)
        _same_company(company, account)
        if account is None:
            raise DomainError(_("Pick the account the money went to or came from."))
        _check_active(account)
        if "amount" in changes:
            value = _money(changes["amount"])
            if row.kind in SIGNED_KINDS:
                new_amount = value if row.amount > 0 else -value
            elif (row.kind == Kind.EXPENSE) != row.is_contra:
                new_amount = -value
            else:
                new_amount = value
        else:
            new_amount = row.amount
        if account.currency != row.currency or new_day != row.occurred_on:
            quote = _quote(company, account.currency, new_day)
        else:
            quote = RateQuote(row.rate, row.rate_stale, "kept")
        base_amount = convert(new_amount, account.currency, company.base_currency, quote.rate)
        _check_size(new_amount, base_amount)
        if row.status == Status.POSTED:
            locked = _lock_accounts(old_account_id, account.pk)
            _check_active(locked[account.pk])
            deltas = {old_account_id: -old_amount}
            deltas[account.pk] = deltas.get(account.pk, ZERO) + new_amount
            _move(locked, deltas)
        if "branch" not in changes and account.pk != old_account_id and account.branch_id:
            row.branch = account.branch
        row.account = account
        row.amount = new_amount
        row.currency = account.currency
        row.rate = quote.rate
        row.rate_stale = quote.stale
        row.base_amount = base_amount
        row.occurred_on = new_day
    row.save()
    changes_made = _diff(before, _row_snapshot(row))
    if changes_made:
        _audit(
            FinanceAction.TRANSACTION_UPDATED,
            company,
            user,
            row,
            sensitive=_is_sensitive(row),
            changes=changes_made,
        )
    return row


def bulk_transactions(rows, *, by: Membership, action: str, payload: dict) -> list[dict]:
    """Recategorize or void many entries at once. Each entry succeeds or fails on its own:
    `[{"id": 12, "ok": True}, {"id": 13, "ok": False, "error": "…"}]`."""
    _need_actor(by)
    if action not in BULK_ACTIONS:
        raise ValueError(f"Bulk action is one of {BULK_ACTIONS}, not {action!r}.")
    rows = list(rows)[:MAX_BULK]
    if action == "void":
        reason = _reason(payload.get("reason", ""))
    else:
        category = payload.get("category")
        if category is None:
            raise DomainError(_("Pick a category."))
    results = []
    with transaction.atomic():
        for row in rows:
            try:
                with transaction.atomic():
                    if action == "void":
                        void_transaction(row, by=by, reason=reason)
                    else:
                        update_transaction(row, by=by, category=category)
            except DomainError as error:
                results.append({"id": row.pk, "ok": False, "error": str(error)})
            else:
                results.append({"id": row.pk, "ok": True})
    return results


def _is_manual(row: Transaction) -> bool:
    return (
        row.kind in RECORDABLE_KINDS
        and not row.source_type
        and row.transfer_id is None
        and row.debt_id is None
    )


def _manual_only_message(row: Transaction) -> str:
    if row.transfer_id is not None:
        return _("This entry is part of a transfer: only its description can change here.")
    if row.debt_id is not None:
        return _("This entry belongs to a debt: only its description can change here.")
    if row.source_type:
        return _("This entry comes from %(source)s: correct it there.") % {
            "source": sources.label(row.source_type)
        }
    return _("Only the description of this entry can change.")


def _row_snapshot(row: Transaction) -> dict:
    return {
        "occurred_on": row.occurred_on.isoformat(),
        "account": str(row.account) if row.account_id else None,
        "amount": str(row.amount),
        "currency": row.currency,
        "category": str(row.category) if row.category_id else None,
        "counterparty": str(row.counterparty) if row.counterparty_id else None,
        "membership": str(row.membership) if row.membership_id else None,
        "branch": str(row.branch) if row.branch_id else None,
        "project": str(row.project) if row.project_id else None,
        "description": row.description,
    }


# Receipts


@transaction.atomic
def upload_receipt(company, *, by: Membership, file, txn: Transaction | None = None) -> Receipt:
    """Store a receipt (a picture or a PDF) in private storage, for `txn` or on its own until
    an entry is recorded with it. Pictures are re-encoded and get a small preview; anything
    that isn't a picture or a PDF is refused."""
    _need_actor(by)
    user = _actor(company, by)
    if txn is not None:
        _same_company(company, txn)
        if txn.status not in LIVE_STATUSES:
            raise DomainError(_("A void or rejected entry takes no receipts."))
        if txn.receipts.count() >= MAX_RECEIPTS:
            raise DomainError(_("Attach at most %(n)s receipts.") % {"n": MAX_RECEIPTS})
    clean = accept_document(file, allowed=("pdf", "image"))
    is_pdf = clean.name.endswith(".pdf")
    receipt = Receipt(
        company=company,
        transaction=txn,
        content_type="application/pdf" if is_pdf else "image/jpeg",
        size=clean.size,
        uploaded_by=user,
    )
    receipt.file.save(clean.name, clean, save=False)
    if not is_pdf:
        thumb = make_thumb(clean)
        receipt.thumb.save(thumb.name, thumb, save=False)
    receipt.save()
    if txn is not None:
        _audit(
            FinanceAction.RECEIPT_ADDED,
            company,
            user,
            txn,
            sensitive=_is_sensitive(txn),
            receipt=receipt.pk,
        )
    return receipt


@transaction.atomic
def attach_receipts(txn: Transaction, receipts, *, by: Membership) -> int:
    """Link receipts uploaded beforehand (by the same person, not linked yet) to `txn`."""
    _need_actor(by)
    receipts = list(receipts)
    if not receipts:
        return 0
    company = txn.company
    user = _actor(company, by)
    ids = [receipt.pk for receipt in receipts]
    free = Receipt.objects.select_for_update().filter(
        pk__in=ids, company=company, transaction__isnull=True, uploaded_by=user
    )
    if free.count() != len(set(ids)):
        raise DomainError(_("That receipt is gone or belongs to another entry. Upload it again."))
    if txn.receipts.count() + len(set(ids)) > MAX_RECEIPTS:
        raise DomainError(_("Attach at most %(n)s receipts.") % {"n": MAX_RECEIPTS})
    linked = free.update(transaction=txn, updated_at=timezone.now())
    _audit(
        FinanceAction.RECEIPT_ADDED,
        company,
        user,
        txn,
        sensitive=_is_sensitive(txn),
        receipts=sorted(ids),
    )
    return linked


@transaction.atomic
def remove_receipt(receipt: Receipt, *, by: Membership) -> None:
    _need_actor(by)
    receipt = Receipt.objects.select_for_update().select_related("transaction").get(pk=receipt.pk)
    company = receipt.company
    user = _actor(company, by)
    txn = receipt.transaction
    names = [name for name in (receipt.file.name, receipt.thumb.name) if name]
    storage = receipt.file.storage
    if txn is not None:
        _audit(
            FinanceAction.RECEIPT_REMOVED,
            company,
            user,
            txn,
            sensitive=_is_sensitive(txn),
            receipt=receipt.pk,
        )
    receipt.delete()
    transaction.on_commit(lambda: [storage.delete(name) for name in names])


# Debts


@transaction.atomic
def update_debt(debt: Debt, *, by: Membership, **fields) -> Debt:
    """Change a debt's due date, description, who chases it or its branch. Its amount never
    changes: cancel it and record it again."""
    _need_actor(by)
    _known(fields, DEBT_FIELDS)
    locked_debt = _lock_debt(debt.pk)
    company = locked_debt.company
    user = _actor(company, by)
    if locked_debt.status == Debt.Status.CANCELLED:
        raise DomainError(_("This debt was cancelled."))
    before = _debt_snapshot(locked_debt)
    if "due_on" in fields:
        due_on = fields["due_on"]
        if due_on is not None and due_on < locked_debt.issued_on:
            raise DomainError(_("The due date can't be before the day it was issued."))
        locked_debt.due_on = due_on
    if "description" in fields:
        locked_debt.description = (fields["description"] or "").strip()[:300]
    if "responsible" in fields:
        _same_company(company, fields["responsible"])
        locked_debt.responsible = fields["responsible"]
    if "branch" in fields:
        _same_company(company, fields["branch"])
        locked_debt.branch = fields["branch"]
    locked_debt.save()
    changes = _diff(before, _debt_snapshot(locked_debt))
    if changes:
        _audit(
            FinanceAction.DEBT_UPDATED,
            company,
            user,
            locked_debt,
            sensitive=locked_debt.kind in Debt.SENSITIVE_KINDS,
            changes=changes,
        )
    return locked_debt


@transaction.atomic
def set_installments(debt: Debt, *, by: Membership, rows) -> list[DebtInstallment]:
    """Replace a debt's instalment plan: `rows` of (due day, amount in the debt's currency)
    adding up to the whole debt. The debt is then due on the last instalment's day. An empty
    list removes the plan."""
    _need_actor(by)
    locked_debt = _lock_debt(debt.pk)
    company = locked_debt.company
    user = _actor(company, by)
    if locked_debt.status != Debt.Status.OPEN:
        raise DomainError(_("This debt is already settled or cancelled."))
    plan = sorted(((day, _money(amount)) for day, amount in rows), key=lambda item: item[0])
    if len(plan) > MAX_INSTALLMENTS:
        raise DomainError(_("A plan has at most %(n)s instalments.") % {"n": MAX_INSTALLMENTS})
    if plan:
        if any(day < locked_debt.issued_on for day, _amount in plan):
            raise DomainError(_("An instalment can't be due before the day the debt was issued."))
        total = sum((amount for _day, amount in plan), ZERO)
        if total != locked_debt.amount:
            raise DomainError(
                _("The instalments add up to %(total)s; the debt is %(amount)s.")
                % {
                    "total": _format(total, locked_debt.currency),
                    "amount": _format(locked_debt.amount, locked_debt.currency),
                }
            )
    locked_debt.installments.all().delete()
    made = DebtInstallment.objects.bulk_create(
        DebtInstallment(debt=locked_debt, due_on=day, amount=amount, position=index)
        for index, (day, amount) in enumerate(plan)
    )
    if plan:
        locked_debt.due_on = plan[-1][0]
        locked_debt.save(update_fields=["due_on", "updated_at"])
    _audit(
        FinanceAction.INSTALLMENTS_SET,
        company,
        user,
        locked_debt,
        sensitive=locked_debt.kind in Debt.SENSITIVE_KINDS,
        installments=[[day.isoformat(), str(amount)] for day, amount in plan],
    )
    return made


def _debt_snapshot(debt: Debt) -> dict:
    return {
        "due_on": debt.due_on.isoformat() if debt.due_on else None,
        "description": debt.description,
        "responsible": str(debt.responsible) if debt.responsible_id else None,
        "branch": str(debt.branch) if debt.branch_id else None,
    }


# Exchange rates


@transaction.atomic
def set_company_rate(company, *, by: Membership, currency: str, day: date, rate) -> CompanyRate:
    """The company's own rate for a day (UZS per 1 USD). It beats the Central Bank's rate for
    entries dated that day from now on; entries already posted keep the rate they froze."""
    _need_actor(by)
    user = _actor(company, by)
    if currency == Currency.UZS or currency not in Currency.values:
        raise DomainError(_("Rates are set for foreign currencies, in so‘m per unit."))
    value = _rate(rate)
    row = (
        CompanyRate.objects.select_for_update()
        .filter(company=company, currency=currency, date=day)
        .first()
    )
    old = str(row.rate) if row is not None else None
    if row is None:
        row = CompanyRate.objects.create(
            company=company, currency=currency, date=day, rate=value, set_by=user
        )
    else:
        row.rate = value
        row.set_by = user
        row.save(update_fields=["rate", "set_by", "updated_at"])
    _audit(
        FinanceAction.RATE_SET,
        company,
        user,
        row,
        currency=currency,
        date=day.isoformat(),
        changes={"rate": [old, str(value)]},
    )
    return row


@transaction.atomic
def delete_company_rate(row: CompanyRate, *, by: Membership) -> None:
    _need_actor(by)
    company = row.company
    user = _actor(company, by)
    _audit(
        FinanceAction.RATE_DELETED,
        company,
        user,
        row,
        currency=row.currency,
        date=row.date.isoformat(),
        rate=str(row.rate),
    )
    row.delete()


# Period lock and settings


def lock_period(company, *, by: Membership, until: date | None) -> FinanceSettings:
    """Close the books up to `until` (inclusive): nothing dated on or before it can be added,
    changed or voided. Moving the date back (or clearing it) reopens a period, which only an
    owner may do.

    Runs in its own transaction and takes the settings row FOR UPDATE, so it waits for the
    ledger writes already running (they hold it FOR SHARE) and every later write sees the new
    date. Call it on its own, never inside a ledger write.
    """
    _need_actor(by)
    user = _actor(company, by)
    with transaction.atomic():
        settings_row = FinanceSettings.objects.select_for_update().get(
            pk=conf.get_settings(company).pk
        )
        current = settings_row.locked_until
        if until is not None and until > _local_today(company):
            raise DomainError(_("The books can be closed up to today at most."))
        if until == current:
            return settings_row
        reopening = current is not None and (until is None or until < current)
        if reopening and not (by.role is not None and by.role.is_owner):
            raise DomainError(_("Only an owner can reopen a closed period."))
        settings_row.locked_until = until
        settings_row.save(update_fields=["locked_until"])
        _audit(
            FinanceAction.PERIOD_REOPENED if reopening else FinanceAction.PERIOD_LOCKED,
            company,
            user,
            settings_row,
            changes={
                "locked_until": [
                    current.isoformat() if current else None,
                    until.isoformat() if until else None,
                ]
            },
        )
    return settings_row


@transaction.atomic
def update_settings(company, *, by: Membership, **fields) -> FinanceSettings:
    """Where rates come from, the approval and receipt thresholds, the large-expense alert and
    how reimbursements are paid. The period lock has its own service (`lock_period`)."""
    _need_actor(by)
    _known(fields, SETTINGS_FIELDS)
    user = _actor(company, by)
    settings_row = FinanceSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    before = _settings_snapshot(settings_row)
    for key, value in fields.items():
        if key == "rate_source":
            if value not in RateSource.values:
                raise ValueError(f"Unknown rate source {value!r}.")
            settings_row.rate_source = value
        elif key == "reimburse_via":
            if value not in FinanceSettings.ReimburseVia.values:
                raise ValueError(f"Unknown reimbursement route {value!r}.")
            settings_row.reimburse_via = value
        else:
            setattr(
                settings_row,
                key,
                _money(value, allow_zero=True) if value not in (None, "") else None,
            )
    settings_row.save()
    changes = _diff(before, _settings_snapshot(settings_row))
    if changes:
        _audit(FinanceAction.SETTINGS_UPDATED, company, user, settings_row, changes=changes)
    return settings_row


def _settings_snapshot(row: FinanceSettings) -> dict:
    def money(value):
        return str(value) if value is not None else None

    return {
        "rate_source": row.rate_source,
        "approval_threshold": money(row.approval_threshold),
        "receipt_required_over": money(row.receipt_required_over),
        "large_expense_alert": money(row.large_expense_alert),
        "reimburse_via": row.reimburse_via,
    }


# Shared helpers of the bookkeeping services


def _known(fields: dict, allowed: tuple[str, ...]) -> None:
    unknown = set(fields) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}.")


def _color(value) -> str:
    color = (value or "").strip()
    if color and not re.fullmatch(COLOR_PATTERN, color):
        raise DomainError(_("A colour like #1f8a70."))
    return color


def _diff(before: dict, after: dict) -> dict:
    """{field: [old, new]} for the fields that changed (the audit History tab's shape)."""
    return {
        key: [before.get(key), value] for key, value in after.items() if before.get(key) != value
    }


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
    if isinstance(value, bool):  # Decimal(True) is 1
        raise DomainError(_("Enter an amount of money."))
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
    """A rate from the caller (or implied by two amounts), as the 6 decimals it's stored with."""
    if isinstance(value, bool):
        raise DomainError(_("Enter an exchange rate."))
    try:
        rate = Decimal(str(value) if isinstance(value, float) else value).quantize(RATE_STEP)
    except InvalidOperation, TypeError, ValueError:
        raise DomainError(_("Enter an exchange rate.")) from None
    if not rate.is_finite() or rate <= 0 or rate > MAX_RATE:
        raise DomainError(_("That exchange rate can't be right."))
    return rate


def _check_size(*amounts: Decimal) -> None:
    """Refuse amounts a money column can't hold (a huge dollar amount in som, a balance)."""
    if any(abs(amount) > MAX_AMOUNT for amount in amounts):
        raise DomainError(_("This amount is too large."))


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


def _hold_books(company) -> date | None:
    """`FinanceSettings.locked_until`, read under a share lock on the settings row that is held
    until the write commits.

    Every ledger write takes this lock first (it heads the lock order), so closing a period, an
    UPDATE of that row, waits for the writes already running, and a write that starts later
    reads the new date. Nothing can land in a period while it is being closed. Writers don't
    block each other: share locks are compatible.
    """
    settings_row = conf.get_settings(company)
    table = connection.ops.quote_name(FinanceSettings._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT locked_until FROM {table} WHERE id = %s FOR SHARE",
            [settings_row.pk],
        )
        return cursor.fetchone()[0]


def _check_open(company, *days: date) -> None:
    """Refuse dates on or before the period lock (taking the share lock of `_hold_books`)."""
    locked_until = _hold_books(company)
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
        _check_size(new_balance)
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


def _book_value(debt: Debt, settled: Decimal) -> Decimal:
    """What settling `settled` more of `debt` (locked) takes off it in the base currency, at the
    debt's frozen rate.

    It is the difference of the running totals, not `settled` converted on its own, so the parts
    add up to exactly what the debt was booked at however it's split: three payments of $0.01 on
    a $0.03 debt never leave a tiyin of exchange difference behind.
    """
    base = debt.company.base_currency
    before = convert(debt.paid, debt.currency, base, debt.rate)
    return convert(debt.paid + settled, debt.currency, base, debt.rate) - before


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
    base_amount: Decimal | None = None,
) -> Transaction:
    """Insert a ledger row. `base_amount` is `amount` at the quote's rate unless given (a debt
    settlement without money, valued by `_book_value`, may differ from it by a tiyin)."""
    if base_amount is None:
        base_amount = convert(amount, currency, company.base_currency, quote.rate)
    _check_size(amount, base_amount)
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
        base_amount=base_amount,
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


def _same_booking(found, source: Source, booked: dict):
    """`found`, what `source` booked earlier (or None), after checking it is the same booking.

    One source (type, id, key) books one thing. A module that reuses a source for another debt,
    account or kind would otherwise get the other booking back and book nothing, silently: it
    gets a ValueError and gives each booking its own key ("paid:r12").
    """
    if found is None:
        return None
    wrong = sorted(name for name, value in booked.items() if getattr(found, name) != value)
    if wrong:
        raise ValueError(
            f"Source {tuple(source)!r} already booked {found._meta.model_name} #{found.pk}, "
            f"which differs in {', '.join(wrong)}. Give each booking its own source key."
        )
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
    """Audit a change. Only people with `finance.view` see the row, and only people with
    `payroll.view` see one with per-person salary detail (§5)."""
    perm = Perm.PAYROLL_VIEW if sensitive else Perm.FINANCE_VIEW
    log = audit.record(
        action, company_id=company.pk, actor=user, target=target, required_perm=perm, **details
    )
    if not log.required_perm:
        # Until audit.record() sets the field from `required_perm` itself (W0-L2), the value
        # only lands in `details`; the audit views filter on the field, so set it here.
        log.required_perm = perm
        log.save(update_fields=["required_perm"])
