from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.reminders.models import ReminderPolicy
from apps.reminders.schedule import first_reminder_at, quiet_until
from apps.tasks.models import Weekday

TASHKENT = ZoneInfo("Asia/Tashkent")


def policy(**fields) -> ReminderPolicy:
    return ReminderPolicy(**fields)  # unsaved: the schedule only reads fields


def at(day: int, hour: int, minute: int = 0) -> datetime:
    # October 2026: the 19th is a Monday.
    return datetime(2026, 10, day, hour, minute, tzinfo=TASHKENT)


def test_first_reminder_is_the_deadline():
    assert first_reminder_at(at(19, 18), policy(), now=at(19, 9)) == at(19, 18)


def test_heads_up_comes_first_when_there_is_time():
    rules = policy(heads_up_minutes=30)

    assert first_reminder_at(at(19, 18), rules, now=at(19, 9)) == at(19, 17, 30)
    assert first_reminder_at(at(19, 18), rules, now=at(19, 17, 45)) == at(19, 18)


def test_no_deadline_no_reminders():
    assert first_reminder_at(None, policy(), now=at(19, 9)) is None


@pytest.mark.parametrize(
    ("now", "resume"),
    [
        (at(19, 23), at(20, 8)),
        (at(20, 3), at(20, 8)),
        (at(19, 22), at(20, 8)),
        (at(19, 8), None),
        (at(19, 12), None),
    ],
)
def test_overnight_quiet_hours(now, resume):
    assert quiet_until(now, policy(quiet_from=time(22), quiet_until=time(8))) == resume


def test_quiet_hours_within_a_day():
    lunch = policy(quiet_from=time(13), quiet_until=time(14))

    assert quiet_until(at(19, 13, 30), lunch) == at(19, 14)
    assert quiet_until(at(19, 14), lunch) is None


def test_quiet_days_wait_for_the_next_working_morning():
    weekend = policy(
        quiet_from=time(22), quiet_until=time(8), quiet_days=[Weekday.SATURDAY, Weekday.SUNDAY]
    )

    # Saturday noon: skip Saturday and Sunday, then the night's quiet hours until Monday 08:00.
    assert quiet_until(at(24, 12), weekend) == at(26, 8)


@pytest.mark.parametrize("hours", [(None, None), (time(9), time(9))])
def test_quiet_hours_can_be_off(hours):
    start, stop = hours

    assert quiet_until(at(19, 23), policy(quiet_from=start, quiet_until=stop)) is None


def test_resume_time_is_in_the_future():
    resume = quiet_until(at(19, 23, 59), policy(quiet_from=time(22), quiet_until=time(8)))

    assert resume - at(19, 23, 59) == timedelta(hours=8, minutes=1)
