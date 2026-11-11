"""Loan payments and tax deadlines, reminded at the company's morning hour (v12).

`reminders.remind` (every 15 minutes) calls `remind(company, local)` for each company with the
finance module; it sends only in the two hours from `Company.morning_report_at` (the hour the
morning report goes out), and every notification is deduplicated per item and day, so a company
hears about each payment or deadline at most once a day.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from apps.finance import loans, taxes

logger = logging.getLogger(__name__)


def in_morning(local: datetime, company) -> bool:
    from apps.reports.periods import in_window

    return in_window(local, company.morning_report_at)


def remind(company, local: datetime) -> int:
    """The reminders of loans and taxes due this morning; how many notifications."""
    if not in_morning(local, company):
        return 0
    today: date = local.date()
    sent = 0
    for name, job in (("loans", loans.remind), ("taxes", taxes.remind)):
        try:
            sent += job(company, today)
        except Exception:  # one part's trouble never stops the other
            logger.exception("%s reminders failed for company %s", name, company.pk)
    return sent
