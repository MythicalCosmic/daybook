from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.tasks import services
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Proof, Task
from apps.tasks.notifications import send_task_assigned, send_task_completed, send_task_reviewed
from apps.tasks.tests.factories import TaskFactory, jpeg

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def actions(message) -> list[TaskAction]:
    rows = message["reply_markup"]["inline_keyboard"]
    return [
        TaskCallback.unpack(button["callback_data"]).action
        for row in rows
        for button in row
        if button.get("callback_data", "").startswith("task:")
    ]


def test_assignee_hears_about_a_new_task_with_buttons(manager, worker, sent_messages):
    task = TaskFactory(assignee=worker, created_by=manager, title="Call the supplier")

    send_task_assigned(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == worker.user.telegram_id
    assert "New task" in message["text"]
    assert "Call the supplier" in message["text"]
    assert actions(message) == [
        TaskAction.START,
        TaskAction.DONE,
        TaskAction.COMMENT,
        TaskAction.BLOCK,
        TaskAction.LIST,
    ]
    rows = message["reply_markup"]["inline_keyboard"]
    assert all(len(row) <= 2 for row in rows)  # two buttons a row at most (research R1 C2)


def test_finished_work_goes_to_the_reviewer_with_the_photo(manager, worker, sent_messages):
    task = TaskFactory(
        assignee=worker, created_by=manager, proof=Proof.PHOTO, needs_confirmation=True
    )
    task = services.complete_task(task, by=worker, proof_photo=jpeg("proof.jpg"))

    send_task_completed(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == manager.user.telegram_id
    assert message["photo"] == task.proof_photo.name
    assert actions(message) == [TaskAction.CONFIRM, TaskAction.RETURN]


def test_daily_task_review_goes_to_the_closest_checkers(company, member, worker, sent_messages):
    """Audit X-11: managers check routine work; the owner hears only when nobody else may."""
    manager = member.registered(company, "Manager")
    member.registered(company, "Owner")
    task = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)

    send_task_completed(task.pk)

    assert {m["chat_id"] for m in sent_messages} == {manager.user.telegram_id}


def test_the_owner_checks_when_nobody_else_may(company, member, worker, sent_messages):
    owner = member.registered(company, "Owner")
    task = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)

    send_task_completed(task.pk)

    assert {m["chat_id"] for m in sent_messages} == {owner.user.telegram_id}


def test_creator_hears_when_an_assigned_task_is_done(manager, worker, sent_messages):
    """Audit B-19: two short lines and the open button, not the whole card again."""
    task = TaskFactory(
        assignee=worker, created_by=manager, status=Task.Status.DONE, title="Count the till"
    )

    send_task_completed(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == manager.user.telegram_id
    assert message["text"].splitlines() == [f"<b>Task done</b> · {worker}", "Count the till"]
    assert actions(message) == [TaskAction.OPEN]


def test_the_done_notice_says_how_late_and_the_report(manager, worker, sent_messages):
    done = timezone.now()
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        status=Task.Status.DONE,
        title="Count the till",
        due_at=done - timedelta(minutes=25),
        completed_at=done,
        proof_text="All counted",
    )

    send_task_completed(task.pk)

    [message] = sent_messages
    assert message["text"].splitlines()[1:] == [
        "Count the till · late by 25 min",
        "Report: All counted",
    ]
    assert "Status:" not in message["text"]


def test_assignee_hears_the_acceptance_in_two_lines(manager, worker, sent_messages, settings):
    """Audit B-19: who accepted it, the title and the reward, with "Open in app"."""
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example/app/"
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        status=Task.Status.REVIEW,
        title="Tidy the window",
        reward=Decimal("20000"),
    )
    services.confirm_task(task, by=manager)

    send_task_reviewed(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == worker.user.telegram_id
    lines = message["text"].splitlines()
    assert lines[:2] == [f"<b>Your task was accepted</b> · {manager}", "Tidy the window"]
    assert lines[2].startswith("Reward: +20")
    assert len(lines) == 3
    [[button]] = message["reply_markup"]["inline_keyboard"]
    assert button["text"] == "Open in app"
    assert button["web_app"]["url"].endswith(f"screen=task%3A{task.pk}")


def test_personal_task_done_tells_nobody(worker, sent_messages):
    task = TaskFactory(assignee=worker, status=Task.Status.DONE)

    send_task_completed(task.pk)

    assert sent_messages == []


def test_assignee_hears_the_review_outcome(manager, worker, sent_messages):
    task = TaskFactory(assignee=worker, created_by=manager, status=Task.Status.REVIEW)
    services.return_task(task, by=manager, reason="Blurry")

    send_task_reviewed(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == worker.user.telegram_id
    assert "sent back: Blurry" in message["text"]
