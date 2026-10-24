from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from django.utils import timezone

from apps.attendance.tests.factories import shift_at
from apps.notifications import telegram
from apps.reminders.engine import send_due_reminders
from apps.reminders.models import ReminderLog, ReminderText
from apps.reminders.policies import default_policy
from apps.tasks.callbacks import TaskAction, TaskCallback
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def noon():
    """Today at 12:00 in the company's timezone: well outside quiet hours."""
    today = timezone.localtime(timezone.now(), TASHKENT).date()
    return datetime.combine(today, time(12), tzinfo=TASHKENT)


@pytest.fixture
def worker(company, member):
    return member.registered(company)


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def late_task(worker, noon, **fields) -> Task:
    """A task whose deadline was a minute before noon, with its reminder scheduled."""
    due = noon - timedelta(minutes=1)
    fields.setdefault("created_by", worker)
    return TaskFactory(assignee=worker, due_at=due, next_reminder_at=due, **fields)


def to(sent_messages, member):
    return [m for m in sent_messages if m["chat_id"] == member.user.telegram_id]


def buttons(message) -> list[TaskAction]:
    rows = message["reply_markup"]["inline_keyboard"]
    return [TaskCallback.unpack(b["callback_data"]).action for row in rows for b in row]


def test_first_reminder_at_the_deadline(company, worker, manager, noon, sent_messages):
    task = late_task(worker, noon, created_by=manager, title="Stock count")

    assert send_due_reminders(noon) == 1

    [message] = to(sent_messages, worker)
    assert "Stock count" in message["text"]
    assert "was due at 11:59" in message["text"]
    assert buttons(message) == [TaskAction.DONE, TaskAction.SNOOZE_MENU, TaskAction.OPEN]
    task.refresh_from_db()
    assert task.reminders_sent == 1
    assert task.next_reminder_at == noon + timedelta(minutes=20)
    assert ReminderLog.objects.get(task=task).kind == ReminderLog.Kind.REMINDER


def test_nothing_goes_out_early(worker, noon, sent_messages):
    TaskFactory(
        assignee=worker,
        due_at=noon + timedelta(hours=1),
        next_reminder_at=noon + timedelta(hours=1),
    )

    assert send_due_reminders(noon) == 0
    assert sent_messages == []


def test_reminders_repeat_until_done(worker, manager, noon, sent_messages):
    task = late_task(worker, noon, created_by=manager)

    send_due_reminders(noon)
    send_due_reminders(noon + timedelta(minutes=10))  # not yet
    send_due_reminders(noon + timedelta(minutes=20))

    texts = [m["text"] for m in to(sent_messages, worker)]
    assert len(texts) == 2
    assert "Reminder 2" in texts[1]

    Task.objects.filter(pk=task.pk).update(status=Task.Status.DONE)
    assert send_due_reminders(noon + timedelta(hours=1)) == 0


def test_heads_up_before_the_deadline(company, worker, noon, sent_messages):
    policy = default_policy(company.pk)
    policy.heads_up_minutes = 30
    policy.save()
    due = noon + timedelta(minutes=20)
    task = TaskFactory(assignee=worker, due_at=due, next_reminder_at=due - timedelta(minutes=30))

    send_due_reminders(noon)

    [message] = sent_messages
    assert "Heads-up" in message["text"]
    assert TaskAction.SNOOZE not in buttons(message)
    task.refresh_from_db()
    assert task.reminders_sent == 0
    assert task.next_reminder_at == due


def test_quiet_hours_hold_reminders_until_morning(worker, noon, sent_messages):
    late_evening = noon.replace(hour=23)
    due = noon.replace(hour=18)  # day work, still open late at night
    task = TaskFactory(assignee=worker, due_at=due, next_reminder_at=late_evening)

    send_due_reminders(late_evening)

    assert sent_messages == []
    task.refresh_from_db()
    assert task.next_reminder_at == (late_evening + timedelta(days=1)).replace(hour=8, minute=0)


