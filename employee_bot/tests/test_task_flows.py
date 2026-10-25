"""The task flows of the polish pass: Undo, steps on the card, the proof photo on the card it
was asked on (albums and files too), "which task is this photo for?", comments by button and by
reply, quick add with "what I understood", managers giving work, lists with pages and the "to
check" list, people in two companies, "can't do it", "need more time", and the small things
(thanks get a, a failing handler still answers)."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SetMessageReaction,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.companies.tests.factories import CompanyFactory
from apps.tasks.callbacks import (
    DueCallback,
    DuePreset,
    ListCallback,
    PhotoCallback,
    PickCallback,
    QuickAddCallback,
    ReasonCallback,
    SnoozeCallback,
    StepCallback,
    TaskAction,
    TaskCallback,
    WhenCallback,
)
from apps.tasks.models import ChecklistItem, Proof, Task, TaskComment
from apps.tasks.tests.factories import TaskFactory, jpeg_bytes
from tests import mocked_bot, updates

pytestmark = pytest.mark.django_db(transaction=True)

make_task = sync_to_async(TaskFactory)


def press(action: TaskAction, task_id: int = 0) -> str:
    return TaskCallback(action=action, task_id=task_id).pack()


def of(bot, kind) -> list:
    return [r for r in bot.requests if isinstance(r, kind)]


def answers(bot) -> list[AnswerCallbackQuery]:
    return of(bot, AnswerCallbackQuery)


def actions_of(markup) -> list[str]:
    return [
        TaskCallback.unpack(button.callback_data).action
        for row in markup.inline_keyboard
        for button in row
        if (button.callback_data or "").startswith("task:")
    ]


async def reload(task: Task) -> Task:
    return await Task.objects.aget(pk=task.pk)


@pytest.fixture
def real_photos(monkeypatch):
    """Proof photos are decoded and re-encoded, so a download must be a real picture."""
    monkeypatch.setattr(mocked_bot, "FILE_CONTENT", jpeg_bytes())


# Undo, steps, review --------------------------------------------------------------------


async def test_done_can_be_undone_from_the_card(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, title="Wipe the display case")
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))
    assert (await reload(task)).status == Task.Status.DONE
    assert TaskAction.UNDO in actions_of(of(bot, EditMessageText)[-1].reply_markup)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.UNDO, task.pk)))

    assert (await reload(task)).status == Task.Status.TODO
    assert answers(bot)[-1].text == "The task is open again."


async def test_work_sent_for_checking_says_so(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(assignee=worker, created_by=manager, needs_confirmation=True)

    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(worker.user.telegram_id), press(TaskAction.DONE, task.pk)),
    )

    assert answers(bot)[-1].text == f"Sent for checking · {manager}"  # audit B-5


async def test_steps_are_ticked_on_the_card_and_done_asks_first(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, title="Opening checklist")
    first = await ChecklistItem.objects.acreate(task=task, text="Count the till", order=0)
    await ChecklistItem.objects.acreate(task=task, text="Fridge reading", order=1)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.OPEN, task.pk)))
    step_rows = [
        row[0].text
        for row in of(bot, EditMessageText)[-1].reply_markup.inline_keyboard
        if (row[0].callback_data or "").startswith("tstep:")
    ]
    assert step_rows == ["Count the till", "Fridge reading"]

    await dp.feed_update(
        bot, updates.callback(tg, StepCallback(task_id=task.pk, item_id=first.pk).pack())
    )
    assert (await ChecklistItem.objects.aget(pk=first.pk)).is_done

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))
    assert (await reload(task)).status == Task.Status.TODO
    assert "Steps not ticked yet: 1" in of(bot, EditMessageText)[-1].text

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.TICK_ALL, task.pk)))
    assert (await reload(task)).status == Task.Status.DONE
    assert not await ChecklistItem.objects.filter(task=task, is_done=False).aexists()


async def test_seen_when_the_assignee_opens_the_card(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(assignee=worker, created_by=manager)

    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(manager.user.telegram_id), press(TaskAction.OPEN, task.pk)
        ),
    )
    assert (await reload(task)).seen_at is None
    await dp.feed_update(
        bot,
        updates.callback(updates.tg_user(worker.user.telegram_id), press(TaskAction.OPEN, task.pk)),
    )
    assert (await reload(task)).seen_at is not None


# Proof ----------------------------------------------------------------------------------


async def test_the_proof_photo_lands_on_the_card_it_was_asked_on(
    dp, bot, company, member, real_photos
):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, title="Front shelf", proof=Proof.PHOTO)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))
    prompt = of(bot, EditMessageText)[-1]
    assert "Send a photo" in prompt.text
    assert actions_of(prompt.reply_markup) == [TaskAction.STOP]  # only Cancel while it waits

    await dp.feed_update(bot, updates.photo(tg, media_group_id="album-1"))
    await dp.feed_update(bot, updates.photo(tg, media_group_id="album-1"))  # the album's second

    assert (await reload(task)).status == Task.Status.DONE
    reactions = [r.reaction[0].emoji for r in of(bot, SetMessageReaction)]
    assert reactions == ["", "", ""]  # working, done, and the album's extra photo
    assert "Front shelf" in of(bot, EditMessageText)[-1].text  # the card, done


async def test_a_photo_sent_as_a_file_is_proof_too(dp, bot, company, member, real_photos):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, proof=Proof.PHOTO)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))

    await dp.feed_update(bot, updates.image_file(tg))

    assert (await reload(task)).status == Task.Status.DONE


async def test_anything_else_while_a_photo_is_awaited_asks_again(dp, bot, company, member):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, proof=Proof.PHOTO)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.DONE, task.pk)))

    await dp.feed_update(bot, updates.sticker(tg))

    assert "Send a photo" in of(bot, SendMessage)[-1].text
    assert (await reload(task)).status == Task.Status.TODO


async def test_a_photo_first_asks_which_task_it_is_for(dp, bot, company, member, real_photos):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker, title="Price tags", proof=Proof.PHOTO)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.photo(tg, caption="done"))
    question = of(bot, SendMessage)[-1]
    assert question.text == "Which task is this photo for?"
    assert "Price tags" in question.reply_markup.inline_keyboard[0][0].text

    await dp.feed_update(bot, updates.callback(tg, PhotoCallback(task_id=task.pk).pack()))

    task = await reload(task)
    assert task.status == Task.Status.DONE and task.proof_text == "done"


# Comments -------------------------------------------------------------------------------


async def test_a_comment_by_button_and_by_reply(dp, bot, company, member, sent_messages):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(assignee=worker, created_by=manager)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.COMMENT, task.pk)))
    assert of(bot, SendMessage)[-1].reply_markup.force_reply  # the reply field opens
    await dp.feed_update(bot, updates.message(tg, "Terminal cheki topilmayapti"))

    card = TaskCallback(action=TaskAction.OPEN, task_id=task.pk).pack()
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Open", callback_data=card)]]
    )
    await dp.feed_update(bot, updates.reply(tg, "Ertalab yozaman", markup))

    texts = [c async for c in TaskComment.objects.filter(task=task).values_list("text", flat=True)]
    assert texts == ["Terminal cheki topilmayapti", "Ertalab yozaman"]
    assert [r.reaction[0].emoji for r in of(bot, SetMessageReaction)] == ["", ""]
    assert any(m["chat_id"] == manager.user.telegram_id for m in sent_messages)  # it reached them


# New tasks ------------------------------------------------------------------------------


async def test_the_title_can_carry_the_deadline(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Kassani sanash 25.12 10:00!!"))
    preview = of(bot, SendMessage)[-1]
    assert "<b>Kassani sanash</b>" in preview.text
    assert "10:00" in preview.text and "" in preview.text
    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="save").pack()))

    task = await Task.objects.aget(assignee=worker)
    due = timezone.localtime(task.due_at, ZoneInfo(company.timezone))
    assert task.title == "Kassani sanash" and task.priority == Task.Priority.URGENT
    assert (due.day, due.month, due.hour, due.minute) == (25, 12, 10, 0)


async def test_not_a_date_keeps_the_words(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Juma namozi"))

    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="literal").pack()))
    await dp.feed_update(bot, updates.callback(tg, DueCallback(preset=DuePreset.NONE).pack()))
    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="save").pack()))

    task = await Task.objects.aget(assignee=worker)
    assert task.title == "Juma namozi" and task.due_at is None


async def test_a_time_that_has_passed_offers_tomorrow(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)
    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Kassa"))

    await dp.feed_update(bot, updates.message(tg, "bugun 00:00"))
    assert "has already passed today" in of(bot, SendMessage)[-1].text
    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="tomorrow").pack()))
    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="save").pack()))

    task = await Task.objects.aget(assignee=worker)
    assert task.due_at > timezone.now()


async def test_a_manager_gives_work_from_new_task(dp, bot, company, member):
    manager = await member.aregistered(company, "Manager")
    worker = await member.aregistered(company)
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/new"))
    await dp.feed_update(bot, updates.message(tg, "Kassa lentasini olib kel"))
    picker = of(bot, SendMessage)[-1]
    assert picker.reply_markup.inline_keyboard[0][0].text == "Me"
    await dp.feed_update(
        bot, updates.callback(tg, PickCallback(task_id=0, member_id=worker.pk).pack())
    )
    await dp.feed_update(bot, updates.callback(tg, DueCallback(preset=DuePreset.IN_AN_HOUR).pack()))
    assert f"For: {worker}" in of(bot, EditMessageText)[-1].text
    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="save").pack()))

    task = await Task.objects.aget(created_by=manager)
    assert task.assignee_id == worker.pk and task.kind == Task.Kind.ASSIGNED


async def test_plain_text_is_offered_as_a_task(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "Vitrinani artish"))
    assert "Add this as a task?" in of(bot, SendMessage)[-1].text
    await dp.feed_update(bot, updates.callback(tg, QuickAddCallback(action="save").pack()))

    assert (await Task.objects.aget(assignee=worker)).title == "Vitrinani artish"


async def test_thanks_and_stickers_get_a_thumbs_up(dp, bot, company, member):
    worker = await member.aregistered(company)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "Rahmat!"))
    await dp.feed_update(bot, updates.sticker(tg))

    assert of(bot, SendMessage) == []
    assert [r.reaction[0].emoji for r in of(bot, SetMessageReaction)] == ["", ""]


# Lists ----------------------------------------------------------------------------------


async def test_long_lists_have_pages_and_checkers_have_their_list(dp, bot, company, member):
    manager = await member.aregistered(company, "Manager")
    worker = await member.aregistered(company)
    for number in range(10):
        await make_task(assignee=manager, title=f"Count {number}")
    await make_task(assignee=worker, created_by=manager, status=Task.Status.REVIEW)
    tg = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "My tasks"))
    listing = of(bot, SendMessage)[-1]
    labels = [row[0].text for row in listing.reply_markup.inline_keyboard]
    assert "1/2" in [b.text for row in listing.reply_markup.inline_keyboard for b in row]
    assert "To check (1)" in [
        b.text for row in listing.reply_markup.inline_keyboard for b in row
    ]
    assert len([label for label in labels if "Count" in label]) == 8

    await dp.feed_update(bot, updates.callback(tg, ListCallback(view="mine", page=1).pack()))
    assert (
        len(
            [
                r
                for r in of(bot, EditMessageText)[-1].reply_markup.inline_keyboard
                if "Count" in r[0].text
            ]
        )
        == 2
    )

    await dp.feed_update(bot, updates.message(tg, "/check"))
    assert "To check" in of(bot, SendMessage)[-1].text


# People in two companies (audit X-1) ----------------------------------------------------


async def test_a_push_from_the_other_company_works(dp, bot, member):
    shop, supplier = await sync_to_async(CompanyFactory)(), await sync_to_async(CompanyFactory)()
    owner = await member.aregistered(shop, "Owner")
    await member.aregistered(supplier, "Owner", user=owner.user)
    worker = await member.aregistered(shop)
    task = await make_task(
        assignee=worker, created_by=owner, status=Task.Status.REVIEW, needs_confirmation=True
    )
    # The bot works in the supplier for them...
    await sync_to_async(type(owner.user).objects.filter(pk=owner.user_id).update)(
        bot_company=supplier
    )
    tg = updates.tg_user(owner.user.telegram_id)

    # ...and still accepts the shop's work from its push.
    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.CONFIRM, task.pk)))

    assert (await reload(task)).status == Task.Status.DONE
    owner.user.refresh_from_db = None
    assert (await type(owner.user).objects.aget(pk=owner.user_id)).bot_company_id == shop.pk


async def test_a_push_from_the_other_company_brings_its_menu(dp, bot, member):
    """Final review: the tap moved the lists to the shop, but the menu still said "Supplier ▸"
    (and showed the supplier's modules) until /start."""
    from aiogram.types import ReplyKeyboardMarkup

    shop, supplier = await sync_to_async(CompanyFactory)(), await sync_to_async(CompanyFactory)()
    owner = await member.aregistered(shop, "Owner")
    await member.aregistered(supplier, "Owner", user=owner.user)
    worker = await member.aregistered(shop)
    task = await make_task(
        assignee=worker, created_by=owner, status=Task.Status.REVIEW, needs_confirmation=True
    )
    await sync_to_async(type(owner.user).objects.filter(pk=owner.user_id).update)(
        bot_company=supplier
    )
    tg = updates.tg_user(owner.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.CONFIRM, task.pk)))

    note = of(bot, SendMessage)[-1]
    assert note.text == f"Now working in <b>{shop.name}</b>."
    assert isinstance(note.reply_markup, ReplyKeyboardMarkup)
    labels = [button.text for row in note.reply_markup.keyboard for button in row]
    assert any(shop.name in label for label in labels)

    # A second tap in the same company changes nothing, so it says nothing.
    sent = len(of(bot, SendMessage))
    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.OPEN, task.pk)))
    assert len(of(bot, SendMessage)) == sent


