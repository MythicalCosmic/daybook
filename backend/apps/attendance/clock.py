"""Days and moments in each company's own calendar.

A shift's `date` is the local day it starts on; times on schedules and templates are local wall
clock times. A shift whose end is not after its start ends the next day (overnight).
"""

import zoneinfo
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from django.utils import timezone


def zone(company) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(company.timezone)


def local(company, moment: datetime) -> datetime:
    return timezone.localtime(moment, zone(company))


def today(company, now: datetime | None = None) -> date:
    return local(company, now or timezone.now()).date()


def at(company, day: date, clock: time) -> datetime:
    """`clock` on `day` in the company's timezone, as an aware moment."""
    return datetime.combine(day, clock, tzinfo=zone(company))


def window(company, day: date, starts: time, ends: time) -> tuple[datetime, datetime]:
    """A shift's start and end; an end at or before the start is on the next day."""
    start = at(company, day, starts)
    end = at(company, day, ends)
    if end <= start:
        end = at(company, day + timedelta(days=1), ends)
    return start, end


def minutes_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def days(start: date, end: date) -> Iterator[date]:
    """Every day from `start` to `end`, both included."""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


def hhmm(company, moment: datetime | None) -> str:
    return local(company, moment).strftime("%H:%M") if moment else ""


def day_month(day: date) -> str:
    return day.strftime("%d.%m")
