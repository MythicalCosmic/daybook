"""Which days a streak must not skip (docs/PLAN-LEARNING.md §7.4).

A streak grows when nothing but days off lies between the last day it counted and today. A
person's workdays follow the calendars of PLAN-OWNER §2.7: someone on a roster works the days
of their planned shifts (a pharmacist on a 2/2 schedule rests two days of four), everyone else
the company's workdays; company holidays and the person's approved time off are never
workdays. Learning on a day off still counts.

A plain module: services and the nightly jobs both use it.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.members.models import Membership

# A gap longer than this always breaks the streak (and keeps the check cheap).
MAX_GAP_DAYS = 400


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _planned_days(member: Membership, first: date, last: date) -> set[date] | None:
    """The days of `member`'s planned shifts from `first` to `last`, or None when they aren't on
    a roster then (no live shift of theirs within a week of the period)."""
    company = member.company
    if not company.has_feature("attendance"):
        return None
    from apps.attendance.models import WorkShift

    around = WorkShift.objects.live().filter(
        company=company,
        membership=member,
        date__range=(first - timedelta(days=6), last + timedelta(days=6)),
    )
    rows = list(around.values_list("date", "status"))
    if not rows:
        return None
    return {
        day for day, status in rows if status == WorkShift.Status.PLANNED and first <= day <= last
    }


def workdays(member: Membership, first: date, last: date) -> set[date]:
    """`member`'s workdays from `first` to `last` (both included)."""
    if first > last:
        return set()
    from apps.timeoff.queries import days_off

    days = _days(first, last)
    planned = _planned_days(member, first, last)
    if planned is not None:
        working = {day for day in days if day in planned}
    else:
        weekdays = set(member.company.workdays or range(7))
        working = {day for day in days if day.weekday() in weekdays}
    if not working:
        return set()
    return working - days_off(member, first, last)


def continues(member: Membership, last_day: date, day: date) -> bool:
    """Whether a streak last counted on `last_day` goes on when `day` counts: no workday of
    the person lies in between."""
    if day <= last_day:
        return False
    if (day - last_day).days > MAX_GAP_DAYS:
        return False
    return not workdays(member, last_day + timedelta(days=1), day - timedelta(days=1))
