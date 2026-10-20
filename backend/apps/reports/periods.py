"""Report periods and send times, in each company's own calendar."""

from datetime import date, datetime, time, timedelta

from django.db import models
from django.utils.translation import gettext_lazy as _

# The owner dashboard's analytics ranges (PLAN-OWNER §3.1); packages import them from here.
from apps.console.ranges import Range as Range
from apps.console.ranges import RangeError as RangeError
from apps.console.ranges import parse_range as parse_range

# A report goes out within this long after its time, not hours late.
REPORT_WINDOW = timedelta(hours=2)


class Period(models.TextChoices):
    WEEK = "week", _("This week")
    LAST_WEEK = "last_week", _("Last week")
    MONTH = "month", _("This month")
    LAST_MONTH = "last_month", _("Last month")


def bounds(period: Period, today: date) -> tuple[date, date]:
    """The period's first day and the day after its last. Weeks start on Monday."""
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    match period:
        case Period.WEEK:
            return week, week + timedelta(days=7)
        case Period.LAST_WEEK:
            return week - timedelta(days=7), week
        case Period.MONTH:
            return month, (month + timedelta(days=32)).replace(day=1)
        case Period.LAST_MONTH:
            return (month - timedelta(days=1)).replace(day=1), month
    raise ValueError(period)


def in_window(local: datetime, at: time) -> bool:
    """Whether a report due at `at` (local time) should go out now."""
    start = local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return start <= local < start + REPORT_WINDOW
