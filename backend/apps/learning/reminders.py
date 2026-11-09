"""Deadlines of training (docs/PLAN-LEARNING.md §4.5), run hourly; each company is handled at its
morning hour (`Company.morning_report_at`, 09:00 by default) or the first run after it:

- due within `remind_before_days` → one reminder (`learning.due_soon`);
- late → a notice on the first late day, then every 3 days, at most 3 (`learning.overdue`);
- `escalate_after_days` late → one notice to the person's managers: their department head
  (`apps.members.departments`), else the holders of `learning.manage` who see them; one digest
  per manager ("3 people are late with training", `learning.escalated`).

Each person hears once per run about all their courses. Nobody hears anything on a day of
approved time off, and suspended people get no reminders (their assignments stay).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import time

from django.db import transaction
from django.db.models import F
from django.utils import timezone, translation

from apps.learning import conf, courses, notify_courses, queries
from apps.learning.models import Assignment, Status
from apps.members.departments import Org
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import in_scope, members_with_perm
from apps.timeoff.queries import members_off

NOTICE_EVERY_DAYS = 3
MAX_NOTICES = 3
MORNING = time(9, 0)


def send_reminders(now=None) -> int:
    """Returns how many notifications went out."""
    now = now or timezone.now()
    sent = 0
    for company in courses.companies_on():
        local = timezone.localtime(now, queries.zone(company))
        if local.time() < (company.morning_report_at or MORNING):
            continue
        with translation.override(company.default_language):
            sent += remind_company(company, now)
    return sent


def _managers(person: Membership, org: Org, holders: list[Membership]) -> list[Membership]:
    head = org.head_above(person) if org else None
    if head is not None:
        return [head]
    return [holder for holder in holders if holder.pk != person.pk and in_scope(holder, person)]


def remind_company(company, now) -> int:
    settings_row = conf.get_settings(company)
    today = queries.local_day(company, now)
    away = members_off(company, today)
    rows = (
        Assignment.objects.filter(
            company=company,
            state__in=queries.OPEN,
            due_at__isnull=False,
            membership__status=Membership.Status.APPROVED,
        )
        .filter(course__status=Status.PUBLISHED, course__archived_at__isnull=True)
        .exclude(membership_id__in=away)
        .select_related("course", "membership__user", "membership__company", "membership__role")
        .order_by("due_at", "pk")
    )
    soon: dict[int, list[Assignment]] = defaultdict(list)
    late: dict[int, list[Assignment]] = defaultdict(list)
    escalate: list[tuple[Assignment, int]] = []
    for row in rows:
        if row.due_at >= now:
            days_left = (queries.local_day(company, row.due_at) - today).days
            if (
                settings_row.remind_before_days
                and row.reminded_at is None
                and days_left <= settings_row.remind_before_days
            ):
                soon[row.membership_id].append(row)
            continue
        if row.overdue_notices < MAX_NOTICES and (
            row.overdue_notices == 0
            or row.reminded_at is None
            or (today - queries.local_day(company, row.reminded_at)).days >= NOTICE_EVERY_DAYS
        ):
            late[row.membership_id].append(row)
        days = queries.days_late(company, row.due_at, now)
        if (
            settings_row.escalate_after_days
            and row.escalated_at is None
            and days >= settings_row.escalate_after_days
        ):
            escalate.append((row, days))
    sent = 0
    with transaction.atomic():
        for items in soon.values():
            sent += notify_courses.due_soon(items[0].membership, items)
            Assignment.objects.filter(pk__in=[row.pk for row in items]).update(reminded_at=now)
        for items in late.values():
            sent += notify_courses.overdue(items[0].membership, items, day=today)
            Assignment.objects.filter(pk__in=[row.pk for row in items]).update(
                overdue_notices=F("overdue_notices") + 1, reminded_at=now
            )
        if escalate:
            sent += _escalate(company, escalate, today=today, now=now)
    return sent


def _escalate(company, escalate: list[tuple[Assignment, int]], *, today, now) -> int:
    org = Org(company.pk)
    holders = list(
        members_with_perm(company, Perm.LEARNING_MANAGE).select_related("user", "role", "company")
    )
    digests: dict[int, list[tuple[Membership, Assignment, int]]] = defaultdict(list)
    recipients: dict[int, Membership] = {}
    for row, days in sorted(escalate, key=lambda item: -item[1]):
        for manager in _managers(row.membership, org, holders):
            recipients[manager.pk] = manager
            digests[manager.pk].append((row.membership, row, days))
    sent = 0
    for manager_id, entries in digests.items():
        sent += notify_courses.escalated(recipients[manager_id], entries, day=today)
    Assignment.objects.filter(pk__in=[row.pk for row, _days in escalate]).update(escalated_at=now)
    return sent
