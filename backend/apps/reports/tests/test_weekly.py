from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.reports.models import WeeklyReport
from apps.reports.tasks import post_weekly_reports
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")
MONDAY = date(2026, 10, 19)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TASHKENT)


@pytest.fixture
def team(company, member):
    """An owner and a manager who may see reports, a worker who may not, and last week's work."""
    owner = member.registered(company, "Owner", user__language="ru")
    manager = member.registered(company, "Manager", first_name="Mona")
    worker = member.registered(company, first_name="Ali", last_name="Valiyev")
    wednesday = MONDAY - timedelta(days=5)
    TaskFactory(
        assignee=worker,
        created_by=manager,
        due_at=at(wednesday, 10),
        status=Task.Status.DONE,
        completed_at=at(wednesday, 11),
    )
    TaskFactory(assignee=worker, created_by=manager, due_at=at(wednesday, 12))
    return owner, manager, worker


def test_people_who_may_see_reports_get_last_week_on_monday_morning(team, sent_messages):
    owner, manager, _worker = team
    assert MONDAY.weekday() == 0

    assert post_weekly_reports(at(MONDAY, 9, 5)) == 2
    assert post_weekly_reports(at(MONDAY, 9, 20)) == 0  # once a week

    readers = {message["chat_id"]: message["text"] for message in sent_messages}
    assert set(readers) == {owner.user.telegram_id, manager.user.telegram_id}
    english = readers[manager.user.telegram_id]
    assert "12.10–18.10" in english
    assert "On time: <b>0%</b>, 0 of 2 tasks." in english
    assert "Ali Valiyev: 0%, 1 late, 1 not done" in english
    assert "Прошлая неделя" in readers[owner.user.telegram_id]  # each in their own language
    assert WeeklyReport.objects.filter(week_start=MONDAY - timedelta(days=7)).count() == 2


@pytest.mark.parametrize(
    "moment",
    [at(MONDAY, 8, 55), at(MONDAY, 11, 5), at(MONDAY + timedelta(days=1), 9, 5)],
    ids=["too early", "too late", "tuesday"],
)
def test_the_report_waits_for_monday_morning(team, sent_messages, moment):
    assert post_weekly_reports(moment) == 0
    assert sent_messages == []


def test_a_quiet_week_sends_nothing(company, member, sent_messages):
    member.registered(company, "Owner")

    assert post_weekly_reports(at(MONDAY, 9, 5)) == 0
    assert sent_messages == []
    assert not WeeklyReport.objects.exists()
