"""What the bots say about HR records. Call under the reader's language
(`inbox.notify` renders each title and body that way); dates are written dd.mm.yyyy, so no
case ending ever follows one."""

from datetime import date

from django.utils.translation import gettext as _

from apps.hr.models import Contract


def day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def contract_ready_title() -> str:
    return _("Your employment contract")


def contract_ready_body(contract: Contract) -> str:
    # Translators: %(number)s is a contract number like 2026-014.
    return _(
        "Contract %(number)s is in force. Read it in the app and confirm you have read it."
    ) % {"number": contract.number or "—"}
