"""Every copy of a task message stays current (research R1 C5, audit B-8, X-6, X-11): the other
checker's request once one accepted, the card of someone the task was taken from, the last
reminder once the task is done, a manager's late alert once the work is in."""

from datetime import timedelta
from itertools import count

import pytest
from django.utils import timezone

from apps.reminders.engine import send_due_reminders
from apps.reminders.policies import default_policy
from apps.tasks import services
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Task, TaskMessage
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def telegram(monkeypatch):
    """Sends get message ids; edits and deletes are recorded."""
    ids = count(100)
    log = {"sent": [], "edits": [], "deleted": []}

    def send(bot, chat_id, text, reply_markup=None, photo=None, photo_storage="default"):
        message_id = next(ids)
        log["sent"].append({"chat_id": chat_id, "id": message_id, "text": text})
        return message_id

    def edit(bot, chat_id, message_id, text, reply_markup=None):
        log["edits"].append(
            {"chat_id": chat_id, "id": message_id, "text": text, "markup": reply_markup}
        )

    monkeypatch.setattr("apps.notifications.telegram.send_message", send)
    monkeypatch.setattr("apps.notifications.telegram.edit_message", edit)
    monkeypatch.setattr(
        "apps.notifications.telegram.delete_message",
        lambda bot, chat_id, message_id: log["deleted"].append(message_id),
    )
    return log


def actions(markup) -> list[str]:
    rows = (markup or {}).get("inline_keyboard", [])
    return [
        TaskCallback.unpack(button["callback_data"]).action
        for row in rows
        for button in row
        if button.get("callback_data", "").startswith("task:")
    ]


def edits_to(log, member) -> list[dict]:
    return [edit for edit in log["edits"] if edit["chat_id"] == member.user.telegram_id]


def test_the_other_checkers_request_says_who_accepted(
    company, member, telegram, django_capture_on_commit_callbacks
):
    worker = member.registered(company)
    first = member.registered(company, "Manager")
    second = member.registered(company, "Manager")
    task = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, needs_confirmation=True)
    with django_capture_on_commit_callbacks(execute=True):
        services.complete_task(task, by=worker)
    assert TaskMessage.objects.filter(task=task, kind=TaskMessage.Kind.REVIEW).count() == 2

    with django_capture_on_commit_callbacks(execute=True):
        services.confirm_task(task, by=first)

    copy = edits_to(telegram, second)[-1]  # drawn again at each change; this is the last
    assert copy["text"].startswith(f"✅ <b>Accepted</b> · {first}")
    assert TaskAction.CONFIRM not in actions(copy["markup"])


def test_the_card_of_someone_a_task_was_taken_from_loses_its_buttons(
    company, member, telegram, django_capture_on_commit_callbacks
):
    manager = member.registered(company, "Manager")
    worker, other = member.registered(company), member.registered(company)
    with django_capture_on_commit_callbacks(execute=True):
        task = services.create_task(
            by=manager,
            title="Count stock",
            assignee=worker,
            due_at=timezone.now() + timedelta(hours=2),
        )

    with django_capture_on_commit_callbacks(execute=True):
        services.reassign_task(task, by=manager, assignee=other)

    [copy] = [
        edit for edit in edits_to(telegram, worker) if "Given to someone else" in edit["text"]
    ]
    assert actions(copy["markup"]) == []


def test_done_takes_the_last_reminder_away_and_updates_the_late_alert(
    company, member, telegram, django_capture_on_commit_callbacks
):
    worker = member.registered(company)
    manager = member.registered(company, "Manager")
    policy = default_policy(company.pk)
    policy.escalate_after = 1
    policy.save()
    due = timezone.now() - timedelta(minutes=30)
    task = TaskFactory(assignee=worker, created_by=manager, due_at=due, next_reminder_at=due)
    send_due_reminders(timezone.now())
    task.refresh_from_db()
    assert task.last_reminder_message_id is not None
    assert TaskMessage.objects.filter(task=task, kind=TaskMessage.Kind.ESCALATION).exists()

    with django_capture_on_commit_callbacks(execute=True):
        services.complete_task(task, by=worker)

    assert telegram["deleted"] == [task.last_reminder_message_id]
    escalation = TaskMessage.objects.get(task=task, kind=TaskMessage.Kind.ESCALATION)
    alert = [edit for edit in edits_to(telegram, manager) if edit["id"] == escalation.message_id][
        -1
    ]
    assert alert["text"].startswith("✅ <b>Done</b>") and "late" in alert["text"]