async def test_the_company_switch(dp, bot, member):
    shop, supplier = await sync_to_async(CompanyFactory)(), await sync_to_async(CompanyFactory)()
    owner = await member.aregistered(shop, "Owner")
    await member.aregistered(supplier, "Owner", user=owner.user)
    tg = updates.tg_user(owner.user.telegram_id)

    await dp.feed_update(bot, updates.message(tg, "/company"))
    picker = of(bot, SendMessage)[-1]
    names = [row[0].text.removeprefix("✓ ") for row in picker.reply_markup.inline_keyboard]
    assert sorted(names) == sorted([shop.name, supplier.name])

    choose = picker.reply_markup.inline_keyboard[names.index(supplier.name)][0].callback_data
    await dp.feed_update(bot, updates.callback(tg, choose))

    assert supplier.name in of(bot, SendMessage)[-1].text  # the home of that company
    assert (await type(owner.user).objects.aget(pk=owner.user_id)).bot_company_id == supplier.pk


# Can't do it, more time, managers on a card ---------------------------------------------


async def test_cant_do_it_from_the_card(dp, bot, company, member, sent_messages):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(
        assignee=worker, created_by=manager, due_at=timezone.now() + timedelta(hours=2)
    )
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.BLOCK, task.pk)))
    assert of(bot, EditMessageReplyMarkup)  # the reasons, in place
    await dp.feed_update(
        bot,
        updates.callback(tg, ReasonCallback(kind="block", task_id=task.pk, code="no_stock").pack()),
    )

    task = await reload(task)
    assert task.blocker == "no_stock" and task.next_reminder_at is None
    assert any("can't do this task" in m["text"] for m in sent_messages)

    # The giver answers from their card: someone else.
    other = await member.aregistered(company)
    boss = updates.tg_user(manager.user.telegram_id)
    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.REASSIGN, task.pk)))
    await dp.feed_update(
        bot, updates.callback(boss, PickCallback(task_id=task.pk, member_id=other.pk).pack())
    )
    task = await reload(task)
    assert task.assignee_id == other.pk and task.blocked_at is None


