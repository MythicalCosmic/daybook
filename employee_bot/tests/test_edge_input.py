"""What people actually send, in every conversation the bot holds: stickers, photos and files
where it waits for words, words where it waits for a photo, a blank or a very long text, markup
it must not render, someone else's contact, a command it doesn't know. No handler may fail on
them (the shared error handler would log "Update … failed"), and no answer may break
Telegram's rules (the `bot` fixture)."""

import logging
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Proof, Task
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def press(action: TaskAction, task_id: int = 0) -> str:
    return TaskCallback(action=action, task_id=task_id).pack()


def odd_things(tg) -> list:
    return [
        updates.sticker(tg),
        updates.photo(tg),
        updates.image_file(tg, mime_type="application/pdf"),
        updates.contact(tg, "+998901112233", owner_id=tg.id + 1),
        updates.message(tg, "   "),
        updates.message(tg, "x" * 5000),
        updates.message(tg, "<b>salom</b> & <i>"),
        updates.message(tg, "/nimadir"),
    ]


@pytest.fixture
def people(company, member):
    def setup():
        boss = member.registered(company, "Manager")
        worker = member.registered(company)
        now = timezone.now()
        task = Task.objects.create(
            company=company,
            kind=Task.Kind.ASSIGNED,
            title="Kassani sanash",
            assignee=worker,
            created_by=boss,
            due_at=now + timedelta(hours=2),
            proof=Proof.PHOTO,
        )
        return boss, worker, task

    return sync_to_async(setup)()


# How to reach each conversation, from the main menu: the updates that open it.
CONVERSATIONS = {
    "idle": lambda tg, task: [],
    "new task title": lambda tg, task: [updates.message(tg, "New task")],
    "comment": lambda tg, task: [updates.callback(tg, press(TaskAction.COMMENT, task.pk))],
    "proof photo": lambda tg, task: [updates.callback(tg, press(TaskAction.DONE, task.pk))],
    "more time": lambda tg, task: [updates.callback(tg, press(TaskAction.MORE_TIME, task.pk))],
}


@pytest.mark.parametrize("conversation", list(CONVERSATIONS))
async def test_odd_input_in_every_conversation(dp, bot, people, conversation, caplog):
    _boss, worker, task = await people
    tg = updates.tg_user(worker.user.telegram_id)
    caplog.set_level(logging.ERROR)

    for update in odd_things(tg):
        for opening in CONVERSATIONS[conversation](tg, task):
            await dp.feed_update(bot, opening)
        await dp.feed_update(bot, update)

    failed = [record.getMessage() for record in caplog.records if "failed" in record.getMessage()]
    assert not failed, failed
