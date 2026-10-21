from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.groups import reports
from apps.groups.models import GroupEvent, GroupReport
from apps.groups.tasks import post_daily_reports
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members.models import Membership
from apps.members.tests.factories import PositionFactory
from apps.projects.tests.factories import card, project, team
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def today() -> date:
    return timezone.localtime(timezone.now(), TASHKENT).date()


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TASHKENT)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


@pytest.fixture
def ali(company, member):
    return member.registered(company, first_name="Ali", last_name="Valiyev")


@pytest.fixture
def vali(company, member):
    return member.registered(company, first_name="Vali", last_name="Aliyev")


def work(assignee, manager, due_at, **fields) -> Task:
    """Shared work: assigned by the manager, so groups may hear about it."""
    return TaskFactory(assignee=assignee, created_by=manager, due_at=due_at, **fields)


def test_the_morning_plan_lists_each_persons_work_for_today(
    company, other_company, member, manager, ali, vali, today
):
    work(ali, manager, at(today, 18))
    work(ali, manager, at(today, 10), kind=Task.Kind.DAILY)
    work(vali, manager, at(today, 9, 30))
    # None of these belong in today's plan:
    work(vali, manager, at(today, 11), status=Task.Status.CANCELLED)
    work(vali, manager, at(today + timedelta(days=1), 9))
    TaskFactory(assignee=vali, due_at=at(today, 12))  # personal
    blocked = member.registered(company, status=Membership.Status.BLOCKED)
    work(blocked, manager, at(today, 12))
    outsider = member.registered(other_company)
    TaskFactory(assignee=outsider, created_by=member.registered(other_company), due_at=at(today, 9))

    rows = reports.morning_plan(company, today)

    assert [(row.name, row.count, row.first_due) for row in rows] == [
        ("Vali Aliyev", 1, at(today, 9, 30)),
        ("Ali Valiyev", 2, at(today, 10)),
    ]


def test_the_day_is_counted_as_on_time_late_and_not_done(company, manager, ali, vali, today):
    work(ali, manager, at(today, 10), status=Task.Status.DONE, completed_at=at(today, 9, 50))
    work(ali, manager, at(today, 11), status=Task.Status.REVIEW, completed_at=at(today, 10))
    work(ali, manager, at(today, 12), status=Task.Status.DONE, completed_at=at(today, 13))
    work(vali, manager, at(today, 14), title="Cash report")
    work(vali, manager, at(today, 22), title="Lock up")  # due after the report

    stats = reports.day_stats(company, today, until=at(today, 20))

    assert stats.on_time == 2
    assert stats.late == 1
    assert stats.not_done == [("Vali Aliyev", "Cash report")]
    assert stats.total == 4


def test_unfinished_cards_are_listed_with_their_key(company, member, today):
    people = team(company, member)
    reno = project(company, people["owner"], key="RENO")
    tiles = card(reno, people["owner"], title="Order tiles", assignee=people["aziz"])
    Task.objects.filter(pk=tiles.pk).update(due_at=at(today, 10))

    stats = reports.day_stats(company, today)

    assert stats.not_done == [(str(people["aziz"]), "RENO-1 · Order tiles")]


def test_the_morning_plan_goes_out_once_after_its_time(
    company, other_company, manager, ali, today, sent_messages
):
    work(ali, manager, at(today, 10), title="Open the shop")
    wants = TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])
    evening_only = TelegramGroupFactory(company=company, events=[GroupEvent.EVENING])
    elsewhere = TelegramGroupFactory(company=other_company, events=[GroupEvent.MORNING])

    assert post_daily_reports(at(today, 8, 55)) == 0  # not yet
    assert post_daily_reports(at(today, 9, 2)) == 1
    assert post_daily_reports(at(today, 9, 7)) == 0  # already sent today

    [post] = sent_messages
    assert post["chat_id"] == wants.chat_id
    assert "Ali Valiyev" in post["text"]
    assert "10:00" in post["text"]
    assert GroupReport.objects.filter(group=wants, kind=GroupEvent.MORNING, day=today).exists()
    assert not GroupReport.objects.filter(group__in=[evening_only, elsewhere]).exists()


def test_a_report_missed_by_hours_is_skipped(company, manager, ali, today, sent_messages):
    work(ali, manager, at(today, 10))
    TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])

    assert post_daily_reports(at(today, 11, 30)) == 0
    assert sent_messages == []


def test_a_day_with_nothing_planned_gets_no_morning_post(company, today, sent_messages):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])

    assert post_daily_reports(at(today, 9)) == 0

    assert sent_messages == []
    # Not marked as sent, so work added before the window closes still gets a plan.
    assert not GroupReport.objects.filter(group=group).exists()


def test_the_evening_summary_counts_the_day(company, manager, ali, vali, today, sent_messages):
    work(ali, manager, at(today, 10), status=Task.Status.DONE, completed_at=at(today, 9))
    work(vali, manager, at(today, 14), title="Cash report")
    group = TelegramGroupFactory(company=company, events=[GroupEvent.EVENING])

    assert post_daily_reports(at(today, 20, 1)) == 1

    [post] = sent_messages
    assert post["chat_id"] == group.chat_id
    assert "Done on time: 1" in post["text"]
    assert "Not done: 1" in post["text"]
    assert "Vali Aliyev: Cash report" in post["text"]


def test_report_times_follow_the_company(company, manager, ali, today, sent_messages):
    company.morning_report_at = time(7, 30)
    company.save()
    work(ali, manager, at(today, 10))
    TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])

    assert post_daily_reports(at(today, 7, 31)) == 1


def test_each_group_gets_the_report_for_its_positions(
    company, member, manager, today, sent_messages
):
    cashier = PositionFactory(company=company)
    work(member.registered(company, first_name="Kassir", position=cashier), manager, at(today, 10))
    work(member.registered(company, first_name="Botir"), manager, at(today, 11))
    cashiers = TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])
    cashiers.positions.add(cashier)
    everyone = TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])

    assert post_daily_reports(at(today, 9)) == 2

    by_group = {message["chat_id"]: message["text"] for message in sent_messages}
    assert "Kassir" in by_group[cashiers.chat_id]
    assert "Botir" not in by_group[cashiers.chat_id]
    assert "Kassir" in by_group[everyone.chat_id]
    assert "Botir" in by_group[everyone.chat_id]


def test_a_group_whose_people_have_nothing_today_gets_no_plan(
    company, member, manager, today, sent_messages
):
    work(member.registered(company), manager, at(today, 10))
    idle = TelegramGroupFactory(company=company, events=[GroupEvent.MORNING])
    idle.positions.add(PositionFactory(company=company))

    assert post_daily_reports(at(today, 9)) == 0
    assert sent_messages == []