async def test_more_time_from_the_card(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    due = timezone.now() + timedelta(hours=1)
    task = await make_task(assignee=worker, created_by=manager, due_at=due)
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.MORE_TIME, task.pk)))
    await dp.feed_update(
        bot, updates.callback(tg, WhenCallback(kind="more", task_id=task.pk, choice="1h").pack())
    )

    task = await reload(task)
    assert task.extension_until is not None and task.extension_until > due
    assert task.due_at == due  # until the giver says yes


async def test_a_manager_sets_a_new_time_from_the_card(dp, bot, company, member):
    """Audit B-9: a manager's card is not a dead end; the deadline moves from it."""
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    due = timezone.now() + timedelta(hours=1)
    task = await make_task(assignee=worker, created_by=manager, due_at=due)
    boss = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.OPEN, task.pk)))
    actions = actions_of(of(bot, EditMessageText)[-1].reply_markup)
    assert TaskAction.NEW_DUE in actions and TaskAction.NUDGE in actions

    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.NEW_DUE, task.pk)))
    await dp.feed_update(
        bot, updates.callback(boss, WhenCallback(kind="due", task_id=task.pk, choice="1h").pack())
    )
    task = await reload(task)
    assert task.due_at > due


async def test_a_time_typed_while_the_choices_show_is_read(dp, bot, company, member):
    """Final review: typing "tomorrow 10:00" under the choices (without first) used to fall
    through to the home message and leave the deadline as it was."""
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    due = timezone.now() + timedelta(hours=1)
    task = await make_task(assignee=worker, created_by=manager, due_at=due)
    boss = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.NEW_DUE, task.pk)))
    await dp.feed_update(bot, updates.message(boss, "tomorrow 10:00"))

    task = await reload(task)
    tz = ZoneInfo(company.timezone)
    local = timezone.localtime(task.due_at, tz)
    # "tomorrow" after midnight is the coming morning (research R2), so only the hour is fixed
    assert (local.hour, local.minute) == (10, 0) and task.due_at > due
    assert of(bot, SendMessage)[-1].text == "New deadline set."


