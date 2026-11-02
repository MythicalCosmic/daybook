"""What the bots say about HR records. Call under the reader's language
(`inbox.notify` renders each title and body that way); dates are written dd.mm.yyyy, and a
name or a date always stands after a colon or on its own, so no case ending follows one."""

from datetime import date

from aiogram import html
from django.utils.translation import gettext as _
from django.utils.translation import ngettext, pgettext

from apps.hr.models import Contract, EmployeeDocument


def day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def contract_ready_title() -> str:
    return _("Your employment contract")


def contract_ready_body(contract: Contract) -> str:
    # Translators: %(number)s is a contract number like 2026-014.
    return _(
        "Contract %(number)s is in force. Read it in the app and confirm you have read it."
    ) % {"number": contract.number or "—"}


# What runs out: to HR (the owner bot), and the person's own documents ----------------------


def document_title(document: EmployeeDocument, today: date) -> str:
    left = (document.expires_on - today).days
    if left > 0:
        return _("Document expires on %(date)s") % {"date": day(document.expires_on)}
    if left == 0:
        return _("Document expires today")
    return _("Document expired on %(date)s") % {"date": day(document.expires_on)}


def document_body(document: EmployeeDocument) -> str:
    return f"{document.membership} · {document.get_kind_display()}"


def my_document_title(document: EmployeeDocument, today: date) -> str:
    left = (document.expires_on - today).days
    if left > 0:
        return _("Your document expires on %(date)s") % {"date": day(document.expires_on)}
    if left == 0:
        return _("Your document expires today")
    return _("Your document has expired")


def my_document_body(document: EmployeeDocument) -> str:
    return f"{document.get_kind_display()}. {_('Upload the new one in the app.')}"


def contract_title(contract: Contract, today: date) -> str:
    left = (contract.ends_on - today).days
    if left > 0:
        return _("Contract ends on %(date)s") % {"date": day(contract.ends_on)}
    if left == 0:
        return _("Contract ends today")
    return _("Contract ended on %(date)s and is still in force") % {"date": day(contract.ends_on)}


def contract_body(contract: Contract) -> str:
    return f"{contract.membership} · {contract.number}\n{_('Renew it or end it.')}"


def probation_title(contract: Contract, today: date) -> str:
    left = (contract.probation_until - today).days
    if left > 0:
        return _("Probation ends on %(date)s") % {"date": day(contract.probation_until)}
    if left == 0:
        return _("Probation ends today")
    return _("Probation ended on %(date)s") % {"date": day(contract.probation_until)}


def probation_body(contract: Contract) -> str:
    return f"{contract.membership}\n{_('Keep them, or extend the probation by a month.')}"


def keep_label() -> str:
    """The button: they passed, keep them."""
    return pgettext("probation", "Keep")


def extend_label() -> str:
    return _("Extend 1 month")


def probation_kept() -> str:
    return _("Probation passed")


def probation_extended(until: date) -> str:
    return _("Probation extended: until %(date)s") % {"date": day(until)}


# Celebrations ------------------------------------------------------------------------------


def birthday_post(name: str) -> str:
    """The group post (HTML), in the company's language."""
    return _("Birthday today: %(name)s. Happy birthday!") % {"name": f"<b>{html.quote(name)}</b>"}


def anniversary_post(name: str, years: int) -> str:
    return ngettext(
        "Work anniversary: %(name)s, %(years)d year with the team. Thank you!",
        "Work anniversary: %(name)s, %(years)d years with the team. Thank you!",
        years,
    ) % {"name": f"<b>{html.quote(name)}</b>", "years": years}


def birthday_greeting_title() -> str:
    return _("Happy birthday!")


def anniversary_greeting_title(years: int) -> str:
    return ngettext(
        "%(years)d year with the team",
        "%(years)d years with the team",
        years,
    ) % {"years": years}


def greeting_body(company_name: str) -> str:
    # Translators: %(company)s is the company's name.
    return _("The whole team of «%(company)s» congratulates you.") % {"company": company_name}
