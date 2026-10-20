"""The periodic work behind attendance's Celery tasks (docs/PLAN-OWNER.md §10.1).

Every job walks the active companies with the module switched on; one company's failure is
logged and never stops the others. Jobs that run every few minutes act once per shift or
day through `notify.mark_once`.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from django.utils import timezone

from apps.attendance import clock, conf, notify, queries, rules, services
from apps.attendance.models import AttendanceRecord, JobMark, WorkShift
from apps.companies.models import Branch, Company
from apps.members.models import Membership
from apps.timeoff.models import Holiday

logger = logging.getLogger(__name__)

# Job marks older than this are cleared (they only guard against repeats within a day).
MARK_KEEP_DAYS = 30


def companies():
    return Company.objects.filter(is_active=True, features__contains=["attendance"]).order_by("pk")


def _each(job: Callable[[Company, datetime], int], now: datetime | None = None) -> int:
    now = now or timezone.now()
    total = 0
    for company in companies():
        try:
            total += job(company, now) or 0
        except Exception:
            logger.exception("attendance job %s failed for company %s", job.__name__, company.pk)
    return total


def generate_shifts(now: datetime | None = None) -> int:
    return _each(lambda company, at: services.generate_shifts(company, now=at), now)


def auto_close(now: datetime | None = None) -> int:
    return _each(services.auto_close, now)


def close_days(now: datetime | None = None) -> int:
    total = _each(services.mark_absences, now)
    JobMark.objects.filter(
        created_at__lt=(now or timezone.now()) - timedelta(days=MARK_KEEP_DAYS)
    ).delete()
    return total


def expire_swaps(now: datetime | None = None) -> int:
    return services.expire_swaps(now)


def shift_nudges(now: datetime | None = None) -> int:
    return _each(nudge_company, now)


def nudge_company(company: Company, now: datetime) -> int:
    """Pre-shift reminders (when switched on), "your shift started" after
    `remind_after_minutes`, the no-show alert to managers after `no_show_alert_minutes`,
    "still working?" an hour after the end, and each branch's morning "who's in" post."""
    settings = conf.get_settings(company)
    pre = timedelta(minutes=settings.pre_shift_reminder_minutes)
    remind = timedelta(minutes=settings.remind_after_minutes)
    no_show = timedelta(minutes=settings.no_show_alert_minutes)
    sent = 0
    shifts = (
        WorkShift.objects.working()
        .filter(company=company, starts_at__lte=now + pre, ends_at__gt=now)
        .select_related("membership__user", "membership__company", "branch", "company")
    )
    started = {
        shift_id
        for shift_id in AttendanceRecord.objects.filter(
            company=company, shift__in=shifts
        ).values_list("shift_id", flat=True)
    }
    for shift in shifts:
        member = shift.membership
        if member.status != Membership.Status.APPROVED or shift.pk in started:
            continue
        before_start = pre and shift.starts_at - pre <= now < shift.starts_at
        if before_start and notify.mark_once(company.pk, f"pre:{shift.pk}"):
            sent += notify.nudge_pre_shift(shift)
        if shift.starts_at + remind <= now and notify.mark_once(company.pk, f"late:{shift.pk}"):
            sent += notify.nudge_late(shift)
        if shift.starts_at + no_show <= now and notify.mark_once(company.pk, f"noshow:{shift.pk}"):
            notify.no_show(shift.pk, False)
            sent += 1
    still = timedelta(minutes=rules.STILL_WORKING_AFTER_MINUTES)
    open_records = AttendanceRecord.objects.filter(
        company=company,
        status=AttendanceRecord.Status.OPEN,
        shift__isnull=False,
        shift__ends_at__lte=now - still,
        shift__ends_at__gt=now - timedelta(hours=settings.auto_close_after_hours),
    ).select_related("membership__user", "shift", "company")
    for record in open_records:
        if notify.mark_once(company.pk, f"still:{record.pk}"):
            sent += notify.ask_still_working(record)
    sent += _morning_posts(company, now)
    return sent


MORNING_DELAY = timedelta(minutes=30)
MORNING_WINDOW = timedelta(hours=2)


def _morning_posts(company: Company, now: datetime) -> int:
    local = clock.local(company, now)
    today = local.date()
    if Holiday.objects.filter(company=company, date=today).exists():
        return 0
    posted = 0
    for branch in Branch.objects.filter(company=company, is_active=True, opens_at__isnull=False):
        if today.weekday() not in (branch.open_weekdays or []):
            continue
        due = clock.at(company, today, branch.opens_at) + MORNING_DELAY
        if not due <= now < due + MORNING_WINDOW:
            continue
        if not notify.mark_once(company.pk, f"morning:{branch.pk}:{today.isoformat()}"):
            continue
        board = queries.day_board(company, today, branch_ids=[branch.pk], now=now)
        rows = [
            row for row in board["people"] if row["branch"] and row["branch"]["id"] == branch.pk
        ]
        rostered = sum(1 for row in rows if row["shift"] and row["state"] != queries.OFF)
        if rostered:
            posted += notify.morning_post(company, branch, rows, rostered)
    return posted
