"""When reminders go out. Pure functions of a policy and the clock."""

from collections.abc import Collection
from datetime import date, datetime, time, timedelta

from apps.reminders.models import ReminderPolicy


def first_reminder_at(
    due_at: datetime | None, policy: ReminderPolicy, now: datetime
) -> datetime | None:
    """The heads-up if there's still time for one, else the deadline itself."""
    if due_at is None:
        return None
    if policy.heads_up_minutes:
        heads_up = due_at - timedelta(minutes=policy.heads_up_minutes)
        if heads_up > now:
            return heads_up
    return due_at


def quiet_until(
    local_now: datetime, policy: ReminderPolicy, days_off: Collection[date] = ()
) -> datetime | None:
    """If `local_now` (in the company's timezone) is quiet, the moment it stops being; else None.

    Quiet means quiet hours, the policy's quiet days, or one of the person's `days_off`.
    """
    moment = local_now
    for _ in range(16 + 2 * len(days_off)):  # quiet hours, a week of quiet days, the days off
        if (end := _end_of_quiet_hours(moment, policy)) is not None:
            moment = end
        elif moment.weekday() in policy.quiet_days or moment.date() in days_off:
            moment = datetime.combine(moment.date() + timedelta(days=1), time.min, moment.tzinfo)
        else:
            break
    return None if moment == local_now else moment


def _end_of_quiet_hours(moment: datetime, policy: ReminderPolicy) -> datetime | None:
    start, stop = policy.quiet_from, policy.quiet_until
    if start is None or stop is None or start == stop:
        return None
    now = moment.time()
    today_stop = datetime.combine(moment.date(), stop, moment.tzinfo)
    if start < stop:  # within one day, e.g. 13:00-14:00
        return today_stop if start <= now < stop else None
    if now >= start:  # overnight, e.g. 22:00-08:00
        return today_stop + timedelta(days=1)
    return today_stop if now < stop else None
