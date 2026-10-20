from datetime import timedelta

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.tasks.callbacks import DueCallback, DuePreset, TaskAction, TaskCallback
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory
from tests import updates
from tests.mocked_bot import FILE_CONTENT

pytestmark = pytest.mark.django_db(transaction=True)

make_task = sync_to_async(TaskFactory)


def press(action: TaskAction, task_id: int = 0) -> str:
    return TaskCallback(action=action, task_id=task_id).pack()


def sent(bot) -> list[SendMessage]:
    return [r for r in bot.requests if isinstance(r, SendMessage)]


def edits(bot) -> list[EditMessageText]:
    return [r for r in bot.requests if isinstance(r, EditMessageText)]


def alerts(bot) -> list[str]:
    return [r.text for r in bot.requests if isinstance(r, AnswerCallbackQuery) and r.show_alert]


async def reload(task: Task) -> Task:
    return await Task.objects.aget(pk=task.pk)


async def test_my_tasks_lists_whats_due_today(dp, bot, company, member):
    worker = await member.aregistered(company)
    late = await make_task(
        assignee=worker, title="Stock count", due_at=timezone.now() - timedelta(minutes=30)
    )
    await make_task(assignee=worker, title="Next week", due_at=timezone.now() + timedelta(days=7))
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "📋 My tasks"))

    reply = sent(bot)[-1]
    buttons = [row[0] for row in reply.reply_markup.inline_keyboard]
    assert len(buttons) == 1
    assert "Stock count" in buttons[0].text
    assert buttons[0].text.startswith("🔴")
    assert TaskCallback.unpack(buttons[0].callback_data).task_id == late.pk


async def test_open_start_and_finish_a_task(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, title="Reply to customers")
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.OPEN, task.pk)))
    assert "Reply to customers" in edits(bot)[-1].text

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.START, task.pk)))
    assert (await reload(task)).status == Task.Status.IN_PROGRESS

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))
    assert (await reload(task)).status == Task.Status.DONE
    assert "Status: Done" in edits(bot)[-1].text


async def test_photo_proof_is_collected_before_completing(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, title="Front shelf", proof=Proof.PHOTO)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))
    assert "Send a photo" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.message(tg, "it's done, trust me"))
    assert "Attach a photo" in sent(bot)[-1].text
    assert (await reload(task)).status == Task.Status.TODO

    await dp.feed_update(bot, updates.photo(tg, caption="Shelf after restock"))
    task = await reload(task)
    assert task.status == Task.Status.DONE
    assert task.proof_text == "Shelf after restock"
    assert await sync_to_async(task.proof_photo.read)() == FILE_CONTENT


async def test_text_report_completes_a_report_task(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, proof=Proof.TEXT)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))
    await dp.feed_update(bot, updates.message(tg, "Takings 4.2M, ran out of rolls"))

    task = await reload(task)
    assert task.status == Task.Status.DONE
    assert task.proof_text == "Takings 4.2M, ran out of rolls"


async def test_cancel_stops_waiting_for_proof(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, proof=Proof.TEXT)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.STOP)))
    await dp.feed_update(bot, updates.message(tg, "this is just chat"))

    assert (await reload(task)).status == Task.Status.TODO


async def test_new_task_with_a_preset_deadline(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "➕ New task"))
    await dp.feed_update(bot, updates.message(tg, "Order receipt rolls"))
    await dp.feed_update(bot, updates.callback(tg, DueCallback(preset=DuePreset.IN_AN_HOUR).pack()))

    task = await Task.objects.aget(assignee=worker)
    assert task.title == "Order receipt rolls"
    assert task.kind == Task.Kind.PERSONAL
    assert timedelta(minutes=55) < task.due_at - timezone.now() <= timedelta(hours=1)
    assert "Added to your list" in sent(bot)[-1].text


async def test_new_task_with_a_typed_deadline(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Learn the refunds flow"))
    await dp.feed_update(bot, updates.message(tg, "whenever"))
    assert "I didn't get that" in sent(bot)[-1].text

    await dp.feed_update(bot, updates.message(tg, "25.12 18:00"))

    task = await Task.objects.aget(assignee=worker)
    assert timezone.localtime(task.due_at).strftime("%d.%m %H:%M") == "25.12 18:00"


async def test_menu_button_abandons_a_half_made_task(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "➕ New task"))
    await dp.feed_update(bot, updates.message(tg, "📋 My tasks"))
    await dp.feed_update(bot, updates.message(tg, "hello"))

    assert not await Task.objects.filter(assignee=worker).aexists()


async def test_manager_confirms_from_the_review_message(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(assignee=worker, created_by=manager, status=Task.Status.REVIEW)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(manager.user.telegram_id), press(TaskAction.CONFIRM, task.pk)
        ),
    )

    task = await reload(task)
    assert task.status == Task.Status.DONE
    assert task.confirmed_by_id == manager.pk


async def test_manager_sends_back_with_a_reason(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(assignee=worker, created_by=manager, status=Task.Status.REVIEW)
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.RETURN, task.pk)))
    await dp.feed_update(bot, updates.message(tg, "Retake it in daylight"))

    task = await reload(task)
    assert task.status == Task.Status.RETURNED
    comment = await task.comments.afirst()
    assert comment.text == "Retake it in daylight"


async def test_colleague_cannot_confirm_from_a_forwarded_button(dp, bot, company, member):
    worker = await member.aregistered(company)
    colleague = await member.aregistered(company)
    task = await make_task(assignee=worker, kind=Task.Kind.DAILY, status=Task.Status.REVIEW)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(colleague.user.telegram_id), press(TaskAction.CONFIRM, task.pk)
        ),
    )

    assert (await reload(task)).status == Task.Status.REVIEW
    assert alerts(bot) == ["This task no longer exists."]  # not even visible to them


async def test_unregistered_member_gets_the_registration_prompt(dp, bot, company, member):
    newcomer = await member.acreate(company)

    await dp.feed_update(bot, updates.message(updates.tg_user(newcomer.user.telegram_id), "/tasks"))

    assert "Accounts are created in the app" in sent(bot)[-1].text


async def test_snooze_from_a_reminder(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(
        assignee=worker,
        created_by=manager,
        due_at=timezone.now() - timedelta(minutes=5),
        next_reminder_at=timezone.now(),
    )
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.SNOOZE, task.pk)))

    task = await reload(task)
    assert task.snooze_count == 1
    answer = [r for r in bot.requests if isinstance(r, AnswerCallbackQuery)][-1]
    assert answer.text.startswith("Snoozed until")

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.SNOOZE, task.pk)))

    assert alerts(bot)[-1] == "No snoozes left for this task."