async def test_a_preset_after_the_choices_leaves_no_time_question_behind(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(
        assignee=worker, created_by=manager, due_at=timezone.now() + timedelta(hours=1)
    )
    boss = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.NEW_DUE, task.pk)))
    await dp.feed_update(
        bot, updates.callback(boss, WhenCallback(kind="due", task_id=task.pk, choice="1h").pack())
    )
    await dp.feed_update(bot, updates.message(boss, "Order insulin"))

    # The text is not read as a time any more ("I didn't catch the time")
    assert "didn't catch the time" not in (of(bot, SendMessage)[-1].text or "")


async def test_other_text_after_the_choices_is_not_trapped_as_a_time(dp, bot, company, member):
    """Choices opened and left alone: a new task typed later gets the usual "Add this as a
    task?", while after (asked to type a time) a non-time still asks again."""
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(
        assignee=worker, created_by=manager, due_at=timezone.now() + timedelta(hours=1)
    )
    boss = updates.tg_user(manager.user.telegram_id)

    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.NEW_DUE, task.pk)))
    await dp.feed_update(bot, updates.message(boss, "Order the insulin"))
    assert of(bot, SendMessage)[-1].text.startswith("Add this as a task?")

    # A reply to a task message under the open choices is still a comment.
    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.STOP)))
    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.NEW_DUE, task.pk)))
    card = TaskCallback(action=TaskAction.OPEN, task_id=task.pk).pack()
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Open", callback_data=card)]]
    )
    await dp.feed_update(bot, updates.reply(boss, "Call me first", markup))
    texts = [c async for c in TaskComment.objects.filter(task=task).values_list("text", flat=True)]
    assert texts == ["Call me first"]

    await dp.feed_update(bot, updates.callback(boss, press(TaskAction.STOP)))
    await dp.feed_update(
        bot, updates.callback(boss, WhenCallback(kind="due", task_id=task.pk, choice="type").pack())
    )
    await dp.feed_update(bot, updates.message(boss, "Order the insulin"))
    assert of(bot, SendMessage)[-1].text.startswith("I didn't catch the time.")


