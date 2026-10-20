from datetime import timedelta

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.companies.tests.factories import CompanyFactory
from apps.groups.models import GroupEvent
from apps.groups.tasks import POST_GAP, announce_task_done, post_to_group
from apps.groups.tests.factories import TelegramGroupFactory
from apps.members import services as member_services
from apps.members.models import Membership
from apps.members.tests.factories import MembershipFactory, PositionFactory
from apps.notifications import telegram
from apps.reminders.engine import send_due_reminders
from apps.reminders.policies import default_policy
from apps.tasks import services as task_services
from apps.tasks.models import Proof, Task
from apps.tasks.tests.factories import TaskFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def worker(company, member):
    return member.registered(company, first_name="Dilnoza", last_name="Karimova")


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager")


def posts(sent_messages, group) -> list[dict]:
    return [message for message in sent_messages if message["chat_id"] == group.chat_id]


def finished(worker, **fields) -> Task:
    now = timezone.now()
    fields = {
        "status": Task.Status.DONE,
        "completed_at": now,
        "due_at": now + timedelta(hours=1),
        "title": "Open the shop",
    } | fields
    return TaskFactory(assignee=worker, **fields)


def eagerly(task, *args):
    """Run a Celery task the way a worker would, retries included."""
    return task.apply(args=args, throw=False)


def test_finished_daily_work_is_posted_with_its_proof(
    company, other_company, worker, sent_messages, django_capture_on_commit_callbacks
):
    wants = TelegramGroupFactory(company=company, events=[GroupEvent.DAILY_DONE])
    assigned_only = TelegramGroupFactory(company=company, events=[GroupEvent.TASKS_DONE])
    switched_off = TelegramGroupFactory(
        company=company, events=[GroupEvent.DAILY_DONE], is_active=False
    )
    elsewhere = TelegramGroupFactory(company=other_company, events=[GroupEvent.DAILY_DONE])
    task = TaskFactory(
        assignee=worker,
        kind=Task.Kind.DAILY,
        title="Open the shop",
        proof=Proof.ANY,
        due_at=timezone.now() + timedelta(hours=1),
    )

    with django_capture_on_commit_callbacks(execute=True):
        task_services.complete_task(
            task, by=worker, proof_text="Shelves done", proof_photo=ContentFile(b"jpg", "a.jpg")
        )

    [post] = posts(sent_messages, wants)
    assert "Dilnoza Karimova" in post["text"]
    assert "Open the shop" in post["text"]
    assert "on time" in post["text"]
    assert "Shelves done" in post["text"]
    task.refresh_from_db()
    assert post["photo"] == task.proof_photo.name
    for group in (assigned_only, switched_off, elsewhere):
        assert not posts(sent_messages, group)


def test_finished_assigned_work_goes_to_groups_that_chose_it(
    company, worker, manager, sent_messages
):
    daily_only = TelegramGroupFactory(company=company, events=[GroupEvent.DAILY_DONE])
    wants = TelegramGroupFactory(company=company, events=[GroupEvent.TASKS_DONE])
    task = finished(worker, created_by=manager)

    announce_task_done(task.pk)

    assert len(posts(sent_messages, wants)) == 1
    assert not posts(sent_messages, daily_only)


def test_late_work_says_how_late(company, worker, manager, sent_messages):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.TASKS_DONE])
    task = finished(worker, created_by=manager, due_at=timezone.now() - timedelta(minutes=95))

    announce_task_done(task.pk)

    [post] = posts(sent_messages, group)
    assert "1 h 35 min late" in post["text"]


def test_work_waiting_for_a_check_says_so(company, worker, manager, sent_messages):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.TASKS_DONE])
    task = finished(worker, created_by=manager, status=Task.Status.REVIEW)

    announce_task_done(task.pk)

    [post] = posts(sent_messages, group)
    assert "Waiting for a check" in post["text"]


def test_personal_tasks_stay_personal(company, worker, sent_messages):
    TelegramGroupFactory(company=company, events=list(GroupEvent))
    task = finished(worker)

    announce_task_done(task.pk)

    assert sent_messages == []


def test_work_reopened_before_the_post_is_not_announced(company, worker, manager, sent_messages):
    TelegramGroupFactory(company=company, events=list(GroupEvent))
    task = finished(worker, created_by=manager, status=Task.Status.RETURNED, completed_at=None)

    announce_task_done(task.pk)

    assert sent_messages == []


def test_a_new_member_is_introduced(
    company, manager, sent_messages, django_capture_on_commit_callbacks
):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.MEMBERS])
    quiet = TelegramGroupFactory(company=company, events=[GroupEvent.DAILY_DONE])
    request = MembershipFactory(
        company=company,
        first_name="Aziz",
        last_name="Rahimov",
        position=PositionFactory(company=company, name="Cashier"),
    )

    with django_capture_on_commit_callbacks(execute=True):
        member_services.approve(request, by=manager.user)

    [post] = posts(sent_messages, group)
    assert "Aziz Rahimov" in post["text"]
    assert "Cashier" in post["text"]
    assert not posts(sent_messages, quiet)


def test_rejected_people_are_not_introduced(
    company, manager, sent_messages, django_capture_on_commit_callbacks
):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.MEMBERS])
    request = MembershipFactory(company=company, first_name="Aziz")

    with django_capture_on_commit_callbacks(execute=True):
        member_services.reject(request, by=manager.user)

    request.refresh_from_db()
    assert request.status == Membership.Status.REJECTED
    assert not posts(sent_messages, group)


