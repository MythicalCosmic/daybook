"""Task points (PLAN-LEARNING §7.7): shared work done on time, at most ten a day, never personal
or self-given work; the nightly jobs."""

from datetime import timedelta

import pytest

from apps.recognition import conf, services, tasks
from apps.recognition.models import BadgeAward, PointsEntry
from apps.recognition.tests.conftest import DAY, at
from apps.recognition.tests.factories import PointsEntryFactory
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db
FRIDAY = DAY - timedelta(days=1)


def done(
    assignee, giver, *, due_hour=18, done_hour=16, status=Task.Status.DONE, day=FRIDAY, kind=None
):
    extra = {"kind": kind} if kind else {}
    return TaskFactory(
        assignee=assignee,
        created_by=giver,
        due_at=at(day, due_hour),
        completed_at=at(day, done_hour),
        status=status,
        **extra,
    )


def test_on_time_shared_work_earns_points_once(shop, ali, head):
    on_time = done(ali, head)
    late = done(ali, head, due_hour=12, done_hour=13)
    waiting = done(ali, head, status=Task.Status.REVIEW)
    personal = done(ali, ali)
    assert personal.kind == Task.Kind.PERSONAL
    self_given = done(ali, ali, kind=Task.Kind.ASSIGNED)
    routine = done(ali, None, kind=Task.Kind.DAILY)
    assert services.award_task_points(shop, FRIDAY) == 2
    keys = set(PointsEntry.objects.filter(reason="task").values_list("key", flat=True))
    assert keys == {f"task:{on_time.pk}", f"task:{routine.pk}"}
    assert f"task:{late.pk}" not in keys and f"task:{waiting.pk}" not in keys
    assert f"task:{self_given.pk}" not in keys
    assert services.award_task_points(shop, FRIDAY) == 0
    assert PointsEntry.objects.get(key=f"task:{on_time.pk}").points == 2


def test_at_most_ten_a_day(shop, ali, head):
    for minute in range(12):
        TaskFactory(
            assignee=ali,
            created_by=head,
            due_at=at(FRIDAY, 18),
            completed_at=at(FRIDAY, 10, minute),
            status=Task.Status.DONE,
        )
    assert services.award_task_points(shop, FRIDAY) == 10
    assert services.award_task_points(shop, FRIDAY) == 0
    assert PointsEntry.objects.filter(membership=ali, reason="task").count() == 10


def test_switched_off(shop, ali, head):
    done(ali, head)
    settings = conf.get_settings(shop)
    settings.task_points = False
    settings.save()
    assert services.award_task_points(shop, FRIDAY) == 0


def test_the_hourly_job_catches_up_two_days(shop, ali, head):
    done(ali, head, day=FRIDAY)
    done(ali, head, day=FRIDAY - timedelta(days=1))
    done(ali, head, day=DAY)  # today: not yet
    assert tasks.task_points() == 2


def test_the_nightly_sweep_runs_once_a_night(shop, ali, freeze):
    PointsEntryFactory(membership=ali, reason="lesson", key="lesson:n")
    freeze(at(DAY, 14))
    assert tasks.nightly() == 0  # not the small hours
    freeze(at(DAY + timedelta(days=1), 2))
    assert tasks.nightly() == 1
    assert BadgeAward.objects.filter(membership=ali, badge="first_lesson").exists()
    assert tasks.nightly() == 0  # once a night


def test_the_sweep_gives_last_month_s_top_three_early_in_the_month(shop, ali, madina, freeze):
    PointsEntryFactory(membership=ali, points=40, at=at(DAY - timedelta(days=10)), key="o:1")
    PointsEntryFactory(membership=madina, points=10, at=at(DAY - timedelta(days=12)), key="o:2")
    freeze(at(DAY.replace(day=1), 1))  # 1 November, the small hours
    services.sweep(shop)
    refs = set(BadgeAward.objects.filter(badge="top3_month").values_list("ref", flat=True))
    assert refs == {"2026-10"}