def test_a_task_due_inside_quiet_hours_is_night_work(worker, noon, sent_messages):
    """Research R2 P1: the night shift's 23:30 till check is reminded at 23:30, not at 08:00."""
    night = noon.replace(hour=23, minute=30)
    late_task(worker, night, title="Tungi kassa tekshiruvi")

    send_due_reminders(night)

    [message] = to(sent_messages, worker)
    assert "Tungi kassa tekshiruvi" in message["text"]


def test_on_shift_quiet_hours_dont_apply(company, worker, noon, sent_messages):
    """Research R1 N1: with attendance, quiet means off shift."""
    company.features = [*company.features, "attendance"]
    company.save(update_fields=["features"])
    night = noon.replace(hour=2)  # deep inside quiet hours
    shift_at(worker, night.date() - timedelta(days=1), time(20), time(8))
    task = TaskFactory(assignee=worker, due_at=noon.replace(hour=1), next_reminder_at=night)

    send_due_reminders(night)

    assert to(sent_messages, worker)
    task.refresh_from_db()
    assert task.reminders_sent == 1


def test_off_shift_waits_for_the_next_shift(company, worker, noon, sent_messages):
    company.features = [*company.features, "attendance"]
    company.save(update_fields=["features"])
    shift = shift_at(worker, noon.date(), time(14), time(22))  # starts later today
    task = late_task(worker, noon)

    send_due_reminders(noon)

    assert sent_messages == []
    task.refresh_from_db()
    assert task.next_reminder_at == shift.starts_at


def test_cant_do_it_keeps_reminders_quiet(worker, manager, noon, sent_messages):
    task = late_task(worker, noon, created_by=manager, blocked_at=noon, blocker="broken")

    assert send_due_reminders(noon) == 0
    task.refresh_from_db()
    assert task.next_reminder_at is None


def test_owner_text_is_for_readers_of_the_company_language(
    company, worker, manager, noon, sent_messages
):
    policy = default_policy(company.pk)
    ReminderText.objects.create(policy=policy, from_step=1, text="Iltimos, {task}!")
    worker.user.language = "ru"  # the company writes in English
    worker.user.save(update_fields=["language"])
    late_task(worker, noon, created_by=manager, title="Shelves")

    send_due_reminders(noon)

    [message] = to(sent_messages, worker)
    assert "Iltimos" not in message["text"]  # the built-in text, in Russian, instead


def test_manager_hears_after_the_third_reminder(worker, manager, noon, sent_messages):
    task = late_task(worker, noon, created_by=manager, title="Call the supplier")

    for minutes in (0, 20, 40, 60):
        send_due_reminders(noon + timedelta(minutes=minutes))

    reminders = to(sent_messages, worker)
    assert len(reminders) == 4
    assert f"{manager} has been told" in reminders[2]["text"]
    [escalation] = to(sent_messages, manager)
    assert str(worker) in escalation["text"]
    assert "Call the supplier" in escalation["text"]
    # The manager can act on it (audit B-9): remind now, give it to someone else, open it.
    assert buttons(escalation) == [TaskAction.NUDGE, TaskAction.REASSIGN, TaskAction.OPEN]
    task.refresh_from_db()
    assert task.escalated_at == noon + timedelta(minutes=40)


def test_daily_work_escalates_to_the_closest_checkers(company, member, worker, noon, sent_messages):
    """Audit X-11: the manager hears it's late; the owner isn't flooded with every routine."""
    manager = member.registered(company, "Manager")
    owner = member.registered(company, "Owner")
    task = late_task(worker, noon, kind=Task.Kind.DAILY)
    Task.objects.filter(pk=task.pk).update(reminders_sent=2)

    send_due_reminders(noon)

    assert len(to(sent_messages, manager)) == 1
    assert to(sent_messages, owner) == []


