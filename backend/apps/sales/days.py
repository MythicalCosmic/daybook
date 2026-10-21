"""Which business day a sale or a shift belongs to (docs/PLAN-OWNER.md §2.7).

`SalesSettings.business_day_ends_at` (04:00 by default) decides it: a sale at 01:30 belongs to
the day before, so a bar's night shift and its sales stay on the evening they started. Only sales
use this calendar; attendance, pay and leave follow their own (§2.7).
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone


def local(company, moment: datetime | None = None) -> datetime:
    """`moment` (default: now) in the company's timezone."""
    return timezone.localtime(moment or timezone.now(), ZoneInfo(company.timezone))


def business_day(company, moment: datetime | None = None, *, ends_at: time | None = None) -> date:
    """The business day `moment` belongs to in `company`'s calendar."""
    if ends_at is None:
        from apps.sales.conf import get_settings

        ends_at = get_settings(company).business_day_ends_at
    at = local(company, moment)
    day = at.date()
    if at.time() < ends_at:
        day -= timedelta(days=1)
    return day


def day_bounds(company, day: date, *, ends_at: time) -> tuple[datetime, datetime]:
    """The first and the next business day's first moment of `day`, as aware datetimes."""
    zone = ZoneInfo(company.timezone)
    start = datetime.combine(day, ends_at, tzinfo=zone)
    return start, start + timedelta(days=1)