def test_late_work_is_posted_once_when_the_manager_is_told(company, worker, manager, sent_messages):
    policy = default_policy(company.pk)
    policy.quiet_from = policy.quiet_until = None  # so the test runs at any hour
    policy.escalate_after = 2
    policy.save()
    group = TelegramGroupFactory(company=company, events=[GroupEvent.LATE])
    now = timezone.now()
    due = now - timedelta(minutes=45)
    TaskFactory(
        assignee=worker, created_by=manager, title="Cash report", due_at=due, next_reminder_at=due
    )

    send_due_reminders(now)  # the first reminder: only the worker hears
    assert not posts(sent_messages, group)

    send_due_reminders(now + timedelta(minutes=policy.repeat_every_minutes))  # escalation
    [post] = posts(sent_messages, group)
    assert "Dilnoza Karimova" in post["text"]
    assert "Cash report" in post["text"]

    send_due_reminders(now + timedelta(minutes=2 * policy.repeat_every_minutes))
    assert len(posts(sent_messages, group)) == 1


def test_a_group_that_removed_the_bot_is_switched_off(company, monkeypatch):
    group = TelegramGroupFactory(company=company)

    def kicked(bot, chat_id, text, reply_markup=None, photo=None):
        raise TelegramForbiddenError(SendMessage(chat_id=chat_id, text=text), "bot was kicked")

    monkeypatch.setattr(telegram, "send_message", kicked)

    eagerly(post_to_group, group.pk, "Hello")

    group.refresh_from_db()
    assert not group.is_active


def test_a_post_telegram_refuses_is_dropped(company, monkeypatch):
    group = TelegramGroupFactory(company=company)

    def muted(bot, chat_id, text, reply_markup=None, photo=None):
        raise TelegramBadRequest(SendMessage(chat_id=chat_id, text=text), "not enough rights")

    monkeypatch.setattr(telegram, "send_message", muted)

    result = eagerly(post_to_group, group.pk, "Hello")

    assert result.successful()
    group.refresh_from_db()
    assert group.is_active  # still linked: an admin may unmute the bot


def test_a_post_follows_a_group_upgraded_to_a_supergroup(company, monkeypatch, sent_messages):
    group = TelegramGroupFactory(company=company, chat_id=-555)
    record = telegram.send_message  # the recorder `sent_messages` installed

    def upgraded(bot, chat_id, text, reply_markup=None, photo=None):
        if chat_id == -555:
            raise TelegramMigrateToChat(
                SendMessage(chat_id=chat_id, text=text), "upgraded", -100_555
            )
        return record(bot, chat_id, text, reply_markup, photo)

    monkeypatch.setattr(telegram, "send_message", upgraded)

    eagerly(post_to_group, group.pk, "Hello")

    group.refresh_from_db()
    assert group.chat_id == -100_555
    assert [message["chat_id"] for message in sent_messages] == [-100_555]


def test_a_post_waits_out_telegrams_rate_limit(company, monkeypatch, sent_messages):
    group = TelegramGroupFactory(company=company)
    record = telegram.send_message
    calls = []

    def busy_once(bot, chat_id, text, reply_markup=None, photo=None):
        calls.append(chat_id)
        if len(calls) == 1:
            raise TelegramRetryAfter(SendMessage(chat_id=chat_id, text=text), "slow down", 3)
        return record(bot, chat_id, text, reply_markup, photo)

    monkeypatch.setattr(telegram, "send_message", busy_once)

    eagerly(post_to_group, group.pk, "Hello")

    assert len(calls) == 2
    assert len(sent_messages) == 1


def test_a_group_narrowed_to_positions_hears_only_about_them(company, member, sent_messages):
    cashier, cook = PositionFactory(company=company), PositionFactory(company=company)
    cashiers_group = TelegramGroupFactory(company=company, events=[GroupEvent.DAILY_DONE])
    cashiers_group.positions.add(cashier)
    everyone = TelegramGroupFactory(company=company, events=[GroupEvent.DAILY_DONE])
    for position in (cashier, cook, None):
        worker = member.registered(company, position=position)
        announce_task_done(finished(worker, kind=Task.Kind.DAILY).pk)

    assert len(posts(sent_messages, cashiers_group)) == 1
    assert len(posts(sent_messages, everyone)) == 3


def test_posts_to_one_group_are_spaced_out(company, worker, manager, monkeypatch):
    group = TelegramGroupFactory(company=company, events=[GroupEvent.TASKS_DONE])
    queued = []
    monkeypatch.setattr(
        post_to_group, "apply_async", lambda args, countdown: queued.append(countdown)
    )

    for _ in range(3):
        announce_task_done(finished(worker, created_by=manager).pk)

    assert queued[0] == pytest.approx(0, abs=1)
    assert queued[1] == pytest.approx(POST_GAP.total_seconds(), abs=1)
    assert queued[2] == pytest.approx(2 * POST_GAP.total_seconds(), abs=1)
    group.refresh_from_db()
    assert group.next_post_at > timezone.now() + 2 * POST_GAP


@pytest.mark.parametrize(
    ("language", "expected"),
    [("uz", "vazifasini bajardi"), ("ru", "выполнена"), ("en", "finished")],
)
def test_group_posts_are_in_the_companys_language(member, sent_messages, language, expected):
    company = CompanyFactory(default_language=language)
    manager = member.registered(company, "Manager", user__language="en")
    worker = member.registered(company, user__language="en")
    TelegramGroupFactory(company=company, events=[GroupEvent.TASKS_DONE])

    announce_task_done(finished(worker, created_by=manager).pk)

    [post] = sent_messages
    assert expected in post["text"]
