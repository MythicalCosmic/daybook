"""Payment reminders (Package I, §10.1 `finance.tasks.remind_payments`, §10.2), sent in the
company's morning, once per person and item per day:

- a recurring bill (or a tax) from `remind_days_before` days before its due day until it is
  paid or skipped, to its payer (or, without one, to the finance managers who see it), with
  [Paid from <account>] when it has a usual account and a fixed amount, and [Tomorrow];
- an automatic payment that couldn't post (a closed period, not enough money);
- an overdue payable or receivable, to the person responsible for it, on the day it falls due
  and then weekly.
"""

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from apps.core.exceptions import DomainError
from apps.core.money import format_money
from apps.finance import access, recurring
from apps.finance.models import Debt, RecurringRule
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm

logger = logging.getLogger(__name__)

MORNING = (9, 12)  # company-local hours, from 09:00 to before 12:00
DEBT_EVERY = 7  # days between reminders of the same overdue debt
PAID = "paid"
LATER = "later"


def remind(now: datetime | None = None) -> int:
    """Every 15 minutes: the reminders due this morning; returns how many notifications."""
    from apps.companies.models import Company

    now = now or timezone.now()
    sent = 0
    for company in Company.objects.filter(features__contains=["finance"]).order_by("pk"):
        local = timezone.localtime(now, ZoneInfo(company.timezone))
        if not MORNING[0] <= local.hour < MORNING[1]:
            continue
        try:
            sent += remind_bills(company, local.date()) + remind_debts(company, local.date())
        except Exception:  # one company's trouble never stops the others
            logger.exception("Payment reminders failed for company %s", company.pk)
    return sent


def due_text(due: date, today: date) -> str:
    if due < today:
        return _("overdue since %(date)s") % {"date": due.strftime("%d.%m.%Y")}
    if due == today:
        return _("due today")
    if due == today + timedelta(days=1):
        return _("due tomorrow")
    return _("due %(date)s") % {"date": due.strftime("%d.%m.%Y")}


def _money(amount, currency, person: Membership) -> str:
    return format_money(amount, currency, (person.user.language or "uz")[:2])


def bill_recipients(rule: RecurringRule) -> list[Membership]:
    payer = rule.payer
    if payer is not None and payer.status == Membership.Status.APPROVED:
        return [payer]
    from apps.members.queries import members_with_perm

    people = members_with_perm(rule.company, Perm.FINANCE_MANAGE).select_related("user", "role")
    found = []
    for person in people:
        branches = scope.branch_ids(person)
        if branches is None or (rule.branch_id is not None and rule.branch_id in branches):
            found.append(person)
    return found


