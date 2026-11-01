"""Queries per update in the busiest screens: the task list, a task card and the "to check"
list (10, 12 and 8 on 2026-11-02). Counted on every thread (the bot runs Django calls on a pool),
for a few rows and for more: the count must not grow with the rows."""

import threading
from contextlib import contextmanager
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.db.backends.utils import CursorWrapper
from django.utils import timezone

from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import ChecklistItem, Task
from apps.tasks.tests.factories import TaskFactory
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


@contextmanager
def counting():
    """Every query any thread runs inside the block."""
    seen = []
    lock = threading.Lock()
    real = CursorWrapper.execute

    def execute(self, sql, params=None):
        with lock:
            seen.append(sql)
        return real(self, sql, params)

    CursorWrapper.execute = execute
    try:
        yield seen
    finally:
        CursorWrapper.execute = real


@pytest.fixture
def people(company, member):
    def setup():
        boss = member.registered(company, "Manager")
        worker = member.registered(company)
        return boss, worker

    return sync_to_async(setup)()


def give(boss, worker, n):
    now = timezone.now()
    for index in range(n):
        task = TaskFactory(
            assignee=worker, created_by=boss, due_at=now + timedelta(hours=index + 1)
        )
        ChecklistItem.objects.create(task=task, text="Qadam", order=0)
        TaskFactory(
            assignee=worker,
            created_by=boss,
            status=Task.Status.REVIEW,
            needs_confirmation=True,
            completed_at=now,
        )


async def cost(dp, bot, tg, update) -> int:
    with counting() as seen:
        await dp.feed_update(bot, update)
    return len(seen)


@pytest.mark.parametrize("screen", ["My tasks", "To check"])
async def test_a_list_costs_the_same_whatever_the_rows(dp, bot, people, screen):
    boss, worker = await people
    who = boss if screen == "To check" else worker
    tg = updates.tg_user(who.user.telegram_id)
    await sync_to_async(give)(boss, worker, 1)
    await dp.feed_update(bot, updates.message(tg, screen))  # warm per-process caches
    few = await cost(dp, bot, tg, updates.message(tg, screen))

    await sync_to_async(give)(boss, worker, 6)
    many = await cost(dp, bot, tg, updates.message(tg, screen))

    assert many == few


async def test_a_card_costs_the_same_whatever_the_task(dp, bot, people):
    boss, worker = await people
    tg = updates.tg_user(worker.user.telegram_id)
    await sync_to_async(give)(boss, worker, 1)
    task = await Task.objects.filter(assignee=worker, status=Task.Status.TODO).afirst()
    tap = TaskCallback(action=TaskAction.OPEN, task_id=task.pk).pack()
    await dp.feed_update(bot, updates.callback(tg, tap))
    few = await cost(dp, bot, tg, updates.callback(tg, tap))

    def more_steps():
        for index in range(5):
            ChecklistItem.objects.create(task=task, text=f"Qadam {index}", order=index + 1)

    await sync_to_async(more_steps)()
    many = await cost(dp, bot, tg, updates.callback(tg, tap))

    assert many == few
