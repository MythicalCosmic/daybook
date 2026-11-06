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


# The expense claim flow (Package I) --------------------------------------------------------------


def claim_start() -> str:
    return _(
        "Send a photo of the receipt, or type the amount you spent, for example: 450000. "
        "Send /cancel to stop."
    )


def claim_off() -> str:
    return _("Expense claims aren't switched on for you.")


def claim_ask_amount() -> str:
    return _("How much did you spend? Type the amount, for example: 450000.")


def claim_bad_amount() -> str:
    return _("That doesn't look like an amount. Type digits only, for example: 450000.")


def claim_ask_category() -> str:
    return _("What was it for? Pick a category.")


def claim_no_categories() -> str:
    return _("There are no expense categories yet. Ask your manager to add them.")


def claim_ask_source() -> str:
    return _("Where did the money come from?")


def claim_own_money() -> str:
    return _("My own money")


def claim_held_cash(held: str) -> str:
    return _("Company cash I hold (%(amount)s)") % {"amount": held}


def claim_summary(category: str, amount: str, source: str, description: str) -> str:
    lines = [f"{category} · {amount}", _("Paid from: %(source)s") % {"source": source}]
    if description:
        lines.append(description)
    return "\n".join(lines)


def claim_button_submit() -> str:
    return _("Submit")


def claim_button_amount() -> str:
    return _("Change amount")


def claim_button_category() -> str:
    return _("Change category")


def claim_button_cancel() -> str:
    return _("Cancel")


def claim_button_more() -> str:
    # Translators: a button showing the next page of categories.
    return _("More ›")


def claim_button_back() -> str:
    # Translators: a button showing the previous page of categories.
    return _("‹ Back")


def claim_cancelled() -> str:
    return _("Cancelled. Nothing was sent.")


def claim_sent() -> str:
    return _("Sent for approval. You'll hear when it is decided.")


def claim_recorded() -> str:
    return _("Recorded. No approval was needed for this amount.")


def claim_expired() -> str:
    return _("This expense was already sent or cancelled. Start again with /expense.")


def drift_title() -> str:
    return _("Balances were corrected from the ledger")


def drift_body(accounts: int, debts: int) -> str:
    return _(
        "The nightly check found %(accounts)s account balance(s) and %(debts)s debt total(s) "
        "that didn't match their entries, and corrected them."
    ) % {"accounts": accounts, "debts": debts}