def test_named_contact_gets_the_late_alert(company, member, worker, manager, noon, sent_messages):
    shift_lead = member.registered(company)
    task = late_task(worker, noon, kind=Task.Kind.DAILY, escalate_to=shift_lead)
    Task.objects.filter(pk=task.pk).update(reminders_sent=2)

    send_due_reminders(noon)

    assert len(to(sent_messages, shift_lead)) == 1
    assert to(sent_messages, manager) == []


def test_personal_tasks_get_one_reminder(worker, manager, noon, sent_messages):
    task = late_task(worker, noon)  # created by the worker for themselves

    send_due_reminders(noon)

    task.refresh_from_db()
    assert task.next_reminder_at is None
    assert to(sent_messages, manager) == []


def test_cap_on_reminders(company, worker, manager, noon, sent_messages):
    policy = default_policy(company.pk)
    policy.max_reminders = 2
    policy.save()
    task = late_task(worker, noon, created_by=manager)

    send_due_reminders(noon)
    send_due_reminders(noon + timedelta(minutes=20))

    task.refresh_from_db()
    assert task.reminders_sent == 2
    assert task.next_reminder_at is None


def test_snooze_button_goes_away_when_none_are_left(worker, manager, noon, sent_messages):
    late_task(worker, noon, created_by=manager, snooze_count=1)

    send_due_reminders(noon)

    assert TaskAction.SNOOZE_MENU not in buttons(sent_messages[0])


def test_someone_who_blocked_the_bot_is_reported_once(
    worker, manager, noon, sent_messages, monkeypatch
):
    record = telegram.send_message

    def blocked_for_worker(bot, chat_id, text, reply_markup=None, photo=None):
        if chat_id == worker.user.telegram_id:
            raise TelegramForbiddenError(SendMessage(chat_id=chat_id, text=text), "bot was blocked")
        return record(bot, chat_id, text, reply_markup, photo)

    monkeypatch.setattr(telegram, "send_message", blocked_for_worker)
    first = late_task(worker, noon, created_by=manager, title="First")
    late_task(worker, noon, created_by=manager, title="Second")

    send_due_reminders(noon)

    [notice] = to(sent_messages, manager)
    assert "blocked the bot" in notice["text"]
    worker.user.refresh_from_db()
    assert worker.user.employee_bot_blocked_at == noon
    first.refresh_from_db()
    assert first.next_reminder_at == noon + timedelta(hours=1)


def test_owner_written_text_takes_over_from_its_step(company, worker, manager, noon, sent_messages):
    policy = default_policy(company.pk)
    ReminderText.objects.create(
        policy=policy, from_step=2, text="{name}, <hurry> with {task}! {late} late."
    )
    worker.first_name = "Ali"
    worker.save()
    late_task(worker, noon, created_by=manager, title="Shelves")

    send_due_reminders(noon)
    send_due_reminders(noon + timedelta(minutes=20))

    first, second = (m["text"] for m in to(sent_messages, worker))
    assert "was due at" in first
    assert second == "Ali, &lt;hurry&gt; with <b>Shelves</b>! 21 min late."


def test_previous_reminder_can_be_replaced(company, worker, manager, noon, monkeypatch):
    policy = default_policy(company.pk)
    policy.replace_previous = True
    policy.save()
    deleted, ids = [], iter([101, 102])
    monkeypatch.setattr(telegram, "send_message", lambda *args, **kwargs: next(ids))
    monkeypatch.setattr(
        telegram, "delete_message", lambda bot, chat, message: deleted.append(message)
    )
    late_task(worker, noon, created_by=manager)

    send_due_reminders(noon)
    send_due_reminders(noon + timedelta(minutes=20))

    assert deleted == [101]


def test_people_who_left_get_nothing(company, member, noon, sent_messages):
    from apps.members.models import Membership

    former = member.registered(company, status=Membership.Status.LEFT)
    task = late_task(former, noon, proof=Proof.NONE)

    send_due_reminders(noon)

    assert sent_messages == []
    task.refresh_from_db()
    assert task.next_reminder_at is None
