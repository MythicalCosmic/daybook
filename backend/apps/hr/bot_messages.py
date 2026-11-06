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


# Pharmacist coverage (docs/PLAN-OWNER.md §14.9) -------------------------------------------


def clock(moment) -> str:
    return moment.strftime("%H:%M")


def reason_text(reason: str | None) -> str:
    """Why someone doesn't count as a qualified pharmacist, in a few words."""
    return {
        "missing": _("a required document is missing"),
        "expired": _("a required document has expired"),
        "unverified": _("a document is not verified yet"),
        "not_pharmacist": _("not in a pharmacist position"),
        "not_approved": _("not working now"),
    }.get(reason or "", _("not qualified"))


def live_gap_title(branch: str) -> str:
    # Translators: %(branch)s is a pharmacy's name, e.g. "Yunusobod".
    return _("No qualified pharmacist on duty: %(branch)s") % {"branch": branch}


def live_gap_body(since, present: list[str]) -> str:
    lines = [_("Since %(time)s nobody qualified has checked in.") % {"time": clock(since)}]
    if present:
        lines.append(_("Checked in: %(names)s") % {"names": ", ".join(present)})
    lines.append(_("Only people with pharmaceutical education may sell medicines."))
    return "\n".join(lines)


def seller_title(branch: str) -> str:
    return _("Till opened by someone not qualified: %(branch)s") % {"branch": branch}


def seller_body(cashier: str, opened_at, reason: str | None) -> str:
    # Translators: %(name)s is a person, %(time)s a clock time, %(reason)s a few words of why.
    return _("Opened at %(time)s. Cashier: %(name)s (%(reason)s).") % {
        "time": clock(opened_at),
        "name": cashier,
        "reason": reason_text(reason),
    }


def planned_gap_title(branch: str) -> str:
    return _("No qualified pharmacist in the roster: %(branch)s") % {"branch": branch}


def planned_gap_when(start, end) -> str:
    # Translators: a day (dd.mm.yyyy) and two clock times, e.g. "14.11.2026, 20:00 to 08:00".
    return _("%(day)s, %(start)s to %(end)s") % {
        "day": day(start.date()),
        "start": clock(start),
        "end": clock(end),
    }


PLANNED_LINES = 6


def planned_gaps_body(gaps: list) -> str:
    """The new gaps, one a line (a few at most), and what to do."""
    lines = []
    for gap in gaps[:PLANNED_LINES]:
        line = planned_gap_when(gap.start, gap.end)
        if gap.need > 1:
            # Translators: qualified pharmacists planned out of those needed, e.g. "1 of 2".
            line += " · " + _("%(have)d of %(need)d") % {"have": gap.have, "need": gap.need}
        lines.append(line)
    if len(gaps) > PLANNED_LINES:
        lines.append(_("and %(count)d more") % {"count": len(gaps) - PLANNED_LINES})
    lines.append(_("Add a qualified pharmacist to the roster."))
    return "\n".join(lines)
