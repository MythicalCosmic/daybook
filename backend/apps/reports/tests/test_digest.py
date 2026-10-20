from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.reports.digest import DIGEST_LIMIT, post_morning_digests
from apps.reports.models import MorningDigest
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")
WEDNESDAY = date(2026, 10, 21)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TASHKENT)


MORNING = at(WEDNESDAY, 9, 2)


@pytest.fixture
def worker(company, member):
    return member.registered(company, first_name="Ali")


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def to(sent_messages, member) -> list[dict]:
    return [m for m in sent_messages if m["chat_id"] == member.user.telegram_id]


def buttons(message) -> list[tuple[TaskAction, int]]:
    rows = message["reply_markup"]["inline_keyboard"]
    return [
        (data.action, data.task_id)
        for data in (TaskCallback.unpack(row[0]["callback_data"]) for row in rows)
    ]


def test_everyone_working_today_gets_their_open_tasks(worker, manager, sent_messages):
    overdue = TaskFactory(
        assignee=worker, created_by=manager, due_at=at(WEDNESDAY, 18) - timedelta(days=1)
    )
    later = TaskFactory(assignee=worker, created_by=manager, due_at=at(WEDNESDAY, 17))
    first = TaskFactory(assignee=worker, due_at=at(WEDNESDAY, 10))  # personal tasks count too
    TaskFactory(
        assignee=worker,
        created_by=manager,
        due_at=at(WEDNESDAY, 11),
        status=Task.Status.DONE,
        completed_at=at(WEDNESDAY, 8),
    )
    TaskFactory(assignee=worker, created_by=manager, due_at=at(WEDNESDAY, 10) + timedelta(days=1))

    assert post_morning_digests(MORNING) == 1
    assert post_morning_digests(MORNING + timedelta(minutes=5)) == 0  # once a day

    [message] = to(sent_messages, worker)
    assert "Good morning, Ali! Tasks for today: 2." in message["text"]
    assert "Still open from earlier days: 1." in message["text"]
    assert buttons(message) == [
        (TaskAction.OPEN, overdue.pk),
        (TaskAction.OPEN, first.pk),
        (TaskAction.OPEN, later.pk),
    ]


def test_nothing_open_means_no_message(worker, manager, sent_messages):
    assert post_morning_digests(MORNING) == 0
    assert sent_messages == []
    assert MorningDigest.objects.filter(membership=worker, day=WEDNESDAY).exists()


def test_a_long_day_links_to_the_full_list(worker, sent_messages):
    for hour in range(10, 11 + DIGEST_LIMIT):
        TaskFactory(assignee=worker, due_at=at(WEDNESDAY, hour % 24))

    post_morning_digests(MORNING)

    [message] = to(sent_messages, worker)
    actions = [action for action, _ in buttons(message)]
    assert actions == [TaskAction.OPEN] * DIGEST_LIMIT + [TaskAction.LIST]


def test_people_off_today_are_left_alone(company, worker, member, sent_messages):
    colleague = member.registered(company)
    for person in (worker, colleague):
        TaskFactory(assignee=person, due_at=at(WEDNESDAY, 12))
    TimeOff.objects.create(
        company=company,
        membership=worker,
        first_day=WEDNESDAY,
        last_day=WEDNESDAY,
        status=TimeOff.Status.APPROVED,
    )

    assert post_morning_digests(MORNING) == 1
    assert not to(sent_messages, worker)
    assert to(sent_messages, colleague)


def test_nobody_gets_one_on_a_holiday(company, worker, sent_messages):
    TaskFactory(assignee=worker, due_at=at(WEDNESDAY, 12))
    Holiday.objects.create(company=company, date=WEDNESDAY, name="Teachers' Day")

    assert post_morning_digests(MORNING) == 0


@pytest.mark.parametrize(
    "moment", [at(WEDNESDAY, 8, 55), at(WEDNESDAY, 11, 5)], ids=["early", "late"]
)
def test_only_in_the_morning(worker, sent_messages, moment):
    TaskFactory(assignee=worker, due_at=at(WEDNESDAY, 12))

    assert post_morning_digests(moment) == 0


def test_companies_can_turn_it_off(company, worker, sent_messages):
    company.morning_digest = False
    company.save()
    TaskFactory(assignee=worker, due_at=at(WEDNESDAY, 12))

    assert post_morning_digests(MORNING) == 0


def test_people_who_blocked_the_bot_are_skipped(worker, sent_messages):
    worker.user.employee_bot_blocked_at = timezone.now()
    worker.user.save()
    TaskFactory(assignee=worker, due_at=at(WEDNESDAY, 12))

    assert post_morning_digests(MORNING) == 0


def test_the_digest_speaks_each_persons_language(company, member, sent_messages):
    person = member.registered(company, first_name="Олег", user__language="ru")
    TaskFactory(assignee=person, due_at=at(WEDNESDAY, 12))

    post_morning_digests(MORNING)

    [message] = to(sent_messages, person)
    assert message["text"].startswith("🌅 Доброе утро, Олег! Задач на сегодня: 1.")