def remind_bills(company, today: date) -> int:
    from apps.inbox.services import NotificationAction, notify

    rules = list(
        RecurringRule.objects.filter(company=company, is_active=True, next_due_on__isnull=False)
        .exclude(last_reminded_on=today)
        .filter(next_due_on__lte=today + timedelta(days=30 + recurring.MAX_SHIFT))
        .select_related("company", "account", "category", "counterparty", "payer__user")
    )
    if not rules:
        return 0
    days_off = recurring.holidays(company, min(r.next_due_on for r in rules), today)
    sent = 0
    for rule in rules:
        due = recurring.shift(rule.next_due_on, rule.on_holiday, days_off)
        if rule.mode == RecurringRule.Mode.AUTO:
            if due >= today:
                continue  # it posts itself; only one that couldn't is worth a word
        elif today < due - timedelta(days=rule.remind_days_before):
            continue
        if rule.create_task and rule.mode == RecurringRule.Mode.BILL:
            _payer_task(rule, due, today)
        people = bill_recipients(rule)
        if not people:
            continue
        payable = (
            rule.mode == RecurringRule.Mode.BILL
            and rule.account_id is not None
            and not rule.amount_varies
        )
        known = not (rule.amount_varies and not rule.amount)

        def title(person, rule=rule, due=due, known=known) -> str:
            with translation.override(person.user.language):
                parts = [rule.name]
                if known:
                    parts.append(_money(rule.amount, rule.currency, person))
                parts.append(due_text(due, today))
                return " · ".join(parts)

        def body(person, rule=rule, due=due) -> str:
            with translation.override(person.user.language):
                if rule.mode == RecurringRule.Mode.AUTO:
                    return _("It couldn't be posted automatically. Check the account.")
                if rule.amount_varies:
                    return _("The amount varies: enter what you paid when you pay it.")
                return ""

        actions = []
        if payable:
            actions.append(
                NotificationAction(
                    PAID,
                    lambda person, rule=rule: (
                        _("Paid from %(account)s") % {"account": rule.account.name}
                    ),
                    "primary",
                )
            )
        actions.append(NotificationAction(LATER, gettext_lazy("Tomorrow"), "default"))
        made = notify(
            people,
            "finance.bill_due",
            title=title,
            body=body,
            url=f"/c/{company.pk}/finance/recurring?rule={rule.pk}",
            target=rule,
            actions=actions,
            data={"occurrence": rule.next_due_on.isoformat()},
            dedupe_key=f"finance:bill:{rule.pk}:{rule.next_due_on.isoformat()}:{today.isoformat()}",
            severity="warning" if due < today else None,
        )
        RecurringRule.objects.filter(pk=rule.pk).update(last_reminded_on=today)
        sent += len(made)
    return sent


TASK_DUE_AT = (18, 0)  # the bill's due day, company time


def _payer_task(rule: RecurringRule, due: date, today: date) -> None:
    """Once per occurrence, when its reminders start: the payer's task to pay it, due on the
    bill's day; it closes by itself when the bill is paid or skipped (`recurring._finish_task`).
    Nothing when the payer isn't working here or the task was already made."""
    from apps.tasks.services import create_system_task

    payer = rule.payer
    if (
        payer is None
        or rule.task_for == rule.next_due_on
        or payer.status != Membership.Status.APPROVED
        or payer.onboarded_at is None
    ):
        return
    zone = ZoneInfo(rule.company.timezone)
    due_at = datetime.combine(due, time(*TASK_DUE_AT), tzinfo=zone)
    soonest = timezone.now() + timedelta(hours=2)
    with translation.override(payer.user.language or "uz"):
        known = not (rule.amount_varies and not rule.amount)
        title = _("Pay: %(name)s") % {"name": rule.name}
        lines = []
        if known:
            lines.append(_money(rule.amount, rule.currency, payer))
        lines.append(due_text(due, today))
        lines.append(
            _(
                "Mark it paid in Finance or with Paid in the reminder: "
                "this task then closes by itself."
            )
        )
        try:
            task = create_system_task(
                rule.company,
                assignee=payer,
                title=title,
                due_at=max(due_at, soonest),
                description="\n".join(lines),
            )
        except DomainError as exc:
            logger.info("No task for recurring rule %s: %s", rule.pk, exc)
            return
    RecurringRule.objects.filter(pk=rule.pk).update(task=task, task_for=rule.next_due_on)
    rule.task, rule.task_for = task, rule.next_due_on


