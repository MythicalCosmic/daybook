"""Expense claims (Package I, docs/PLAN-OWNER.md §3.7, §10.2): "I paid for the company".

    claim = claims.submit_claim(company, by=member, amount=..., category=..., spent_on=...,
                                paid_from="own_money", receipt_files=[photo], via="bot")
    claims.decide_claim(claim, by=manager, approve=True)
    claims.pay_claim(claim, by=manager, account=kassa)          # own money, paid in cash

The money flow (§3.7):
- **Own money**: on approval a `reimbursement` payable to the person is opened with the
  expense booked as its accrual (`open_debt(..., category=claim.category)`). With
  `reimburse_via=payroll` (and payroll on) the next payslip pays it back; with `cash` the
  approver pays it from an account (`pay_claim`). The claim reads "paid" once the debt is.
- **Company cash I hold**: the expense is recorded on the account the person holds, pending
  until approved (`approve_transaction`), rejected with the claim.
- Below `FinanceSettings.approval_threshold` a claim is booked at once; with no threshold
  every claim waits. Nobody decides their own claim.

Receipts go through `services.upload_receipt` (sanitized, private storage) and belong to the
claim; once it is booked they point at its ledger row too, so the entry shows them.

Approvers hear about a waiting claim in Telegram with the receipt photo and [Approve]
[Reject] (inbox kind `finance.claim`, whose in-app form is the "Needs you" queue
`finance.claims`); the person hears the decision (`finance.claim_decided`).
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.console.registry import QueueAction, QueueItem
from apps.core.exceptions import DomainError
from apps.core.files import signed_url
from apps.core.money import format_money, quantize
from apps.finance import conf, queries, services
from apps.finance.audit_actions import FinanceAction
from apps.finance.models import (
    Category,
    Claim,
    Debt,
    FinanceSettings,
    MoneyAccount,
    Receipt,
    Transaction,
)
from apps.finance.sources import Source
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

SOURCE = "finance.claim"
PULSE = "finance.claims"
MAX_RECEIPTS = 5
RECEIPT_TTL = 3600
Status = Claim.Status
PaidFrom = Claim.PaidFrom


# Rules ----------------------------------------------------------------------------------------


def reimburse_route(company) -> str:
    """How an approved own-money claim is paid back: by payroll only while payroll is on."""
    route = conf.get_settings(company).reimburse_via
    if route == FinanceSettings.ReimburseVia.PAYROLL and company.has_feature("payroll"):
        return FinanceSettings.ReimburseVia.PAYROLL
    return FinanceSettings.ReimburseVia.CASH


def effective_status(claim: Claim) -> str:
    """An approved own-money claim reads "paid" once its debt is settled (payroll pays it)."""
    if (
        claim.status == Status.APPROVED
        and claim.paid_from == PaidFrom.OWN_MONEY
        and claim.debt_id is not None
        and claim.debt.status == Debt.Status.PAID
    ):
        return Status.PAID
    return claim.status


def needs_approval(company, amount: Decimal) -> bool:
    threshold = conf.get_settings(company).approval_threshold
    return threshold is None or amount >= threshold


def can_decide(member: Membership, claim: Claim) -> bool:
    return (
        claim.status == Status.SUBMITTED
        and claim.membership_id != member.pk
        and member.has_perm(Perm.FINANCE_APPROVE)
        and _in_scope(member, claim)
    )


def can_pay(member: Membership, claim: Claim) -> bool:
    return (
        effective_status(claim) == Status.APPROVED
        and claim.paid_from == PaidFrom.OWN_MONEY
        and claim.debt_id is not None
        and claim.debt.status == Debt.Status.OPEN
        and not claim.debt.is_locked
        and reimburse_route(claim.company) == FinanceSettings.ReimburseVia.CASH
        and member.has_perm(Perm.FINANCE_RECORD)
        and claim.membership_id != member.pk
        and _in_scope(member, claim)
    )


def _in_scope(member: Membership, claim: Claim) -> bool:
    from apps.members.queries import in_scope

    return in_scope(member, claim.membership)


def visible_claims(member: Membership) -> QuerySet[Claim]:
    """Claims an approver or a finance viewer sees: the people in their branch scope (and
    their own)."""
    rows = Claim.objects.for_company(member.company)
    if not (member.has_perm(Perm.FINANCE_APPROVE) or member.has_perm(Perm.FINANCE_VIEW)):
        return rows.filter(membership=member)
    branches = scope.branch_ids(member)
    if branches is None:
        return rows
    return rows.filter(
        Q(membership=member) | Q(membership__branches__in=branches) | Q(branch_id__in=branches)
    ).distinct()


def with_relations(rows: QuerySet[Claim]) -> QuerySet[Claim]:
    return rows.select_related(
        "company", "membership__user", "category__parent", "branch", "debt", "decided_by"
    ).prefetch_related("receipts")


def receipt_links(claim: Claim, *, user) -> list[dict]:
    links = []
    for receipt in claim.receipts.all():
        extension = ".pdf" if receipt.content_type == "application/pdf" else ".jpg"
        links.append(
            {
                "id": receipt.pk,
                "url": signed_url(
                    receipt.file,
                    user=user,
                    company_id=receipt.company_id,
                    check=f"finance.receipt:{receipt.pk}",
                    ttl=RECEIPT_TTL,
                    filename=f"receipt-{receipt.pk}{extension}",
                ),
                "thumb_url": signed_url(
                    receipt.thumb,
                    user=user,
                    company_id=receipt.company_id,
                    check=f"finance.receipt:{receipt.pk}",
                    ttl=RECEIPT_TTL,
                    filename=f"receipt-{receipt.pk}-thumb.webp",
                )
                if receipt.thumb
                else None,
                "content_type": receipt.content_type,
                "is_image": receipt.is_image,
            }
        )
    return links


def expense_categories(company) -> QuerySet[Category]:
    return (
        Category.objects.for_company(company)
        .filter(kind=Category.Kind.EXPENSE, is_active=True)
        .exclude(system_code__in=CLAIM_EXCLUDED)
        .select_related("parent")
        .order_by("order", "name")
    )


# Categories a person never claims: what the system books by itself.
CLAIM_EXCLUDED = ("salaries", "payroll_taxes", "cash_shortage", "bad_debts", "fx_diff")


def held_accounts(member: Membership) -> list[MoneyAccount]:
    return list(
        MoneyAccount.objects.filter(
            company=member.company,
            holder=member,
            kind=MoneyAccount.Kind.EMPLOYEE,
            is_active=True,
        ).order_by("currency", "pk")
    )


def wallet(member: Membership) -> dict:
    """Money I hold for the company and what it owes me back (open reimbursements)."""
    company = member.company
    base = company.base_currency
    held = held_accounts(member)
    owed = Debt.objects.filter(
        company=company,
        membership=member,
        direction=Debt.Direction.PAYABLE,
        kind=Debt.Kind.REIMBURSEMENT,
        status=Debt.Status.OPEN,
        currency=base,
    ).aggregate(total=Sum("amount"), paid=Sum("paid"))
    settings_row = conf.get_settings(company)

    def money(value):
        return str(value) if value is not None else None

    return {
        "currency": base,
        "held": [
            {
                "account_id": account.pk,
                "name": account.name,
                "balance": str(account.balance),
                "currency": account.currency,
            }
            for account in held
        ],
        "held_total": str(
            quantize(sum((a.balance for a in held if a.currency == base), Decimal(0)))
        ),
        "owed_to_me": str(quantize((owed["total"] or Decimal(0)) - (owed["paid"] or Decimal(0)))),
        "approval_threshold": money(settings_row.approval_threshold),
        "receipt_required_over": money(settings_row.receipt_required_over),
    }


# Services -------------------------------------------------------------------------------------


def submit_claim(
    company,
    *,
    by: Membership,
    amount,
    category: Category,
    spent_on: date,
    paid_from: str,
    description: str = "",
    receipt_files=(),
    via: str = Claim.Via.MINIAPP,
) -> Claim:
    """`by` claims an expense they paid. Booked at once below the approval threshold;
    otherwise it waits and the approvers are asked."""
    services._need_actor(by)
    user = services._actor(company, by)
    if by.status != Membership.Status.APPROVED:
        raise DomainError(_("Your access is paused."))
    if paid_from not in PaidFrom.values:
        raise ValueError(f"Unknown paid_from {paid_from!r}.")
    if via not in Claim.Via.values:
        raise ValueError(f"Unknown via {via!r}.")
    value = services._money(amount)
    services._same_company(company, category)
    if category.kind != Category.Kind.EXPENSE or not category.is_active:
        raise DomainError(_("Pick an expense category."))
    if category.system_code in CLAIM_EXCLUDED:
        raise DomainError(_("Pick another category: this one is booked by the system."))
    today = queries.local_today(company)
    if spent_on > today:
        raise DomainError(_("Pick today or an earlier day."))
    services._check_open(company, spent_on)
    files = list(receipt_files)
    if len(files) > MAX_RECEIPTS:
        raise DomainError(_("Attach at most %(n)s receipts.") % {"n": MAX_RECEIPTS})
    settings_row = conf.get_settings(company)
    limit = settings_row.receipt_required_over
    if limit is not None and value > limit and not files:
        raise DomainError(
            _("Expenses over %(limit)s need a receipt: attach a photo or a PDF.")
            % {"limit": services._format(limit, company.base_currency)}
        )
    if paid_from == PaidFrom.HELD_CASH:
        held = sum(
            (a.balance for a in held_accounts(by) if a.currency == company.base_currency),
            Decimal(0),
        )
        if value > held:
            raise DomainError(
                _("You hold %(held)s of company cash: that's less than this expense.")
                % {"held": services._format(held, company.base_currency)}
            )
    waits = needs_approval(company, value)
    with transaction.atomic():
        claim = Claim.objects.create(
            company=company,
            membership=by,
            amount=value,
            currency=company.base_currency,
            category=category,
            spent_on=spent_on,
            description=(description or "").strip()[:300],
            paid_from=paid_from,
            branch=by.home_branch,
            via=via,
        )
        for file in files:
            receipt = services.upload_receipt(company, by=by, file=file)
            receipt.claim = claim
            receipt.save(update_fields=["claim", "updated_at"])
        services._audit(
            FinanceAction.CLAIM_SUBMITTED,
            company,
            user,
            claim,
            amount=str(value),
            paid_from=paid_from,
            waits=waits,
        )
        if paid_from == PaidFrom.HELD_CASH:
            row = _record_held(claim, by=by, posted=not waits)
            claim.transaction = row
            claim.save(update_fields=["transaction", "updated_at"])
        if not waits:
            _book_approved(claim, by=None)
        else:
            transaction.on_commit(lambda: notify_approvers(claim.pk))
        _bump(company)
    return claim


def decide_claim(claim: Claim, *, by: Membership, approve: bool, reason: str = "") -> Claim:
    """Approve or reject a waiting claim. Checks the decider's permission and scope (the
    inbox buttons call this directly) and that nobody decides their own claim."""
    services._need_actor(by)
    company = claim.company
    user = services._actor(company, by)
    with transaction.atomic():
        claim = _lock(claim)
        if claim.membership_id == by.pk:
            raise DomainError(_("Nobody approves their own expenses."))
        if not by.has_perm(Perm.FINANCE_APPROVE) or not _in_scope(by, claim):
            raise DomainError(_("You don't have permission to do this."))
        if claim.status != Status.SUBMITTED:
            raise DomainError(_("This expense was already decided."))
        claim.decided_by = user
        claim.decided_at = timezone.now()
        if approve:
            claim.status = Status.APPROVED
            claim.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
            _book_approved(claim, by=by)
            action = FinanceAction.CLAIM_APPROVED
        else:
            reason = services._reason(reason)
            if claim.transaction_id is not None:
                services.reject_transaction(claim.transaction, by=by, reason=reason)
            claim.status = Status.REJECTED
            claim.reject_reason = reason
            claim.save(
                update_fields=["status", "decided_by", "decided_at", "reject_reason", "updated_at"]
            )
            action = FinanceAction.CLAIM_REJECTED
        services._audit(action, company, user, claim, reason=claim.reject_reason)
        transaction.on_commit(lambda: notify_decided(claim.pk))
        _bump(company)
    return claim


def pay_claim(
    claim: Claim, *, by: Membership, account: MoneyAccount, paid_on: date | None = None
) -> Claim:
    """Pay back an approved own-money claim from `account` (the cash route)."""
    services._need_actor(by)
    company = claim.company
    user = services._actor(company, by)
    paid_on = paid_on or queries.local_today(company)
    with transaction.atomic():
        claim = _lock(claim)
        if claim.membership_id == by.pk:
            raise DomainError(_("Someone else pays back your own expenses."))
        if claim.paid_from != PaidFrom.OWN_MONEY or claim.debt_id is None:
            raise DomainError(_("Only an approved expense paid from own money is paid back."))
        if claim.status != Status.APPROVED:
            raise DomainError(_("This expense isn't waiting to be paid back."))
        debt = Debt.objects.get(pk=claim.debt_id)
        if debt.status == Debt.Status.OPEN:
            services.pay_debt(
                debt,
                by=by,
                amount=debt.amount - debt.paid,
                paid_on=paid_on,
                account=account,
                source=Source(SOURCE, claim.pk, "paid"),
            )
        claim.status = Status.PAID
        claim.paid_at = timezone.now()
        claim.save(update_fields=["status", "paid_at", "updated_at"])
        services._audit(
            FinanceAction.CLAIM_PAID,
            company,
            user,
            claim,
            account=account.pk,
            amount=str(claim.amount),
        )
        transaction.on_commit(lambda: notify_decided(claim.pk))
        _bump(company)
    return claim


def cancel_claim(claim: Claim, *, by: Membership) -> Claim:
    """The person takes back their claim while nobody has decided it."""
    services._need_actor(by)
    company = claim.company
    user = services._actor(company, by)
    with transaction.atomic():
        claim = _lock(claim)
        if claim.membership_id != by.pk:
            raise DomainError(_("Only the person who claimed it can cancel it."))
        if claim.status != Status.SUBMITTED:
            raise DomainError(_("This expense was already decided."))
        if claim.transaction_id is not None:
            services.reject_transaction(
                claim.transaction, by=by, reason=_("Cancelled by the person who claimed it.")
            )
        claim.status = Status.CANCELLED
        claim.save(update_fields=["status", "updated_at"])
        services._audit(FinanceAction.CLAIM_CANCELLED, company, user, claim)
        _bump(company)
    return claim


def sync_paid(company=None) -> int:
    """Mark approved own-money claims "paid" once their debt is settled (payroll paid it)."""
    rows = Claim.objects.filter(
        status=Status.APPROVED,
        paid_from=PaidFrom.OWN_MONEY,
        debt__status=Debt.Status.PAID,
    )
    if company is not None:
        rows = rows.filter(company=company)
    return rows.update(status=Status.PAID, paid_at=timezone.now(), updated_at=timezone.now())


def _record_held(claim: Claim, *, by: Membership, posted: bool) -> Transaction:
    company = claim.company
    account = services.account_for_holder(company, claim.membership)
    return services.record_transaction(
        company,
        by=by,
        kind=Transaction.Kind.EXPENSE,
        amount=claim.amount,
        occurred_on=claim.spent_on,
        account=account,
        category=claim.category,
        membership=claim.membership,
        branch=claim.branch,
        description=_description(claim),
        status=Transaction.Status.POSTED if posted else Transaction.Status.PENDING,
        source=Source(SOURCE, claim.pk, "held"),
    )


def _book_approved(claim: Claim, *, by: Membership | None) -> None:
    """Book an approved claim (`by` None: below the threshold, approved by the rules)."""
    if claim.status != Status.APPROVED:
        claim.status = Status.APPROVED
        claim.save(update_fields=["status", "updated_at"])
    row = None
    if claim.paid_from == PaidFrom.HELD_CASH:
        row = claim.transaction
        if row is not None and row.status == Transaction.Status.PENDING:
            if by is None:
                raise ValueError("A pending held-cash claim is approved by a person.")
            row = services.approve_transaction(row, by=by)
    else:
        debt = services.open_debt(
            claim.company,
            by=by,
            direction=Debt.Direction.PAYABLE,
            kind=Debt.Kind.REIMBURSEMENT,
            amount=claim.amount,
            currency=claim.currency,
            issued_on=claim.spent_on,
            membership=claim.membership,
            category=claim.category,
            branch=claim.branch,
            description=_description(claim),
            source=Source(SOURCE, claim.pk, "debt"),
        )
        claim.debt = debt
        row = debt.transactions.filter(status__in=("pending", "posted")).order_by("pk").first()
        claim.transaction = row
        claim.save(update_fields=["debt", "transaction", "updated_at"])
    if row is not None:
        Receipt.objects.filter(claim=claim, transaction__isnull=True).update(
            transaction=row, updated_at=timezone.now()
        )


def _description(claim: Claim) -> str:
    text = claim.description or str(claim.category)
    return f"{text} · {claim.membership}"[:300]


def _lock(claim: Claim) -> Claim:
    return (
        Claim.objects.select_for_update(of=("self",))
        .select_related("company", "membership__user", "category", "branch", "transaction", "debt")
        .get(pk=claim.pk)
    )


def _bump(company) -> None:
    from apps.console import pulse

    transaction.on_commit(lambda: pulse.bump(company.pk, PULSE, "finance.ledger"))


# Needs you and notifications ------------------------------------------------------------------


def deciders(claim: Claim) -> list[Membership]:
    """Who may decide: finance.approve holders who see the person, never the person."""
    from apps.members.queries import in_scope, members_with_perm

    people = (
        members_with_perm(claim.company, Perm.FINANCE_APPROVE)
        .exclude(pk=claim.membership_id)
        .select_related("user", "role")
    )
    return [person for person in people if in_scope(person, claim.membership)]


def waiting_for(member: Membership) -> QuerySet[Claim]:
    """Claims `member` may decide now."""
    if not member.has_perm(Perm.FINANCE_APPROVE):
        return Claim.objects.none()
    return visible_claims(member).filter(status=Status.SUBMITTED).exclude(membership=member)


def queue_count(member: Membership) -> int:
    return waiting_for(member).count()


def queue_items(member: Membership, limit: int) -> list[QueueItem]:
    company = member.company
    rows = (
        waiting_for(member)
        .select_related("membership__user", "category")
        .order_by("created_at", "pk")[:limit]
    )
    return [
        QueueItem(
            kind=PULSE,
            id=row.pk,
            title=claim_title(row),
            subtitle=claim_subtitle(row),
            created_at=row.created_at,
            url=f"/c/{company.pk}/finance/claims?claim={row.pk}",
            actions=(
                QueueAction(
                    "approve",
                    str(_("Approve")),
                    "primary",
                    "POST",
                    f"finance/claims/{row.pk}/approve/",
                ),
                QueueAction(
                    "reject",
                    str(_("Reject")),
                    "danger",
                    "POST",
                    f"finance/claims/{row.pk}/reject/",
                    needs_reason=True,
                ),
            ),
        )
        for row in rows
    ]


def _money(amount, currency, language=None) -> str:
    return format_money(amount, currency, ((language or translation.get_language()) or "uz")[:2])


def claim_title(claim: Claim) -> str:
    return _("%(name)s · %(amount)s · %(category)s") % {
        "name": claim.membership,
        "amount": _money(claim.amount, claim.currency),
        "category": claim.category,
    }


def claim_subtitle(claim: Claim) -> str:
    source = PaidFrom(claim.paid_from).label
    parts = [str(source), claim.spent_on.strftime("%d.%m.%Y")]
    if claim.description:
        parts.append(claim.description)
    return " · ".join(parts)


APPROVE = ("approve", gettext_lazy("Approve"), "primary")
REJECT = ("reject", gettext_lazy("Reject"), "danger")


def notify_approvers(claim_id: int) -> int:
    from apps.inbox.services import NotificationAction, notify

    claim = (
        Claim.objects.select_related("company", "membership__user", "category")
        .filter(pk=claim_id, status=Status.SUBMITTED)
        .first()
    )
    if claim is None:
        return 0
    people = deciders(claim)
    if not people:
        return 0
    photo = claim.receipts.filter(content_type__startswith="image/").order_by("pk").first()
    sent = notify(
        people,
        "finance.claim",
        title=lambda person: claim_title(claim),
        body=lambda person: claim_subtitle(claim),
        url=f"/c/{claim.company_id}/finance/claims?claim={claim.pk}",
        target=claim,
        actions=[
            NotificationAction(*APPROVE),
            NotificationAction(REJECT[0], REJECT[1], REJECT[2], needs_reason=True),
        ],
        dedupe_key=f"finance:claim:{claim.pk}",
        photo=photo.file.name if photo is not None else None,
        photo_storage="private",
    )
    return len(sent)


def notify_decided(claim_id: int) -> int:
    from apps.inbox.services import notify

    claim = (
        Claim.objects.select_related("company", "membership__user", "category", "debt")
        .filter(pk=claim_id)
        .first()
    )
    if claim is None or claim.status not in (Status.APPROVED, Status.REJECTED, Status.PAID):
        return 0
    status = claim.status

    def title(person: Membership) -> str:
        amount = _money(claim.amount, claim.currency, person.user.language)
        if status == Status.REJECTED:
            return _("Your expense of %(amount)s was not approved") % {"amount": amount}
        if status == Status.PAID:
            return _("Your expense of %(amount)s was paid back") % {"amount": amount}
        return _("Your expense of %(amount)s is approved") % {"amount": amount}

    def body(person: Membership) -> str:
        if status == Status.REJECTED:
            return claim.reject_reason
        if status == Status.APPROVED and claim.paid_from == PaidFrom.OWN_MONEY:
            if reimburse_route(claim.company) == FinanceSettings.ReimburseVia.PAYROLL:
                return str(_("It will be paid back with your next pay."))
            return str(_("It will be paid back in cash."))
        return ""

    sent = notify(
        [claim.membership],
        "finance.claim_decided",
        title=title,
        body=body,
        app_screen="expenses",
        target=claim,
        dedupe_key=f"finance:claim:{claim.pk}:{status}",
    )
    return len(sent)


# Inbox buttons (apps.inbox.registry.register_action) -------------------------------------------


def _target(notification) -> Claim:
    claim = Claim.objects.filter(
        company_id=notification.company_id, pk=notification.target_id
    ).first()
    if claim is None:
        raise DomainError(_("This isn't available any more."))
    return claim


def approve_action(notification, by: Membership, reason: str) -> str:
    decide_claim(_target(notification), by=by, approve=True)
    return str(_("Expense approved."))


def reject_action(notification, by: Membership, reason: str) -> str:
    decide_claim(_target(notification), by=by, approve=False, reason=reason)
    return str(_("Expense rejected."))
