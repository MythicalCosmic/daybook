import pytest

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
    return [TaskCallback.unpack(button["callback_data"]).action for row in rows for button in row]


def test_assignee_hears_about_a_new_task_with_buttons(manager, worker, sent_messages):
    task = TaskFactory(assignee=worker, created_by=manager, title="Call the supplier")

    send_task_assigned(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == worker.user.telegram_id
    assert "New task" in message["text"]
    assert "Call the supplier" in message["text"]
    assert actions(message) == [TaskAction.START, TaskAction.DONE, TaskAction.LIST]


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


def test_daily_task_review_goes_to_everyone_who_can_confirm(company, member, worker, sent_messages):
    manager = member.registered(company, "Manager")
    owner = member.registered(company, "Owner")
    task = TaskFactory(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)

    send_task_completed(task.pk)

    assert {m["chat_id"] for m in sent_messages} == {
        manager.user.telegram_id,
        owner.user.telegram_id,
    }


def test_creator_hears_when_an_assigned_task_is_done(manager, worker, sent_messages):
    task = TaskFactory(assignee=worker, created_by=manager, status=Task.Status.DONE)

    send_task_completed(task.pk)

    [message] = sent_messages
    assert message["chat_id"] == manager.user.telegram_id
    assert "completed a task" in message["text"]


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
