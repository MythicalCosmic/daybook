"""What the bots say about policies. Call under the reader's language (`inbox.notify` renders
each title and body that way). Dates are written dd.mm.yyyy; a policy's title, a name or a date
always stands after a colon or on a line of its own, so no case ending ever follows one."""

from datetime import date

from django.utils.translation import gettext as _

# Names or titles listed in one message at most; the rest are counted.
LIST_LINES = 8


def day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def to_sign_title(title: str, *, new_version: bool) -> str:
    if new_version:
        # Translators: %(title)s is a policy's name, e.g. "Dori berish qoidalari".
        return _("New version to read and sign: %(title)s") % {"title": title}
    return _("Rules to read and sign: %(title)s") % {"title": title}


def sign_by(due_on: date) -> str:
    return _("Read them in the app and sign by %(date)s.") % {"date": day(due_on)}


def many_to_sign_title(count: int) -> str:
    return _("Rules to read and sign: %(count)d") % {"count": count}


def listed(lines: list[str]) -> list[str]:
    shown = list(lines[:LIST_LINES])
    if len(lines) > LIST_LINES:
        shown.append(_("And %(count)d more") % {"count": len(lines) - LIST_LINES})
    return shown


def many_to_sign_body(titles: list[str], due_on: date) -> str:
    return "\n".join([*listed(titles), sign_by(due_on)])


def to_read_title(title: str) -> str:
    return _("New rules to read: %(title)s") % {"title": title}


def to_read_body() -> str:
    return _("Read them in the app.")


def reminder_title(title: str, due_on: date, today: date) -> str:
    if today > due_on:
        return _("Still waiting for your signature: %(title)s") % {"title": title}
    if today == due_on:
        return _("Last day to sign: %(title)s") % {"title": title}
    if (due_on - today).days == 1:
        return _("Sign by tomorrow: %(title)s") % {"title": title}
    return _("Please read and sign: %(title)s") % {"title": title}


def reminder_body(due_on: date, today: date) -> str:
    if today > due_on:
        return _("The deadline was %(date)s. Read them in the app and sign.") % {
            "date": day(due_on)
        }
    return sign_by(due_on)


def late_title(title: str) -> str:
    return _("Not signed in time: %(title)s") % {"title": title}


def late_body(names: list[str], due_on: date) -> str:
    return "\n".join([*listed(names), _("Deadline: %(date)s") % {"date": day(due_on)}])
