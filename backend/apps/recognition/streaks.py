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


def _planned_days(company, first_days: dict[int, date], last: date) -> dict[int, set[date] | None]:
    """Member id → the days of their planned shifts from their first day to `last`, or None when
    they aren't on a roster then (no live shift of theirs within a week of the period)."""
    if not company.has_feature("attendance"):
        return dict.fromkeys(first_days)
    from apps.attendance.models import WorkShift

    week = timedelta(days=6)
    around = WorkShift.objects.live().filter(
        company=company,
        membership_id__in=list(first_days),
        date__range=(min(first_days.values()) - week, last + week),
    )
    rostered: set[int] = set()
    planned: dict[int, set[date]] = {member_id: set() for member_id in first_days}
    for member_id, day, status in around.values_list("membership_id", "date", "status"):
        first = first_days[member_id]
        if day < first - week:
            continue  # someone else's longer period reaches back this far, not theirs
        rostered.add(member_id)
        if status == WorkShift.Status.PLANNED and first <= day <= last:
            planned[member_id].add(day)
    return {
        member_id: planned[member_id] if member_id in rostered else None for member_id in first_days
    }


def workdays_many(company, first_days: dict[int, date], last: date) -> dict[int, set[date]]:
    """Member id → their workdays from their own first day to `last` (both included), for people
    of one company: three queries however many they are (a leaderboard asks for everyone's)."""
    from apps.timeoff.queries import days_off_many

    result: dict[int, set[date]] = {member_id: set() for member_id in first_days}
    spans = {member_id: first for member_id, first in first_days.items() if first <= last}
    if not spans:
        return result
    planned = _planned_days(company, spans, last)
    weekdays = set(company.workdays or range(7))
    working: dict[int, set[date]] = {}
    for member_id, first in spans.items():
        mine = planned[member_id]
        if mine is None:
            mine = {day for day in _days(first, last) if day.weekday() in weekdays}
        if mine:
            working[member_id] = mine
    if not working:
        return result
    off = days_off_many(company.pk, {member_id: spans[member_id] for member_id in working}, last)
    for member_id, days in working.items():
        result[member_id] = days - off[member_id]
    return result


def workdays(member: Membership, first: date, last: date) -> set[date]:
    """`member`'s workdays from `first` to `last` (both included)."""
    if first > last:
        return set()
    return workdays_many(member.company, {member.pk: first}, last)[member.pk]


def continues(member: Membership, last_day: date, day: date) -> bool:
    """Whether a streak last counted on `last_day` goes on when `day` counts: no workday of
    the person lies in between."""
    if day <= last_day:
        return False
    if (day - last_day).days > MAX_GAP_DAYS:
        return False
    return not workdays(member, last_day + timedelta(days=1), day - timedelta(days=1))
