"""What the bots say about sales and cash.

Every function returns text in the active language; `apps.inbox.services.notify` calls the
`(Membership) -> str` builders under each recipient's language. Money goes through
`apps.core.money.format_money`, so it reads "1 250 000 so‘m" / "1 250 000 сум".
"""

from decimal import Decimal

from django.utils import translation
from django.utils.translation import gettext as _

from apps.core.money import format_money


def money(amount: Decimal | None, currency: str = "UZS") -> str:
    if amount is None:
        return "—"
    return format_money(amount, currency, (translation.get_language() or "uz")[:2])


def signed(amount: Decimal | None, currency: str = "UZS") -> str:
    """A difference with its sign: "+12 000 so‘m", "-15 000 so‘m", "0"."""
    if amount is None:
        return "—"
    if amount == 0:
        return money(Decimal(0), currency)
    text = money(abs(amount), currency)
    return f"+{text}" if amount > 0 else f"−{text}"


# Handovers (to the receiver; to the owners when it didn't arrive) --------------------------


def handover_title(cashier: str, amount: Decimal, currency: str) -> str:
    return _("💵 %(person)s handed you %(amount)s") % {
        "person": cashier,
        "amount": money(amount, currency),
    }


def handover_body(till: str, reason: str) -> str:
    text = _("From %(till)s. Did you get it?") % {"till": till}
    return f"{text}\n{reason}" if reason else text


def handover_declined_title(amount: Decimal, currency: str) -> str:
    return _("⚠️ Handover not received: %(amount)s") % {"amount": money(amount, currency)}


def handover_declined_body(receiver: str, cashier: str, till: str, reason: str) -> str:
    text = _("%(receiver)s says the cash %(cashier)s handed over at %(till)s never arrived.") % {
        "receiver": receiver,
        "cashier": cashier,
        "till": till,
    }
    return f"{text}\n«{reason}»" if reason else text


def handover_late_title(amount: Decimal, currency: str, hours: int) -> str:
    return _("Handover of %(amount)s unconfirmed for %(hours)s h") % {
        "amount": money(amount, currency),
        "hours": hours,
    }


def handover_late_body(cashier: str, receiver: str, branch: str) -> str:
    return _("%(cashier)s → %(receiver)s at %(branch)s. Nobody has confirmed it yet.") % {
        "cashier": cashier,
        "receiver": receiver,
        "branch": branch,
    }


# Shifts --------------------------------------------------------------------------------


def difference_title(code: str, difference: Decimal) -> str:
    return _("Cash difference at %(shift)s: %(difference)s") % {
        "shift": code,
        "difference": signed(difference),
    }


def difference_body(cashier: str, branch: str, counted: Decimal, expected: Decimal) -> str:
    return _("%(cashier)s · %(branch)s. Counted %(counted)s, expected %(expected)s.") % {
        "cashier": cashier,
        "branch": branch,
        "counted": money(counted),
        "expected": money(expected),
    }


def float_title(code: str, difference: Decimal) -> str:
    return _("The float at %(shift)s differs by %(difference)s") % {
        "shift": code,
        "difference": signed(difference),
    }


def float_body(cashier: str, till: str, counted: Decimal, expected: Decimal) -> str:
    return _(
        "%(cashier)s counted %(counted)s when opening %(till)s; the last shift left %(expected)s."
    ) % {"cashier": cashier, "till": till, "counted": money(counted), "expected": money(expected)}


def closed_title(cashier: str, code: str, net: Decimal) -> str:
    return _("%(cashier)s closed %(shift)s: %(net)s") % {
        "cashier": cashier,
        "shift": code,
        "net": money(net),
    }


def closed_body(branch: str, difference: Decimal | None) -> str:
    if difference is None:
        return _("%(branch)s. The cash wasn't counted.") % {"branch": branch}
    return _("%(branch)s. Cash difference: %(difference)s.") % {
        "branch": branch,
        "difference": signed(difference),
    }


