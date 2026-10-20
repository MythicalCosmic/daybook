"""A suspended member hears "Your access is paused until …" whatever they send."""

from datetime import date

import pytest
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import ReplyKeyboardRemove
from asgiref.sync import sync_to_async

from apps.members import services
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory
from tests import updates

pytestmark = pytest.mark.django_db(transaction=True)


async def suspended_worker(company, member, until):
    owner = await member.aregistered(company, "Owner")
    worker = await member.aregistered(company)
    await sync_to_async(services.suspend)(worker, by=owner, until=until, reason="Investigation")
    return owner, worker


@pytest.mark.parametrize("text", ["📋 My tasks", "hello", "/start"])
async def test_every_message_gets_the_paused_answer(dp, bot, company, member, text):
    _owner, worker = await suspended_worker(company, member, date(2099, 3, 1))

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), text))

    [reply] = [r for r in bot.requests if isinstance(r, SendMessage)]
    assert "Your access to" in reply.text
    assert "is paused until 01.03.2099" in reply.text
    assert isinstance(reply.reply_markup, ReplyKeyboardRemove)


async def test_until_further_notice(dp, bot, company, member):
    _owner, worker = await suspended_worker(company, member, None)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "hi"))

    assert "paused until further notice" in bot.sent_texts()[-1]


async def test_buttons_answer_with_the_same_alert_and_do_nothing(dp, bot, company, member):
    owner, worker = await suspended_worker(company, member, date(2099, 3, 1))
    task = await sync_to_async(TaskFactory)(assignee=worker, created_by=owner)
    press = TaskCallback(action=TaskAction.START, task_id=task.pk).pack()

    await dp.feed_update(bot, updates.callback(updates.tg_user(worker.user.telegram_id), press))

    [alert] = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)]
    assert alert.show_alert
    assert "paused until 01.03.2099" in alert.text
    assert (await Task.objects.aget(pk=task.pk)).status == Task.Status.TODO


async def test_after_reinstatement_the_bot_works_again(dp, bot, company, member):
    owner, worker = await suspended_worker(company, member, None)
    await sync_to_async(services.reinstate)(worker, by=owner)

    await dp.feed_update(bot, updates.message(updates.tg_user(worker.user.telegram_id), "hi"))

    assert "paused" not in bot.sent_texts()[-1]
    assert "member of" in bot.sent_texts()[-1]
