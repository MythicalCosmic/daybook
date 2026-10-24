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


def quiet_for_task(
    local_now: datetime,
    policy: ReminderPolicy,
    days_off: Collection[date] = (),
    *,
    due: datetime | None = None,
    shift: tuple[bool, datetime | None] | None = None,
) -> datetime | None:
    """When reminders about one task may go again, if `local_now` is quiet for it; else None.

    - With the person's shifts known (`shift`: whether they're at work now, and when their next
      shift starts), quiet is simply being off shift (research R1 N1): at work, nothing holds
      the reminder; off shift, it waits for the next shift.
    - Otherwise the policy's quiet hours, quiet days and the person's days off, except that a
      task due inside the quiet hours is night work: those hours don't hold it (R2 P1). A
      night pharmacist's 23:30 till check is reminded at 23:30, not at 08:00.
    """
    if shift is not None:
        at_work, next_start = shift
        if at_work:
            return None
        if next_start is not None:
            return next_start.astimezone(local_now.tzinfo)
    night_work = due is not None and in_quiet_hours(due.astimezone(local_now.tzinfo), policy)
    return quiet_until(local_now, policy, days_off, hours=not night_work)


def in_quiet_hours(moment: datetime, policy: ReminderPolicy) -> bool:
    """Whether `moment`'s time of day is inside the policy's quiet hours."""
    return _end_of_quiet_hours(moment, policy) is not None


def quiet_until(
    local_now: datetime,
    policy: ReminderPolicy,
    days_off: Collection[date] = (),
    *,
    hours: bool = True,
) -> datetime | None:
    """If `local_now` (in the company's timezone) is quiet, the moment it stops being; else None.

    Quiet means quiet hours (unless `hours` is False), the policy's quiet days, or one of the
    person's `days_off`.
    """
    moment = local_now
    for _ in range(16 + 2 * len(days_off)):  # quiet hours, a week of quiet days, the days off
        if hours and (end := _end_of_quiet_hours(moment, policy)) is not None:
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
