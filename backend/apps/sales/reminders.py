"""Overdue nasiya and invoices (docs/PLAN-OWNER.md §10.1 `sales.tasks.remind_customer_debts`,
§10.2): in each company's morning, the person responsible for an overdue customer debt the
sales module opened (a credit sale at the till, an invoice) hears about it once a day, one
message per person (a digest when several are due).

`Debt.last_reminded_on` is shared with finance's weekly debt reminders: a debt reminded today by
either is skipped by the other, so nobody hears about the same debt twice in a morning.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.utils import timezone, translation
from django.utils.translation import ngettext

from apps.companies.models import Company, Feature
from apps.members.models import Membership
from apps.sales import bot_messages as msg

logger = logging.getLogger(__name__)

MORNING = (9, 12)  # company-local hours, from 09:00 to before 12:00
SOURCES = ("sales.creditentry", "sales.invoice")
DIGEST_LINES = 10


def remind(now: datetime | None = None) -> int:
    """Every 15 minutes: this morning's reminders; returns how many notifications went out."""
    now = now or timezone.now()
    sent = 0
    for company in Company.objects.filter(is_active=True, features__contains=[Feature.SALES]):
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if not MORNING[0] <= local.hour < MORNING[1]:
            continue
        try:
            sent += remind_company(company, local.date())
        except Exception:  # one company's trouble never stops the others
            logger.exception("Customer debt reminders failed for company %s", company.pk)
    return sent


def overdue(company, today: date):
    from apps.finance.models import Debt

    return (
        Debt.objects.filter(
            company=company,
            direction=Debt.Direction.RECEIVABLE,
            status=Debt.Status.OPEN,
            source_type__in=SOURCES,
            counterparty__isnull=False,
            responsible__isnull=False,
            responsible__status=Membership.Status.APPROVED,
            due_on__lt=today,
        )
        .exclude(last_reminded_on=today)
        .select_related("counterparty", "responsible__user", "company")
        .order_by("responsible_id", "due_on", "pk")
    )


def line(debt, today: date) -> str:
    left = debt.amount - debt.paid
    days = (today - debt.due_on).days
    return ngettext(
        "%(customer)s: %(amount)s, %(days)s day overdue",
        "%(customer)s: %(amount)s, %(days)s days overdue",
        days,
    ) % {"customer": debt.counterparty.name, "amount": msg.money(left, debt.currency), "days": days}


def remind_company(company, today: date) -> int:
    from apps.finance.models import Debt
    from apps.inbox.services import notify

    by_person: dict[int, list] = {}
    for debt in overdue(company, today):
        by_person.setdefault(debt.responsible_id, []).append(debt)
    sent = 0
    for rows in by_person.values():
        person = rows[0].responsible
        count = len(rows)
        with translation.override(company.default_language):
            if count == 1:
                debt = rows[0]
                made = notify(
                    [person],
                    "sales.customer_debt_due",
                    title=lambda member, debt=debt: line(debt, today),
                    body=lambda member, debt=debt: debt.description,
                    url=f"/c/{company.pk}/sales/customers?customer={debt.counterparty_id}",
                    target=debt,
                    dedupe_key=f"sales:debt:{debt.pk}:{today.isoformat()}",
                )
            else:
                made = notify(
                    [person],
                    "sales.customer_debt_due",
                    title=lambda member, count=count: (
                        ngettext(
                            "%(count)s customer debt is overdue",
                            "%(count)s customer debts are overdue",
                            count,
                        )
                        % {"count": count}
                    ),
                    body=lambda member, rows=rows: (
                        "\n".join(line(debt, today) for debt in rows[:DIGEST_LINES])
                        + (f"\n…{len(rows) - DIGEST_LINES}" if len(rows) > DIGEST_LINES else "")
                    ),
                    url=f"/c/{company.pk}/sales/customers?owing=1",
                    dedupe_key=f"sales:debts:{person.pk}:{today.isoformat()}",
                )
        Debt.objects.filter(pk__in=[debt.pk for debt in rows]).update(last_reminded_on=today)
        sent += len(made)
    return sent