def remind_debts(company, today: date) -> int:
    from apps.inbox.services import notify

    debts = (
        Debt.objects.filter(
            company=company,
            status=Debt.Status.OPEN,
            counterparty__isnull=False,
            responsible__isnull=False,
            responsible__status=Membership.Status.APPROVED,
            due_on__isnull=False,
            due_on__lte=today,
        )
        .exclude(last_reminded_on__gt=today - timedelta(days=DEBT_EVERY))
        .select_related("counterparty", "responsible__user")
        .order_by("responsible_id", "due_on", "pk")
    )
    # One message per person a day: a single debt in full, several as a digest (someone who
    # looks after forty nasiya customers gets one message, not forty).
    by_person: dict[int, list[Debt]] = {}
    for debt in debts:
        by_person.setdefault(debt.responsible_id, []).append(debt)
    sent = 0
    for rows in by_person.values():
        person = rows[0].responsible
        if len(rows) == 1:
            debt = rows[0]
            made = notify(
                [person],
                "finance.debt_due",
                title=lambda person, debt=debt: debt_line(debt, today, person),
                body=lambda person, debt=debt: debt.description,
                url=f"/c/{company.pk}/finance/debts?debt={debt.pk}",
                target=debt,
                dedupe_key=f"finance:debt:{debt.pk}:{today.isoformat()}",
            )
        else:
            count = len(rows)
            made = notify(
                [person],
                "finance.debt_due",
                title=lambda person, count=count: _digest_title(person, count),
                body=lambda person, rows=rows: (
                    "\n".join(debt_line(debt, today, person) for debt in rows[:DIGEST_LINES])
                    + (f"\n…{len(rows) - DIGEST_LINES}" if len(rows) > DIGEST_LINES else "")
                ),
                url=f"/c/{company.pk}/finance/debts?overdue=true",
                dedupe_key=f"finance:debts:{person.pk}:{today.isoformat()}",
            )
        Debt.objects.filter(pk__in=[debt.pk for debt in rows]).update(last_reminded_on=today)
        sent += len(made)
    return sent


DIGEST_LINES = 10


def debt_line(debt: Debt, today: date, person: Membership) -> str:
    """ "Owed to us: Shifo klinikasi · 2 000 000 UZS · 5 days overdue", in `person`'s language."""
    late = (today - debt.due_on).days
    with translation.override(person.user.language):
        owed = (
            _("Owed to us: %(party)s")
            if debt.direction == Debt.Direction.RECEIVABLE
            else _("We owe: %(party)s")
        ) % {"party": debt.counterparty.name}
        when = (
            _("due today")
            if late == 0
            else ngettext("%(days)s day overdue", "%(days)s days overdue", late) % {"days": late}
        )
        return " · ".join([owed, _money(debt.amount - debt.paid, debt.currency, person), when])


def _digest_title(person: Membership, count: int) -> str:
    with translation.override(person.user.language):
        return ngettext(
            "%(count)s debt you look after is due or overdue",
            "%(count)s debts you look after are due or overdue",
            count,
        ) % {"count": count}


# Inbox buttons ----------------------------------------------------------------------------------


def _rule(notification) -> RecurringRule:
    rule = (
        RecurringRule.objects.filter(company_id=notification.company_id, pk=notification.target_id)
        .select_related("company", "account")
        .first()
    )
    if rule is None:
        raise DomainError(_("This isn't available any more."))
    return rule


def paid_action(notification, by: Membership, reason: str) -> str:
    """[Paid from <account>]: pay the reminded occurrence from the rule's usual account."""
    rule = _rule(notification)
    occurrence = (notification.data or {}).get("occurrence")
    if rule.next_due_on is None or rule.next_due_on.isoformat() != occurrence:
        return str(_("Already paid."))
    if rule.account_id is None or rule.amount_varies:
        raise DomainError(_("Open the dashboard to enter the amount."))
    if not access.recordable_accounts(by).filter(pk=rule.account_id).exists():
        raise DomainError(
            _("You can't record payments on %(account)s.") % {"account": rule.account}
        )
    try:
        with transaction.atomic():
            # The occurrence is checked again under the rule's lock: someone may have paid it
            # in the dashboard since it was read above.
            recurring.pay_occurrence(
                rule, by=by, account=rule.account, occurrence=date.fromisoformat(occurrence)
            )
    except recurring.Settled:
        return str(_("Already paid."))
    return str(_("Paid from %(account)s.") % {"account": rule.account.name})


def later_action(notification, by: Membership, reason: str) -> str:
    return str(_("I'll remind you tomorrow."))
