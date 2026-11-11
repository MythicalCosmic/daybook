"""A supplier's payment terms (v12): when what it delivers on credit is due.

A counterparty may have terms (`Counterparty.credit_days` or `credit_day`, at most one):
    credit_days  N days after delivery ("30 kun", net 30);
    credit_day   on day D of the month after delivery ("keyingi oyning 10-sanasi"); the month's
                 last day when it is shorter.
A payable for goods or a bill on credit (`Debt.kind` trade or bill) opened without a due date
gets one from them (`services.open_debt`), whoever opens it: the debts page, a goods receipt
(`apps.inventory`), a purchase. A due date someone typed always wins. Then the payables list,
the payments calendar, the cash forecast and the overdue views follow by themselves.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from django.utils.translation import gettext as _
from django.utils.translation import ngettext

# The kinds of payable whose due date comes from the supplier's terms.
KINDS = ("trade", "bill")


def has_terms(party) -> bool:
    return party is not None and (party.credit_days is not None or party.credit_day is not None)


def due_on(party, delivered_on: date) -> date | None:
    """The day a delivery of `delivered_on` is due under the party's terms (None: no terms)."""
    if party is None:
        return None
    if party.credit_days is not None:
        return delivered_on + timedelta(days=party.credit_days)
    if party.credit_day is not None:
        year = delivered_on.year + delivered_on.month // 12
        month = delivered_on.month % 12 + 1
        return date(year, month, min(party.credit_day, calendar.monthrange(year, month)[1]))
    return None


def describe(party) -> str:
    """The terms in words, in the active language ("" without terms)."""
    if party is None:
        return ""
    if party.credit_days is not None:
        return ngettext(
            "%(days)s day after delivery", "%(days)s days after delivery", party.credit_days
        ) % {"days": party.credit_days}
    if party.credit_day is not None:
        return _("Day %(day)s of the next month") % {"day": party.credit_day}
    return ""


def applies(direction: str, kind: str, party, due: date | None) -> bool:
    return direction == "payable" and kind in KINDS and due is None and has_terms(party)
