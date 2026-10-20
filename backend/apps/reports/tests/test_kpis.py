from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.members.models import Membership
from apps.reminders.models import ReminderLog
from apps.reports import kpis
from apps.reports.periods import Period, bounds, in_window
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

TASHKENT = ZoneInfo("Asia/Tashkent")
WEDNESDAY = date(2026, 10, 21)


@pytest.mark.parametrize(
    ("period", "today", "expected"),
    [
        (Period.WEEK, WEDNESDAY, (date(2026, 10, 19), date(2026, 10, 26))),
        (Period.LAST_WEEK, WEDNESDAY, (date(2026, 10, 12), date(2026, 10, 19))),
        (Period.MONTH, WEDNESDAY, (date(2026, 10, 1), date(2026, 11, 1))),
        (Period.LAST_MONTH, WEDNESDAY, (date(2026, 9, 1), date(2026, 10, 1))),
        (Period.MONTH, date(2026, 12, 31), (date(2026, 12, 1), date(2027, 1, 1))),
        (Period.LAST_MONTH, date(2027, 1, 1), (date(2026, 12, 1), date(2027, 1, 1))),
    ],
)
def test_period_bounds(period, today, expected):
    assert bounds(period, today) == expected


def test_a_report_goes_out_in_the_two_hours_after_its_time():
    at = time(9, 0)
    day = datetime.combine(WEDNESDAY, time(0), tzinfo=TASHKENT)

    assert not in_window(day.replace(hour=8, minute=59), at)
    assert in_window(day.replace(hour=9), at)
    assert in_window(day.replace(hour=10, minute=59), at)
    assert not in_window(day.replace(hour=11), at)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TASHKENT)


@pytest.mark.django_db
def test_each_persons_shared_work_is_scored(company, member):
    manager = member.registered(company, "Manager", first_name="Mona")
    ali = member.registered(company, first_name="Ali")
    vali = member.registered(company, first_name="Vali")
    idle = member.registered(company, first_name="Bek")
    member(company, status=Membership.Status.PENDING, first_name="Pending")
    now = at(WEDNESDAY, 12)
    monday = date(2026, 10, 19)

    def work(person, due, **fields):
        return TaskFactory(assignee=person, created_by=manager, due_at=due, **fields)

    done = Task.Status.DONE
    work(ali, at(monday, 10), status=done, completed_at=at(monday, 9))
    work(ali, at(monday, 11), status=Task.Status.REVIEW, completed_at=at(monday, 11, 30))
    missed = work(ali, at(WEDNESDAY, 9))
    work(vali, at(WEDNESDAY, 10), status=done, completed_at=at(WEDNESDAY, 10), kind=Task.Kind.DAILY)
    # Not part of this week's scores:
    work(ali, at(WEDNESDAY, 18))  # not due yet
    work(ali, at(monday, 12), status=Task.Status.CANCELLED)
    TaskFactory(assignee=ali, due_at=at(monday, 13))  # personal
    work(ali, at(monday - timedelta(days=3), 10))  # last week, still open: late now, not missed
    for kind, delivered in [(ReminderLog.Kind.REMINDER, True)] * 2 + [
        (ReminderLog.Kind.REMINDER, False),
        (ReminderLog.Kind.ESCALATION, True),
    ]:
        ReminderLog.objects.create(task=missed, kind=kind, recipient=ali, delivered=delivered)
    ReminderLog.objects.update(sent_at=at(WEDNESDAY, 9, 30))  # sent_at is set on create

    report = kpis.team(company, monday, monday + timedelta(days=7), now, branch_ids=None)

    assert [str(person) for person, _ in report.rows] == ["Vali", "Ali", "Bek", "Mona"]
    scores = {str(person): score for person, score in report.rows}
    assert scores["Ali"] == kpis.Score(
        on_time=1, late=1, missed=1, late_now=2, reminders=2, avg_delay=timedelta(minutes=30)
    )
    assert (scores["Ali"].total, scores["Ali"].on_time_percent) == (3, 33)
    assert scores["Ali"].avg_delay_minutes == 30
    assert scores["Vali"].on_time_percent == 100
    assert scores["Bek"] == kpis.Score()
    assert scores["Bek"].on_time_percent is None
    totals = report.totals
    assert (totals.total, totals.on_time, totals.on_time_percent) == (4, 2, 50)
    assert (totals.late_now, totals.reminders, totals.avg_delay_minutes) == (2, 2, 30)
    assert idle in [person for person, _ in report.rows]
