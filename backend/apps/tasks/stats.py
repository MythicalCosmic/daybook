from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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


def summary(member: Membership, now: datetime) -> dict:
    """The numbers on the mini app's home screen."""
    tz = ZoneInfo(member.company.timezone)
    start, end = _day_bounds(timezone.localtime(now, tz).date(), tz)
    mine = Task.objects.filter(assignee=member).exclude(status=Task.Status.CANCELLED)
    todays = list(mine.filter(due_at__gte=start, due_at__lt=end).values_list("status", flat=True))
    days = _day_results(member, now, lookback=STREAK_LOOKBACK_DAYS)
    today = timezone.localtime(now, tz).date()
    month_start, _ = _day_bounds(today.replace(day=1), tz)
    month = mine.filter(completed_at__gte=month_start, status__in=FINISHED)
    # Only deadlines already behind us count: a task due tonight isn't late yet.
    dated = list(
        mine.filter(due_at__gte=month_start, due_at__lt=now).values_list(
            "status", "completed_at", "due_at"
        )
    )
    finished_dated = [row for row in dated if row[0] in FINISHED]
    policy = default_policy(member.company_id)
    return {
        "today_total": len(todays),
        "today_done": sum(status in FINISHED for status in todays),
        "late": mine.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now).count(),
        "streak_days": _streak(days, today),
        "week": _week(days, today),
        "month_done": month.count(),
        "month_on_time_percent": (
            round(100 * sum(_in_time(done, due) for _, done, due in finished_dated) / len(dated))
            if dated
            else None
        ),
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
    """For each day `member` had shared work due: whether all of it was finished on time."""
    tz = ZoneInfo(member.company.timezone)
    today = timezone.localtime(now, tz).date()
    since, _ = _day_bounds(today - timedelta(days=lookback), tz)
    _, until = _day_bounds(today, tz)
    tasks = (
        Task.objects.filter(
            assignee=member, kind__in=STREAK_KINDS, due_at__gte=since, due_at__lt=until
        )
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    )
    days: dict[date, bool] = {}
    for due_at, status, completed_at in tasks:
        day = timezone.localtime(due_at, tz).date()
        on_time = status in FINISHED and completed_at is not None and completed_at <= due_at
        days[day] = days.get(day, True) and on_time
    return days


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


def _in_time(completed_at: datetime | None, due_at: datetime) -> bool:
    return completed_at is not None and completed_at <= due_at


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)
