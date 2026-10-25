"""Work accepted automatically (docs/PLAN-OWNER.md §15.3) reads "Accepted" in the bot at once:
the note after Done and the card's status, not "sent for checking"."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from asgiref.sync import sync_to_async

from apps.tasks import conf
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import OnFinish, Proof, Task
from apps.tasks.tests.factories import TaskFactory
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


def press(action: TaskAction, task_id: int) -> str:
    return TaskCallback(action=action, task_id=task_id).pack()


def of(bot, kind) -> list:
    return [r for r in bot.requests if isinstance(r, kind)]


async def test_work_accepted_at_once_says_accepted(dp, bot, company, member):
    worker = await member.aregistered(company, user__language="uz")
    manager = await member.aregistered(company, "Manager")
    task = await sync_to_async(TaskFactory)(assignee=worker, created_by=manager, title="Vitrina")

    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(worker.user.telegram_id), press(TaskAction.DONE, task.pk)),
    )

    assert (await Task.objects.aget(pk=task.pk)).status == Task.Status.DONE
    assert of(bot, AnswerCallbackQuery)[-1].text == "Qabul qilindi"
    assert "Holati: Qabul qilindi" in of(bot, EditMessageText)[-1].text


async def test_only_with_proof_and_no_proof_still_goes_for_checking(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    row = await sync_to_async(conf.get_settings)(company)
    row.on_finish = OnFinish.PROOF
    await row.asave()
    task = await sync_to_async(TaskFactory)(
        assignee=worker,
        created_by=manager,
        proof=Proof.NONE,
        needs_confirmation=True,
        accept_with_proof=True,
    )

    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(worker.user.telegram_id), press(TaskAction.DONE, task.pk)),
    )

    assert (await Task.objects.aget(pk=task.pk)).status == Task.Status.REVIEW
    assert "Sent for checking" in of(bot, AnswerCallbackQuery)[-1].text
