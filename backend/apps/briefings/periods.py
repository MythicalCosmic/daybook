"""The periods a review covers, in the company's calendar.

A weekly review covers the last whole week (Monday to Sunday) before the day it is written,
compared with the week before and with the average of the four weeks before it; a monthly one
covers the last whole month, compared with the month before and the average of the three
months before.

    period = periods.latest("weekly", today)   # Period(start=Mon, end=Sun, previous=…, …)
    periods.is_due(settings, "weekly", local_now)
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from apps.briefings.models import Briefing, BriefingSettings

WEEKS_AVERAGED = 4
MONTHS_AVERAGED = 3
# A monthly review missed on the first still goes out on the days after, up to this day.
MONTHLY_CATCH_UP = 7


@dataclass(frozen=True)
class Period:
    kind: str
    start: date
    end: date
    previous: tuple[date, date]
    # The periods before `start` whose average the review compares with, and how many.
    average: tuple[date, date]
    count: int

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "previous": {
                "start": self.previous[0].isoformat(),
                "end": self.previous[1].isoformat(),
            },
            "average": {
                "start": self.average[0].isoformat(),
                "end": self.average[1].isoformat(),
                "periods": self.count,
            },
        }


def _month_start(day: date, back: int = 0) -> date:
    month = day.year * 12 + day.month - 1 - back
    return date(month // 12, month % 12 + 1, 1)


def week(start: date) -> Period:
    """The week starting on Monday `start`."""
    end = start + timedelta(days=6)
    return Period(
        Briefing.Kind.WEEKLY,
        start,
        end,
        (start - timedelta(days=7), start - timedelta(days=1)),
        (start - timedelta(days=7 * WEEKS_AVERAGED), start - timedelta(days=1)),
        WEEKS_AVERAGED,
    )


def month(start: date) -> Period:
    """The month starting on `start` (the first of a month)."""
    end = _month_start(start, -1) - timedelta(days=1)
    before = _month_start(start, 1)
    return Period(
        Briefing.Kind.MONTHLY,
        start,
        end,
        (before, start - timedelta(days=1)),
        (_month_start(start, MONTHS_AVERAGED), start - timedelta(days=1)),
        MONTHS_AVERAGED,
    )


def latest(kind: str, today: date) -> Period:
    """The last whole week or month before `today`."""
    if kind == Briefing.Kind.MONTHLY:
        return month(_month_start(today, 1))
    this_monday = today - timedelta(days=today.weekday())
    return week(this_monday - timedelta(days=7))


def of(kind: str, start: date) -> Period:
    return month(start) if kind == Briefing.Kind.MONTHLY else week(start)


def is_due(settings: BriefingSettings, kind: str, local_now: datetime) -> bool:
    """Whether the scheduled review of `kind` should go out now: switched on, its day and time
    have come, and this period's review hasn't gone out yet. A run missed on the day still
    sends it later: the weekly one until the week ends, the monthly one within its first
    MONTHLY_CATCH_UP days (a month's review read late in the month is old news)."""
    today = local_now.date()
    period = latest(kind, today)
    if kind == Briefing.Kind.MONTHLY:
        if not settings.monthly_enabled or settings.monthly_sent_for == period.start:
            return False
        if today.day == 1:
            return local_now.time() >= settings.send_at
        return today.day <= MONTHLY_CATCH_UP
    if not settings.weekly_enabled or settings.weekly_sent_for == period.start:
        return False
    if today.weekday() == settings.weekday:
        return local_now.time() >= settings.send_at
    return today.weekday() > settings.weekday


def due_moment(settings: BriefingSettings, kind: str, local_now: datetime) -> datetime | None:
    """When the current period's review was due (company time), None while it is off."""
    zone = local_now.tzinfo
    today = local_now.date()
    if kind == Briefing.Kind.MONTHLY:
        if not settings.monthly_enabled:
            return None
        return datetime.combine(_month_start(today), settings.send_at, zone)
    if not settings.weekly_enabled:
        return None
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday + timedelta(days=settings.weekday), settings.send_at, zone)


def next_send(settings: BriefingSettings, kind: str, local_now: datetime) -> datetime | None:
    """When the next review of `kind` goes out (company time), None while it is off."""
    zone = local_now.tzinfo
    if kind == Briefing.Kind.MONTHLY:
        if not settings.monthly_enabled:
            return None
        first = _month_start(local_now.date())
        moment = datetime.combine(first, settings.send_at, zone)
        if moment <= local_now:
            moment = datetime.combine(_month_start(first, -1), settings.send_at, zone)
        return moment
    if not settings.weekly_enabled:
        return None
    today = local_now.date()
    ahead = (settings.weekday - today.weekday()) % 7
    moment = datetime.combine(today + timedelta(days=ahead), settings.send_at, zone)
    if moment <= local_now:
        moment += timedelta(days=7)
    return moment
