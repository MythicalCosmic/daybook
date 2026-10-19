from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.members.models import Membership
from apps.tasks.models import Activity, Task
from apps.tasks.queries import awaiting_review_by

STREAK_LOOKBACK_DAYS = 365
# Finished from the assignee's point of view: waiting for a check counts.
FINISHED = (Task.Status.DONE, Task.Status.REVIEW)


def summary(member: Membership, now: datetime) -> dict:
    """The numbers on the mini app's home screen."""
    tz = ZoneInfo(member.company.timezone)
    start, end = _day_bounds(timezone.localtime(now, tz).date(), tz)
    mine = Task.objects.filter(assignee=member).exclude(status=Task.Status.CANCELLED)
    todays = list(mine.filter(due_at__gte=start, due_at__lt=end).values_list("status", flat=True))
    return {
        "today_total": len(todays),
        "today_done": sum(status in FINISHED for status in todays),
        "late": mine.filter(status__in=Task.OPEN_STATUSES, due_at__lt=now).count(),
        "streak_days": streak(member, now),
        "unread_activity": Activity.objects.filter(recipient=member, read_at__isnull=True).count(),
        "awaiting_review": awaiting_review_by(member).count(),
    }


def streak(member: Membership, now: datetime) -> int:
    """Days in a row on which everything due was finished that same day.

    Days with nothing due neither count nor break it, and today only counts once it's all done.
    """
    tz = ZoneInfo(member.company.timezone)
    today = timezone.localtime(now, tz).date()
    since, _ = _day_bounds(today - timedelta(days=STREAK_LOOKBACK_DAYS), tz)
    _, until = _day_bounds(today, tz)
    tasks = (
        Task.objects.filter(assignee=member, due_at__gte=since, due_at__lt=until)
        .exclude(status=Task.Status.CANCELLED)
        .values_list("due_at", "status", "completed_at")
    )
    days: dict[date, bool] = {}
    for due_at, status, completed_at in tasks:
        day = timezone.localtime(due_at, tz).date()
        _, day_end = _day_bounds(day, tz)
        on_time = status in FINISHED and completed_at is not None and completed_at < day_end
        days[day] = days.get(day, True) and on_time

    count = 0
    for day in sorted(days, reverse=True):
        if days[day]:
            count += 1
        elif day != today:  # today isn't over yet
            break
    return count


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)