async def test_snooze_choices_in_place(dp, bot, company, member):
    worker = await member.aregistered(company)
    manager = await member.aregistered(company, "Manager")
    task = await make_task(
        assignee=worker, created_by=manager, due_at=timezone.now() - timedelta(minutes=5)
    )
    tg = updates.tg_user(worker.user.telegram_id)

    await dp.feed_update(bot, updates.callback(tg, press(TaskAction.SNOOZE_MENU, task.pk)))
    choices = of(bot, EditMessageReplyMarkup)[-1].reply_markup
    assert [b.text for b in choices.inline_keyboard[0]] == ["15 min", "1 hour"]

    await dp.feed_update(
        bot, updates.callback(tg, SnoozeCallback(task_id=task.pk, preset="15m").pack())
    )

    task = await reload(task)
    assert task.snooze_count == 1 and task.due_at < timezone.now()
    assert "the deadline stays" in answers(bot)[-1].text


# Failures still answer ------------------------------------------------------------------


async def test_a_failing_handler_still_answers_the_tap(dp, bot, company, member, monkeypatch):
    worker = await member.aregistered(company)
    task = await make_task(assignee=worker)

    def broken(*args, **kwargs):
        raise RuntimeError("database fell over")

    monkeypatch.setattr("apps.tasks.services.start_task", broken)
    await dp.feed_update(
        bot,
        updates.callback(
            updates.tg_user(worker.user.telegram_id), press(TaskAction.START, task.pk)
        ),
    )

    assert answers(bot)[-1].text == "Something went wrong. Please try again in a moment."
