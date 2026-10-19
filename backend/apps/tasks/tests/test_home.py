"""The mini app's home screen: summary numbers, the activity feed, repeating personal tasks."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory, MembershipFactory
from apps.tasks import queries, services, stats
from apps.tasks.generation import generate_daily_tasks
from apps.tasks.models import Activity, Repeat, Task, TaskTemplate
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")


def client_for(membership: Membership) -> APIClient:
    api = APIClient()
    token = RefreshToken.for_user(membership.user).access_token
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api


def at(day_offset: int, hour: int, now: datetime) -> datetime:
    local_day = timezone.localtime(now, TASHKENT).date() + timedelta(days=day_offset)
    return datetime.combine(local_day, time(hour), tzinfo=TASHKENT)


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def finished(worker, due_at, completed_at, **kwargs):
    return TaskFactory(
        assignee=worker,
        due_at=due_at,
        status=Task.Status.DONE,
        completed_at=completed_at,
        **kwargs,
    )


# Summary


def test_summary_counts_todays_work(company, worker):
    now = timezone.now()
    today_noon = at(0, 12, now)
    finished(worker, today_noon, today_noon)
    TaskFactory(assignee=worker, due_at=today_noon, status=Task.Status.REVIEW)
    TaskFactory(assignee=worker, due_at=at(0, 23, now))
    TaskFactory(assignee=worker, due_at=at(0, 23, now), status=Task.Status.CANCELLED)
    TaskFactory(assignee=worker, due_at=now - timedelta(days=2))  # late, from another day

    numbers = stats.summary(worker, now)

    assert numbers["today_total"] == 3
    assert numbers["today_done"] == 2
    assert numbers["late"] >= 1


def test_streak_counts_days_finished_in_time(worker):
    now = timezone.now()
    for days_ago in (1, 2, 3):
        due = at(-days_ago, 10, now)
        finished(worker, due, due + timedelta(hours=1))
    # Five days ago: done, but only the day after. That breaks the streak.
    late_due = at(-5, 10, now)
    finished(worker, late_due, late_due + timedelta(days=1))

    assert stats.streak(worker, now) == 3


def test_streak_skips_empty_days_and_waits_for_today(worker):
    now = timezone.now()
    finished(worker, at(-1, 9, now), at(-1, 10, now))
    finished(worker, at(-4, 9, now), at(-4, 10, now))  # nothing due on days 2-3
    TaskFactory(assignee=worker, due_at=at(0, 23, now))  # today, still open

    assert stats.streak(worker, now) == 2


def test_streak_breaks_on_an_unfinished_day(worker):
    now = timezone.now()
    finished(worker, at(-1, 9, now), at(-1, 10, now))
    TaskFactory(assignee=worker, due_at=at(-2, 9, now))  # never done
    finished(worker, at(-3, 9, now), at(-3, 10, now))

    assert stats.streak(worker, now) == 1


def test_summary_endpoint(company, worker):
    response = client_for(worker).get(f"/api/v1/companies/{company.pk}/summary/")

    assert response.status_code == 200
    assert set(response.data) == {
        "today_total",
        "today_done",
        "late",
        "streak_days",
        "unread_activity",
        "awaiting_review",
    }


# Activity feed


def test_assigning_puts_it_in_the_assignees_feed(manager, worker):
    task = services.create_task(by=manager, assignee=worker, title="Call the supplier")

    [entry] = Activity.objects.filter(recipient=worker)
    assert (entry.kind, entry.task, entry.actor) == (Activity.Kind.ASSIGNED, task, manager)
    assert not Activity.objects.filter(recipient=manager).exists()


def test_review_cycle_fills_both_feeds(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager, needs_confirmation=True)

    services.complete_task(task, by=worker)
    services.return_task(task, by=manager, reason="Blurry photo")

    kinds = dict(Activity.objects.values_list("recipient", "kind"))
    assert kinds[manager.pk] == Activity.Kind.REVIEW
    returned = Activity.objects.get(recipient=worker)
    assert (returned.kind, returned.text) == (Activity.Kind.RETURNED, "Blurry photo")


def test_comments_reach_the_other_side_only(manager, worker):
    task = TaskFactory(assignee=worker, created_by=manager)

    services.add_comment(task, by=worker, text="On it")

    assert list(Activity.objects.values_list("recipient", "kind")) == [
        (manager.pk, Activity.Kind.COMMENTED)
    ]


def test_feed_endpoint_and_mark_read(company, manager, worker):
    services.create_task(by=manager, assignee=worker, title="Prepare the window")
    api = client_for(worker)

    feed = api.get(f"/api/v1/companies/{company.pk}/activity/").data["results"]
    assert feed[0]["kind"] == "assigned"
    assert feed[0]["task"]["title"] == "Prepare the window"
    assert feed[0]["actor"]["id"] == manager.pk
    assert feed[0]["is_read"] is False

    assert api.post(f"/api/v1/companies/{company.pk}/activity/read/").data == {"marked": 1}
    assert stats.summary(worker, timezone.now())["unread_activity"] == 0


def test_feed_is_private(company, member, manager, worker):
    services.create_task(by=manager, assignee=worker, title="Mine")
    colleague = member.registered(company)

    feed = client_for(colleague).get(f"/api/v1/companies/{company.pk}/activity/")

    assert feed.data["results"] == []


# Repeating personal tasks


def test_repeating_personal_task_makes_a_series(company, worker):
    due = timezone.now() + timedelta(days=1)

    task = services.create_task(
        by=worker, title="Water the plants", due_at=due, repeat=Repeat.WEEKLY
    )

    template = task.template
    local_due = timezone.localtime(due, TASHKENT)
    assert template.personal
    assert template.weekdays == [local_due.weekday()]
    assert template.starts_on == local_due.date()
    assert task.for_date == local_due.date()

    # The day it was created for doesn't get a duplicate; a week later gets the next one.
    generate_daily_tasks(company, local_due.date())
    generate_daily_tasks(company, local_due.date() + timedelta(days=7))
    series = Task.objects.filter(template=template).order_by("for_date")
    assert [t.kind for t in series] == [Task.Kind.PERSONAL, Task.Kind.PERSONAL]
    assert series[1].for_date == local_due.date() + timedelta(days=7)


def test_series_starts_on_the_first_deadline(company, worker):
    tomorrow = timezone.now() + timedelta(days=1)
    task = services.create_task(by=worker, title="Stretch", due_at=tomorrow, repeat=Repeat.DAILY)

    generate_daily_tasks(company, timezone.localtime(timezone.now(), TASHKENT).date())

    assert list(Task.objects.filter(template=task.template)) == [task]


def test_repeating_needs_a_time_and_is_personal_only(manager, worker):
    with pytest.raises(Exception, match="Pick a time"):
        services.create_task(by=worker, title="Someday", repeat=Repeat.DAILY)
    with pytest.raises(Exception, match="daily tasks"):
        services.create_task(
            by=manager,
            assignee=worker,
            title="Every day",
            due_at=timezone.now() + timedelta(hours=1),
            repeat=Repeat.DAILY,
        )


def test_cancelling_can_stop_the_series(worker):
    task = services.create_task(
        by=worker,
        title="Water the plants",
        due_at=timezone.now() + timedelta(hours=2),
        repeat=Repeat.DAILY,
    )

    services.cancel_task(task, by=worker, stop_repeating=True)

    assert not TaskTemplate.objects.get(pk=task.template_id).is_active


def test_personal_series_stay_out_of_company_templates(company, manager, worker):
    services.create_task(
        by=worker, title="Mine", due_at=timezone.now() + timedelta(hours=2), repeat=Repeat.DAILY
    )

    response = client_for(manager).get(f"/api/v1/companies/{company.pk}/task-templates/")

    assert response.data == []


def test_api_shows_the_repeat_days(company, worker):
    response = client_for(worker).post(
        f"/api/v1/companies/{company.pk}/tasks/",
        {
            "title": "Opening checklist",
            "due_at": (timezone.now() + timedelta(hours=2)).isoformat(),
            "repeat": "weekdays",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["repeat_weekdays"] == [0, 1, 2, 3, 4]


# Visibility


def test_confirmers_see_work_waiting_for_a_check(company, worker):
    checker_role = AccessRoleFactory(company=company, permissions=[Perm.TASKS_CONFIRM])
    checker = MembershipFactory(
        company=company,
        role=checker_role,
        status=Membership.Status.APPROVED,
        onboarded_at=timezone.now(),
    )
    waiting = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)
    TaskFactory(assignee=worker)

    assert list(queries.visible_tasks(checker)) == [waiting]
