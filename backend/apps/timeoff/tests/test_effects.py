"""What time off changes elsewhere: daily tasks, reminders and the app's home screen."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.reminders.engine import send_due_reminders
from apps.reminders.models import ReminderPolicy
from apps.reminders.policies import default_policy
from apps.reminders.schedule import quiet_until
from apps.tasks import stats
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory, TaskTemplateFactory
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def today() -> date:
    return timezone.localdate(timezone=TASHKENT)


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def approved(member, first: date, last: date | None = None) -> TimeOff:
    return TimeOff.objects.create(
        company=member.company,
        membership=member,
        first_day=first,
        last_day=last or first,
        status=TimeOff.Status.APPROVED,
    )


def test_no_daily_tasks_on_a_company_holiday(company, worker, manager, today):
    template = TaskTemplateFactory(
        company=company, created_by=manager, due_time="23:59", assignees=[worker]
    )
    template.created_at = timezone.now() - timedelta(days=1)
    template.save()
    Holiday.objects.create(company=company, date=today, name="Independence Day")

    generate_daily_tasks(company, today)
    assert not Task.objects.exists()

    generate_daily_tasks(company, today + timedelta(days=1))
    assert Task.objects.filter(assignee=worker).count() == 1


def test_no_daily_tasks_for_someone_on_time_off(company, member, worker, manager, today):
    colleague = member.registered(company)
    template = TaskTemplateFactory(
        company=company, created_by=manager, due_time="23:59", assignees=[worker, colleague]
    )
    template.created_at = timezone.now() - timedelta(days=1)
    template.save()
    approved(worker, today)
    TimeOff.objects.create(  # only approved time off counts
        company=company, membership=colleague, first_day=today, last_day=today
    )

    generate_daily_tasks(company, today)

    assert list(Task.objects.values_list("assignee", flat=True)) == [colleague.pk]


def test_days_off_are_quiet():
    policy = ReminderPolicy(quiet_from=time(22), quiet_until=time(8), quiet_days=[6])
    friday_noon = datetime(2026, 10, 23, 12, tzinfo=TASHKENT)
    days_off = {date(2026, 10, 23), date(2026, 10, 24)}

    # Friday and Saturday off, Sunday quiet: it starts again on Monday after the quiet hours.
    assert quiet_until(friday_noon, policy, days_off) == datetime(2026, 10, 26, 8, tzinfo=TASHKENT)
    assert quiet_until(friday_noon, policy) is None


def test_reminders_wait_until_the_time_off_is_over(company, worker, manager, today, sent_messages):
    policy = default_policy(company.pk)
    policy.quiet_from = policy.quiet_until = None  # so the test runs at any hour
    policy.save()
    now = timezone.now()
    due = now - timedelta(minutes=30)
    task = TaskFactory(assignee=worker, created_by=manager, due_at=due, next_reminder_at=due)
    approved(worker, today, today + timedelta(days=1))

    send_due_reminders(now)

    assert sent_messages == []
    task.refresh_from_db()
    back = datetime.combine(today + timedelta(days=2), time.min, tzinfo=TASHKENT)
    assert task.next_reminder_at == back
    assert task.reminders_sent == 0


def test_holidays_silence_reminders_for_everyone(company, worker, manager, today, sent_messages):
    policy = default_policy(company.pk)
    policy.quiet_from = policy.quiet_until = None
    policy.save()
    due = timezone.now() - timedelta(minutes=30)
    TaskFactory(assignee=worker, created_by=manager, due_at=due, next_reminder_at=due)
    Holiday.objects.create(company=company, date=today, name="New Year")

    send_due_reminders(timezone.now())

    assert sent_messages == []


def test_the_home_screen_knows_about_a_day_off(company, worker, today):
    assert stats.summary(worker, timezone.now())["off_today"] is None

    approved(worker, today - timedelta(days=1), today + timedelta(days=2))
    assert stats.summary(worker, timezone.now())["off_today"] == {
        "kind": "time_off",
        "name": "",
        "until": today + timedelta(days=2),
    }

    Holiday.objects.create(company=company, date=today, name="Navruz")
    assert stats.summary(worker, timezone.now())["off_today"] == {
        "kind": "holiday",
        "name": "Navruz",
        "until": today,
    }
