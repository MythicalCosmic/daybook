"""Notifications of the finance ledger, sent by Celery after the change committed.

- `finance.large_expense`: someone who isn't an owner recorded an expense at or above the
  company's `large_expense_alert`; every other owner hears about it (in the app and Telegram).
- `finance.balance_drift`: the nightly check corrected cached balances from the ledger.
"""

from apps.finance import bot_messages
from apps.finance.models import Transaction
from apps.inbox.services import notify
from apps.members.models import Membership


def owners(company) -> list[Membership]:
    return list(
        Membership.objects.filter(
            company=company, status=Membership.Status.APPROVED, role__is_owner=True
        ).select_related("user", "role", "company")
    )


def send_large_expense(txn_id: int) -> int:
    """Tell the owners about a big expense; returns how many were told."""
    txn = (
        Transaction.objects.select_related("company", "account", "category", "created_by")
        .filter(pk=txn_id, kind=Transaction.Kind.EXPENSE, status=Transaction.Status.POSTED)
        .first()
    )
    if txn is None:
        return 0
    company = txn.company
    actor = (
        Membership.objects.filter(company=company, user_id=txn.created_by_id).first()
        if txn.created_by_id
        else None
    )
    recipients = [person for person in owners(company) if person.user_id != txn.created_by_id]
    if not recipients:
        return 0
    amount = abs(txn.amount)
    person_name = str(actor) if actor else (str(txn.created_by) if txn.created_by else "")

    def title(person: Membership) -> str:
        return bot_messages.large_expense_title(
            bot_messages.money(amount, txn.currency, person.user.language),
            str(txn.category) if txn.category_id else "",
        )

    def body(person: Membership) -> str:
        return bot_messages.large_expense_body(person_name, str(txn.account), txn.description)

    sent = notify(
        recipients,
        "finance.large_expense",
        title=title,
        body=body,
        url=f"/c/{company.pk}/finance/transactions?txn={txn.pk}",
        target=txn,
        actor=actor,
        dedupe_key=f"finance:large:{txn.pk}",
    )
    return len(sent)


def send_drift(company, *, accounts: int, debts: int) -> int:
    recipients = owners(company)
    sent = notify(
        recipients,
        "finance.balance_drift",
        title=lambda person: bot_messages.drift_title(),
        body=lambda person: bot_messages.drift_body(accounts, debts),
        url=f"/c/{company.pk}/finance/accounts",
    )
    return len(sent)
