"""Date ranges for analytics endpoints, in each company's own calendar.

`parse_range(params, company, now)` reads the query parameters every analytics endpoint takes:

- `from`, `to`: company-local days, `YYYY-MM-DD`, both inclusive (`to` defaults to today);
- or `preset`: today, yesterday, week, last_week, month, last_month, last_30, quarter, year
  (the "this …" presets run to today; the default is `month`);
- `compare`: none (default), prev or year.

`prev` compares a calendar preset with the same days of the previous week, month, quarter or
year (1-20 October against 1-20 September); a custom range, `last_30`, today and yesterday with
the same number of days just before. `year` compares with the same days a year earlier.

Packages import `Range` and `parse_range` from `apps.reports.periods` (PLAN-OWNER §3.1), which
re-exports them; owner endpoints use `RangeMixin`.
"""

import calendar
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

PRESETS = (
    "today",
    "yesterday",
    "week",
    "last_week",
    "month",
    "last_month",
    "last_30",
    "quarter",
    "year",
)
COMPARES = ("none", "prev", "year")
DEFAULT_PRESET = "month"
# Longer spans would make every daily series too big to be useful.
MAX_DAYS = 366 * 3


class RangeError(ValueError):
    """The parameters don't describe a usable range. The message is safe to show."""


@dataclass(frozen=True)
class Range:
    start: date
    end: date
    compare_start: date | None = None
    compare_end: date | None = None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def has_compare(self) -> bool:
        return self.compare_start is not None

    def as_dict(self) -> dict:
        """The `range`/`compare` keys of the analytics response shape (§4)."""
        compare = None
        if self.compare_start is not None:
            compare = {"from": self.compare_start.isoformat(), "to": self.compare_end.isoformat()}
        return {
            "range": {"from": self.start.isoformat(), "to": self.end.isoformat()},
            "compare": compare,
        }


def company_today(company, now: datetime | None = None) -> date:
    now = now or timezone.now()
    return timezone.localtime(now, zoneinfo.ZoneInfo(company.timezone)).date()


def parse_range(params, company, now: datetime) -> Range:
    today = company_today(company, now)
    start_text, end_text = params.get("from"), params.get("to")
    preset = params.get("preset") or (None if start_text or end_text else DEFAULT_PRESET)
    if preset is not None and (start_text or end_text):
        raise RangeError(_("Give either a preset or from/to, not both."))
    if preset is None:
        if not start_text:
            raise RangeError(_("Give the first day (from)."))
        start = _day(start_text, "from")
        end = _day(end_text, "to") if end_text else today
        if end < start:
            raise RangeError(_("The last day can't be before the first."))
        shift = None
    else:
        if preset not in PRESETS:
            raise RangeError(_("Unknown preset: %(preset)s") % {"preset": preset})
        start, end, shift = _preset(preset, today)
    if (end - start).days + 1 > MAX_DAYS:
        raise RangeError(_("Pick at most three years."))

    compare = params.get("compare") or "none"
    if compare not in COMPARES:
        raise RangeError(_("Unknown comparison: %(compare)s") % {"compare": compare})
    if compare == "none":
        return Range(start, end)
    if compare == "year":
        return Range(start, end, _shift_months(start, -12), _shift_months(end, -12))
    if isinstance(shift, Months):
        return Range(start, end, _shift_months(start, -shift), _shift_months(end, -shift))
    span = timedelta(days=shift) if shift else end - start + timedelta(days=1)
    return Range(start, end, start - span, end - span)


class Months(int):
    """A `prev` comparison that moves by calendar months rather than by days."""


def _preset(preset: str, today: date) -> tuple[date, date, int | Months]:
    """(first day, last day, how far `prev` moves back: days, or `Months`)."""
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    match preset:
        case "today":
            return today, today, 1
        case "yesterday":
            yesterday = today - timedelta(days=1)
            return yesterday, yesterday, 1
        case "week":
            return week, today, 7
        case "last_week":
            return week - timedelta(days=7), week - timedelta(days=1), 7
        case "month":
            return month, today, Months(1)
        case "last_month":
            last = month - timedelta(days=1)
            return last.replace(day=1), last, Months(1)
        case "last_30":
            return today - timedelta(days=29), today, 30
        case "quarter":
            first_month = 3 * ((today.month - 1) // 3) + 1
            return today.replace(month=first_month, day=1), today, Months(3)
        case "year":
            return today.replace(month=1, day=1), today, Months(12)
    raise RangeError(preset)


def _shift_months(day: date, months: int) -> date:
    """The same day `months` months away, clipped to the end of a shorter month."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _day(text: str, name: str) -> date:
    try:
        return date.fromisoformat(text)
    except TypeError, ValueError:
        raise RangeError(_("%(name)s must be a day like 2026-10-20.") % {"name": name}) from None
