"""What the bots say about Face ID scans: plain, short, no emoji. Every function renders in the
active language (callers wrap them in the recipient's `translation.override`)."""

from aiogram import html
from django.utils.translation import gettext as _

from apps.attendance import clock


def who(event) -> str:
    """The person: their Daybook name, else the terminal's name and number."""
    if event.membership_id:
        return event.membership.full_name or str(event.membership)
    if event.name_on_device:
        return _("%(name)s (No %(number)s)") % {
            "name": event.name_on_device,
            "number": event.employee_no,
        }
    return _("No %(number)s") % {"number": event.employee_no}


def scan_title(event) -> str:
    """ "Mushtariy · 08:00 · Kirish": who, when, which terminal."""
    return " · ".join((who(event), clock.hhmm(event.company, event.event_at), event.device.name))


def scan_body(event, record=None) -> str:
    """What the scan did, in a few words."""
    action = event.action
    if action == "not_linked":
        return _("Not in Daybook yet: link the number to a person.")
    if action == "checked_in":
        if record is not None and record.is_late:
            from apps.attendance.bot_messages import duration

            return _("Came in, %(late)s late.") % {"late": duration(record.late_minutes)}
        return _("Came in.")
    if action == "checked_out":
        if record is not None and record.worked_minutes:
            from apps.attendance.bot_messages import duration

            return _("Left. Worked today: %(worked)s.") % {
                "worked": duration(record.worked_minutes)
            }
        return _("Left.")
    return event.device.branch.name


def arrival_post(event) -> str:
    """The branch group's line about someone the terminal saw."""
    return _("<b>%(name)s</b>: %(time)s, %(device)s.") % {
        "name": html.quote(who(event)),
        "time": clock.hhmm(event.company, event.event_at),
        "device": html.quote(event.device.name),
    }
