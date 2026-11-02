"""Months and days in each company's own calendar (a payroll period is a month, kept as its
first day)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError


def first_day(day: date) -> date:
    return day.replace(day=1)


def last_day(period: date) -> date:
    following = (period.replace(day=1) + timedelta(days=32)).replace(day=1)
    return following - timedelta(days=1)


def bounds(period: date) -> tuple[date, date]:
    """The first and the last day of `period`'s month."""
    start = first_day(period)
    return start, last_day(start)


def next_period(period: date) -> date:
    return last_day(period) + timedelta(days=1)


def previous_period(period: date) -> date:
    return first_day(first_day(period) - timedelta(days=1))


def add_months(period: date, months: int) -> date:
    index = period.year * 12 + period.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def days(start: date, end: date):
    """Every day from `start` to `end`, both included."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def zone(company) -> ZoneInfo:
    return ZoneInfo(company.timezone)


def today(company, now: datetime | None = None) -> date:
    return timezone.localtime(now or timezone.now(), zone(company)).date()


def local(company, moment: datetime) -> datetime:
    return timezone.localtime(moment, zone(company))


def parse_period(value) -> date:
    """`2026-10` or any day of the month (`2026-10-01`) as the month's first day."""
    if isinstance(value, date):
        return first_day(value)
    text = str(value or "").strip()
    try:
        if len(text) == 7:
            return datetime.strptime(text, "%Y-%m").date()
        return first_day(date.fromisoformat(text))
    except ValueError:
        raise DomainError(_("Give a month as YYYY-MM.")) from None
