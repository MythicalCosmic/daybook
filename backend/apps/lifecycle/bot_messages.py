"""What the bots say about the people lifecycle. Call under the reader's language
(`inbox.notify` renders each title and body that way). Plain text (the inbox escapes it), no
emoji, days as dd.mm.yyyy, a pay amount never: the person reads their own in the app."""

from datetime import date

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.lifecycle.models import DisciplinaryRecord, JobChange, Termination


def record_title(record: DisciplinaryRecord) -> str:
    """The kind of record, as the title: "Written warning"."""
    return str(record.get_kind_display())


def record_body(record: DisciplinaryRecord) -> str:
    # Translators: %(category)s is what it is about, e.g. "Storage conditions breached".
    return _("About: %(category)s. Read it in the app; you can write your explanation there.") % {
        "category": record.get_category_display()
    }


def explanation_title(record: DisciplinaryRecord) -> str:
    # Translators: %(name)s is a person's name; it stands alone after the colon.
    return _("Explanation from: %(name)s") % {"name": record.membership}


def explanation_body(record: DisciplinaryRecord) -> str:
    return f"{record.get_kind_display()} · {record.issued_on:%d.%m.%Y}"


def day(value: date | None) -> str:
    return f"{value:%d.%m.%Y}" if value else "—"


def _reason(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= 300 else f"{text[:297]}..."


# Leaving: HR -----------------------------------------------------------------------------------


def leave_request_title(termination: Termination) -> str:
    # Translators: %(name)s is a person's name; it stands alone after the colon.
    return _("Asks to leave: %(name)s") % {"name": termination.membership}


def leave_request_body(termination: Termination, notice: int | None) -> str:
    lines = [_("Last working day asked for: %(date)s") % {"date": day(termination.wished_last_day)}]
    if notice is not None:
        lines.append(
            ngettext("Notice: %(count)d day", "Notice: %(count)d days", notice) % {"count": notice}
        )
    if termination.reason:
        lines.append(_("Reason: %(reason)s") % {"reason": _reason(termination.reason)})
    return "\n".join(lines)


def leave_withdrawn_title(termination: Termination) -> str:
    return _("Stays after all: %(name)s") % {"name": termination.membership}


def leave_withdrawn_body(termination: Termination) -> str:
    return _("They withdrew their request to leave.")


def left_title(termination: Termination) -> str:
    return _("Has left: %(name)s") % {"name": termination.membership}


def left_body(termination: Termination, *, final_payslip: bool, still_open: int) -> str:
    lines = [_("Last working day: %(date)s") % {"date": day(termination.left_on)}]
    if final_payslip:
        lines.append(_("The final payslip is waiting in Payroll to be checked."))
    if still_open:
        lines.append(
            ngettext(
                "Still not handed over: %(count)d item.",
                "Still not handed over: %(count)d items.",
                still_open,
            )
            % {"count": still_open}
        )
    else:
        lines.append(_("Everything on the handover list was handed over."))
    return "\n".join(lines)


def last_day_title(termination: Termination) -> str:
    return _("Last working day today: %(name)s") % {"name": termination.membership}


def last_day_body(done: int, total: int) -> str:
    return _("Handed over: %(done)s. Still open: %(open)s.") % {
        "done": done,
        "open": total - done,
    }


def leave_failed_title(termination: Termination) -> str:
    return _("Leaving not completed: %(name)s") % {"name": termination.membership}


def leave_failed_body(termination: Termination) -> str:
    return "\n".join([termination.error, _("Open it and press Try again.")])


# Leaving: the person ---------------------------------------------------------------------------


def leave_agreed_title(termination: Termination) -> str:
    return _("Your last working day: %(date)s") % {"date": day(termination.last_day)}


def leave_agreed_body(termination: Termination) -> str:
    return _(
        "Hand over what you hold before then: the list is in the app. Thank you for your work."
    )


def leave_declined_title(termination: Termination) -> str:
    return _("Your request to leave was declined")


def leave_closed_body(termination: Termination) -> str:
    lines = []
    if termination.close_reason:
        lines.append(_("Reason: %(reason)s") % {"reason": _reason(termination.close_reason)})
    lines.append(_("Talk to your manager if you have questions."))
    return "\n".join(lines)


def leave_called_off_title(termination: Termination) -> str:
    return _("Your leaving is called off")


# Job changes -----------------------------------------------------------------------------------


def _named(value: dict | None) -> str:
    return (value or {}).get("name") or "—"


def change_lines(change: JobChange) -> list[str]:
    """One line per part: "Position: Senior pharmacist (was: Pharmacist)"; pay without its
    amount."""
    before, after = change.before or {}, change.after or {}
    labels = {
        "position": _("Position: %(now)s (was: %(was)s)"),
        "branch": _("Branch: %(now)s (was: %(was)s)"),
        "department": _("Department: %(now)s (was: %(was)s)"),
    }
    lines = []
    for part, label in labels.items():
        if part in (change.parts or []):
            lines.append(label % {"now": _named(after.get(part)), "was": _named(before.get(part))})
    if "pay" in (change.parts or []):
        lines.append(_("The pay changes too."))
    return lines


def change_proposed_title(change: JobChange) -> str:
    return _("Job change to approve: %(name)s") % {"name": change.membership}


def change_proposed_body(change: JobChange) -> str:
    lines = [_("Starts: %(date)s") % {"date": day(change.effective_on)}, *change_lines(change)]
    lines.append(_("Reason: %(reason)s") % {"reason": _reason(change.reason)})
    return "\n".join(lines)


def change_decided_title(change: JobChange) -> str:
    values = {"name": change.membership}
    if change.status == JobChange.Status.REJECTED:
        return _("Job change rejected: %(name)s") % values
    if change.status == JobChange.Status.CANCELLED:
        return _("Job change cancelled: %(name)s") % values
    return _("Job change approved: %(name)s") % values


def change_decided_body(change: JobChange) -> str:
    lines = [_("Starts: %(date)s") % {"date": day(change.effective_on)}]
    if change.decision_note:
        lines.append(_("Reason: %(reason)s") % {"reason": _reason(change.decision_note)})
    if change.status == JobChange.Status.APPLIED:
        lines.append(_("It has taken effect."))
    return "\n".join(lines)


def change_failed_title(change: JobChange) -> str:
    return _("Job change not applied: %(name)s") % {"name": change.membership}


def change_failed_body(change: JobChange) -> str:
    return "\n".join([change.error, _("Open it and press Try again.")])


def changed_title(change: JobChange) -> str:
    return _("Your job has changed")


def changed_body(change: JobChange) -> str:
    after = change.after or {}
    lines = [_("From: %(date)s") % {"date": day(change.effective_on)}]
    if "position" in change.parts:
        lines.append(_("Position: %(name)s") % {"name": _named(after.get("position"))})
    if "branch" in change.parts:
        lines.append(_("Branch: %(name)s") % {"name": _named(after.get("branch"))})
    if "department" in change.parts:
        lines.append(_("Department: %(name)s") % {"name": _named(after.get("department"))})
    if "pay" in change.parts:
        lines.append(_("Your pay changes too: see it in the app."))
    return "\n".join(lines)
