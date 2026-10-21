"""What the bots and the inbox say about the finance ledger. Every text is rendered in the
recipient's language (inbox `notify` calls these under it)."""

from django.utils.translation import gettext as _

from apps.core.money import format_money


def money(amount, currency: str, language: str) -> str:
    return format_money(amount, currency, (language or "uz")[:2])


def large_expense_title(amount: str, category: str) -> str:
    return _("Big expense: %(amount)s · %(category)s") % {"amount": amount, "category": category}


def large_expense_body(person: str, account: str, description: str) -> str:
    text = _("%(person)s recorded it on %(account)s.") % {"person": person, "account": account}
    if description:
        text = f"{text}\n{description}"
    return text


def drift_title() -> str:
    return _("Balances were corrected from the ledger")


def drift_body(accounts: int, debts: int) -> str:
    return _(
        "The nightly check found %(accounts)s account balance(s) and %(debts)s debt total(s) "
        "that didn't match their entries, and corrected them."
    ) % {"accounts": accounts, "debts": debts}
