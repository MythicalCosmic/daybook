from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.members.models import Membership
from apps.reminders.policies import default_policy
from apps.tasks.models import Activity, Task
from apps.tasks.queries import awaiting_review_by
from apps.timeoff.queries import off_today

STREAK_LOOKBACK_DAYS = 365
# Finished from the assignee's point of view: waiting for a check counts.
FINISHED = (Task.Status.DONE, Task.Status.REVIEW)
# A streak counts shared work: routine work and tasks given by hand (project cards are given
# tasks too). Personal tasks never count (docs/PLAN-OWNER.md §3.16).
STREAK_KINDS = (Task.Kind.DAILY, Task.Kind.ASSIGNED)
# Finished by its deadline: done or waiting for a check, no later than it was due.
ON_TIME = Q(status__in=FINISHED, completed_at__lte=F("due_at"))


def summary(member: Membership, now: datetime) -> dict:
    """The numbers on the mini app's home screen."""
    tz = ZoneInfo(member.company.timezone)
    today = timezone.localtime(now, tz).date()
    start, end = _day_bounds(today, tz)
    month_start, _end = _day_bounds(today.replace(day=1), tz)
    # Only deadlines already behind us count for the month: a task due tonight isn't late yet.
    this_month = Q(due_at__gte=month_start, due_at__lt=now)
    today_due = Q(due_at__gte=start, due_at__lt=end)
    counts = (
        Task.objects.filter(assignee=member)
        .exclude(status=Task.Status.CANCELLED)
        .aggregate(
            today_total=Count("pk", filter=today_due),
            today_done=Count("pk", filter=today_due & Q(status__in=FINISHED)),
            late=Count("pk", filter=Q(status__in=Task.OPEN_STATUSES, due_at__lt=now)),
            month_done=Count("pk", filter=Q(completed_at__gte=month_start, status__in=FINISHED)),
            month_dated=Count("pk", filter=this_month),
            month_on_time=Count("pk", filter=this_month & ON_TIME),
        )
    )
    days = _day_results(member, now, lookback=STREAK_LOOKBACK_DAYS)
    dated = counts["month_dated"]
    policy = default_policy(member.company_id)
    return {
        "today_total": counts["today_total"],
        "today_done": counts["today_done"],
        "late": counts["late"],
        "streak_days": _streak(days, today),
        "week": _week(days, today),
        "month_done": counts["month_done"],
        "month_on_time_percent": round(100 * counts["month_on_time"] / dated) if dated else None,
        "quiet_from": policy.quiet_from,
        "quiet_until": policy.quiet_until,
        "unread_activity": Activity.objects.filter(recipient=member, read_at__isnull=True).count(),
        "awaiting_review": awaiting_review_by(member).count(),
        "off_today": off_today(member, today),
    }


def streak(member: Membership, now: datetime) -> int:
    """The one streak, wherever it shows (the mini app's home and profile, Person 360 on the
    dashboard): days in a row on which every shared task due that day (routine work and tasks
    given by hand, never personal ones) was finished on time, done or waiting for a check by its
    deadline.

    Days with nothing due (days off, holidays) neither count nor break it; today counts once all
    of it is finished on time, and doesn't break it before the day is over.
    """
    today = timezone.localtime(now, ZoneInfo(member.company.timezone)).date()
    return _streak(_day_results(member, now, lookback=STREAK_LOOKBACK_DAYS), today)


def _day_results(member: Membership, now: datetime, lookback: int) -> dict[date, bool]:
    """For each day `member` had shared work due: whether all of it was finished on time.
    Postgres sums the days up: a year of routines is thousands of tasks but at most 366 days."""
    tz = ZoneInfo(member.company.timezone)
    today = timezone.localtime(now, tz).date()
    since, _end = _day_bounds(today - timedelta(days=lookback), tz)
    _start, until = _day_bounds(today, tz)
    per_day = (
        Task.objects.filter(
            assignee=member, kind__in=STREAK_KINDS, due_at__gte=since, due_at__lt=until
        )
        .exclude(status=Task.Status.CANCELLED)
        .annotate(day=TruncDate("due_at", tzinfo=tz))
        .order_by()
        .values("day")
        .annotate(total=Count("pk"), on_time=Count("pk", filter=ON_TIME))
        .values_list("day", "total", "on_time")
    )
    return {day: total == on_time for day, total, on_time in per_day}


def _streak(days: dict[date, bool], today: date) -> int:
    count = 0
    for day in sorted(days, reverse=True):
        if days[day]:
            count += 1
        elif day != today:  # today isn't over yet
            break
    return count


def _week(days: dict[date, bool], today: date) -> list[dict]:
    week = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        if day == today:
            state = "done" if days.get(day) else "today"
        elif day not in days:
            state = "free"
        else:
            state = "done" if days[day] else "missed"
        week.append({"date": day, "state": state})
    return week


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)
