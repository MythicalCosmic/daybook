"""The bot's task texts without emoji (the owner's rule, 25.10.2026): the status and priority in
words on the card, ticked steps and list entries that say what they are, page turns in words,
in every language the bot speaks."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone, translation

from apps.notifications.emoji import has_emoji
from apps.reminders import bot_messages as reminder_messages
from apps.reminders.policies import default_policy
from apps.tasks import bot_messages
from apps.tasks.models import ChecklistItem, Proof, Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def words(message) -> list[str]:
    """A message's text and the labels of its buttons."""
    text, markup = message
    rows = markup.inline_keyboard if markup is not None else []
    return [text, *(button.text for row in rows for button in row)]


def test_the_card_says_its_status_and_priority_in_words(worker, manager):
    now = timezone.now()
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        title="Front shelf",
        priority=Task.Priority.URGENT,
        due_at=now - timedelta(minutes=25),
    )

    lines = bot_messages.card_text(task, worker, now).splitlines()

    assert lines[0] == "<b>Front shelf</b>"
    assert "Status: To do" in lines
    assert "Priority: Urgent" in lines
    assert any(line.startswith("Due: ") and line.endswith("late by 25 min") for line in lines)


def test_nothing_drawn_for_a_task_has_an_emoji(company, worker, manager, settings):
    settings.EMPLOYEE_MINIAPP_URL = "https://app.example/app/"
    now = timezone.now()
    task = TaskFactory(
        assignee=worker,
        created_by=manager,
        title="Front shelf",
        priority=Task.Priority.URGENT,
        due_at=now - timedelta(minutes=25),
        proof=Proof.PHOTO,
        reward=Decimal("20000"),
        needs_confirmation=True,
    )
    ChecklistItem.objects.create(task=task, text="Old tags off", is_done=True)
    ChecklistItem.objects.create(task=task, text="New tags on", order=1)
    people = [worker, manager] * 5
    for language in ("uz", "ru", "en"):
        with translation.override(language):
            messages = [
                bot_messages.task_card(task, worker, now),
                bot_messages.task_card(task, manager, now),
                bot_messages.task_list([task], now, reviews=2),
                bot_messages.review_list([task], now),
                bot_messages.proof_prompt(task, worker, now),
                bot_messages.unticked_prompt(task, worker, now, 1),
                bot_messages.return_prompt(task, manager, now),
                bot_messages.task_assigned(task, now),
                bot_messages.comment_notice(task, "Tags ran out", manager, worker, False),
                bot_messages.quick_add_preview(
                    "Order insulin", "tomorrow, 18:00", found=True, urgent=True, repeat="Daily"
                ),
                ("", bot_messages.snooze_keyboard(task, worker)),
                ("", bot_messages.block_keyboard(task)),
                ("", bot_messages.when_keyboard(task, "more", now)),
                ("", bot_messages.cancel_keyboard(task)),
                ("", bot_messages.person_picker(people, task_id=task.pk, page=1)),
                reminder_messages.heads_up(task),
                reminder_messages.reminder(task, 1, default_policy(company.pk), now, "Boss"),
                reminder_messages.escalation(task, now, manager),
            ]
            for message in messages:
                for text in words(message):
                    assert not has_emoji(text), (language, text)


def test_list_entries_say_what_stands_out(worker):
    now = timezone.now()
    tasks = [
        TaskFactory(assignee=worker, title="Fridge log", status=Task.Status.RETURNED),
        TaskFactory(assignee=worker, title="Count the till", due_at=now - timedelta(hours=1)),
        TaskFactory(assignee=worker, title="Order insulin", priority=Task.Priority.URGENT),
        TaskFactory(assignee=worker, title="Price tags", status=Task.Status.REVIEW),
        TaskFactory(assignee=worker, title="Wipe the counter"),
    ]

    _text, markup = bot_messages.task_list(tasks, now)

    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert "Fridge log · sent back" in labels
    assert any(
        label.startswith("Count the till · ") and label.endswith(", late") for label in labels
    )
    assert "Order insulin · urgent" in labels
    assert "Price tags · being checked" in labels
    assert "Wipe the counter" in labels


def test_a_ticked_step_says_so_and_is_green(worker):
    task = TaskFactory(assignee=worker)
    ChecklistItem.objects.create(task=task, text="Old tags off", is_done=True)
    ChecklistItem.objects.create(task=task, text="New tags on", order=1)

    _text, markup = bot_messages.task_card(task, worker, timezone.now())

    steps = [(button.text, button.style) for [button] in markup.inline_keyboard[:2]]
    assert steps == [("Done: Old tags off", "success"), ("New tags on", None)]


def test_pages_turn_with_words(worker, manager):
    people = [worker, manager] * 5

    first = bot_messages.person_picker(people, task_id=7)
    second = bot_messages.person_picker(people, task_id=7, page=1)

    assert [button.text for button in first.inline_keyboard[-2]] == ["1/2", "Next"]
    assert [button.text for button in second.inline_keyboard[-2]] == ["Previous", "2/2"]
    assert second.inline_keyboard[-1][0].text == "Back"