def verified_title(code: str) -> str:
    return _("✅ Shift %(shift)s verified") % {"shift": code}


def verified_body(difference: Decimal | None) -> str:
    if not difference:
        return _("No cash difference. Thank you!")
    return _("Cash difference: %(difference)s.") % {"difference": signed(difference)}


def disputed_title(code: str) -> str:
    return _("Shift %(shift)s needs another look") % {"shift": code}


def disputed_body(manager: str, reason: str) -> str:
    return f"{manager}: «{reason}»"


def ai_mismatch_title(code: str) -> str:
    return _("The photos of %(shift)s don't match the typed totals") % {"shift": code}


def ai_mismatch_body() -> str:
    return _("AI read other numbers on the Z-report or the terminal slip. Check before verifying.")


# Operational alerts ---------------------------------------------------------------------


def not_opened_title(branch: str) -> str:
    return _("%(branch)s hasn't opened yet") % {"branch": branch}


def not_opened_body(opens_at: str, minutes: int) -> str:
    return _("It opens at %(time)s; no till was open %(minutes)s minutes later.") % {
        "time": opens_at,
        "minutes": minutes,
    }


def not_closed_title(code: str) -> str:
    return _("%(shift)s is still open") % {"shift": code}


def not_closed_body(cashier: str, branch: str, closes_at: str) -> str:
    return _("%(cashier)s hasn't closed the till at %(branch)s (closes at %(time)s).") % {
        "cashier": cashier,
        "branch": branch,
        "time": closes_at,
    }


def till_open_title() -> str:
    return _("🧾 Your till is still open")


def till_open_body(code: str, branch: str) -> str:
    return _("%(shift)s at %(branch)s. Close the shift in Kassa.") % {
        "shift": code,
        "branch": branch,
    }


def big_payout_title(amount: Decimal, currency: str) -> str:
    return _("Big payout from a till: %(amount)s") % {"amount": money(amount, currency)}


def big_payout_body(person: str, till: str, reason: str) -> str:
    return _("%(person)s paid out from %(till)s: %(reason)s") % {
        "person": person,
        "till": till,
        "reason": reason,
    }


def over_limit_title(branch: str, amount: Decimal) -> str:
    return _("%(branch)s holds %(amount)s in cash") % {"branch": branch, "amount": money(amount)}


def over_limit_body(limit: Decimal) -> str:
    return _("That's above its limit of %(limit)s after closing. Move it to the bank.") % {
        "limit": money(limit)
    }


# Group posts (in the company's language) ------------------------------------------------


def group_shift_closed(code: str, branch: str, cashier: str, net: Decimal, difference) -> str:
    lines = [
        _("🧾 <b>%(shift)s</b> closed · %(branch)s") % {"shift": code, "branch": branch},
        cashier,
        _("Sales: %(net)s") % {"net": money(net)},
    ]
    if difference is not None:
        lines.append(_("Cash difference: %(difference)s") % {"difference": signed(difference)})
    return "\n".join(lines)


def group_evening(day_label: str, rows: list[tuple[str, Decimal, int]], total: Decimal, change):
    lines = [_("📊 <b>Sales · %(day)s</b>") % {"day": day_label}]
    for name, net, receipts in rows:
        lines.append(
            _("%(branch)s: %(net)s (%(receipts)s receipts)")
            % {"branch": name, "net": money(net), "receipts": receipts}
        )
    total_line = _("Total: <b>%(total)s</b>") % {"total": money(total)}
    if change is not None:
        total_line += " · " + _("%(change)s vs the same day last week") % {"change": change}
    lines.append(total_line)
    return "\n".join(lines)


# Button labels --------------------------------------------------------------------------


def received_label() -> str:
    return _("Received")


def not_received_label() -> str:
    return _("Not received")


def verify_label() -> str:
    return _("Verify")
