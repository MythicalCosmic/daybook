"""The task-polish contracts (scratchpad briefs/tp-backlog.md): quick-add parsing over the API,
undo after Done, snooze choices, comments that reach people, "can't do it", "need more time",
"given by me", seen receipts, and the person who loses or keeps a task hearing about it."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.groups.tasks import announce_task_done
from apps.inbox.models import Notification
from apps.inbox.services import act_from_bot
from apps.tasks import services
from apps.tasks.models import Activity, Task
from apps.tasks.notifications import send_task_completed
from apps.tasks.tests.factories import TaskFactory, make_shop

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def shop(company, member):
    return make_shop(company, member)


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    """`with commit():` runs what the services queue for after their commit (the messages)."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


WEDNESDAY_10 = datetime(2026, 10, 21, 10, 0, tzinfo=TASHKENT)


@pytest.fixture
def wednesday_morning(monkeypatch):
    """The clock at a Wednesday 10:00 in Tashkent, so "ertaga" is always Thursday."""
    monkeypatch.setattr("django.utils.timezone.now", lambda: WEDNESDAY_10)


def given(shop, person=None, **fields):
    """Work the branch lead gave someone (the worker by default)."""
    person = person or shop.worker
    fields.setdefault("due_at", timezone.now() + timedelta(hours=3))
    return TaskFactory(assignee=person, created_by=shop.lead, branch=person.home_branch, **fields)


def employee_path(company, path):
    return f"/api/v1/companies/{company.pk}/tasks/{path}"


def owner_path(company, path):
    return f"/api/v1/owner/companies/{company.pk}/tasks/{path}"


def texts(sent, chat_id) -> list[str]:
    return [message["text"] for message in sent if message["chat_id"] == chat_id]


# Contract 1: quick add over the API --------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "label"),
    [("uz", "Ertaga"), ("ru", "Завтра"), ("en", "Tomorrow")],
)
def test_parse_reads_the_text_in_the_persons_language(
    shop, api_as, wednesday_morning, language, label
):
    shop.worker.user.language = language
    shop.worker.user.save(update_fields=["language"])
    before = Task.objects.count()

    response = api_as(shop.worker).post(
        employee_path(shop.company, "parse/"),
        {"text": "Kassani sanash ertaga 10:00!!"},
        format="json",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Kassani sanash"
    assert data["priority"] == "urgent"
    assert data["repeat"] is None and data["repeat_weekdays"] is None
    due = datetime.fromisoformat(data["due_at"]).astimezone(TASHKENT)
    local_now = timezone.localtime(timezone.now(), TASHKENT)
    assert due.date() == local_now.date() + timedelta(days=1) and due.hour == 10
    assert data["due_label"].startswith(f"{label}, ")
    assert data["due_label"].endswith("10:00")
    assert Task.objects.count() == before  # nothing saved


def test_parse_gives_the_repeat_and_its_days(shop, api_as):
    response = api_as(shop.worker).post(
        employee_path(shop.company, "parse/"),
        {"text": "Haftalik hisobot har dushanba soat 10 da"},
        format="json",
    )
    data = response.json()
    assert data["title"] == "Haftalik hisobot"
    assert data["repeat"] == "weekly" and data["repeat_weekdays"] == [0]


def test_parse_without_a_date_keeps_the_text(shop, api_as):
    response = api_as(shop.worker).post(
        employee_path(shop.company, "parse/"), {"text": "Vitrinani artish"}, format="json"
    )
    assert response.json() == {
        "title": "Vitrinani artish",
        "due_at": None,
        "due_label": None,
        "priority": None,
        "repeat": None,
        "repeat_weekdays": None,
    }


def test_the_owner_api_parses_too(shop, owner_api):
    response = owner_api(shop.owner).post(
        owner_path(shop.company, "parse/"), {"text": "Call supplier in 2 hours"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Call supplier"
    assert response.json()["due_at"] is not None


# Contract 2: undo after Done --------------------------------------------------------------


def test_done_can_be_undone_within_a_minute(shop):
    task = given(shop, needs_confirmation=True)
    services.start_task(task, by=shop.worker)
    services.complete_task(task, by=shop.worker)
    assert Activity.objects.filter(task=task, kind=Activity.Kind.REVIEW).exists()

    task = services.reopen_task(task, by=shop.worker)

    assert task.status == Task.Status.IN_PROGRESS
    assert task.completed_at is None
    assert task.next_reminder_at is not None
    # The checker's feed entry goes with the Done it was about.
    assert not Activity.objects.filter(task=task, kind=Activity.Kind.REVIEW).exists()


def test_undo_has_limits(shop):
    task = given(shop)
    services.complete_task(task, by=shop.worker)
    with pytest.raises(PermissionDenied):
        services.reopen_task(task, by=shop.colleague)
    Task.objects.filter(pk=task.pk).update(completed_at=timezone.now() - timedelta(seconds=61))
    with pytest.raises(DomainError, match="Too late"):
        services.reopen_task(task, by=shop.worker)
    checked = given(shop, needs_confirmation=True)
    services.complete_task(checked, by=shop.worker)
    services.confirm_task(checked, by=shop.lead)
    with pytest.raises(DomainError, match="accepted"):
        services.reopen_task(checked, by=shop.worker)
    with pytest.raises(DomainError):
        services.reopen_task(given(shop), by=shop.worker)  # not done at all


def test_reopen_over_the_api(shop, api_as):
    task = given(shop)
    services.complete_task(task, by=shop.worker)

    response = api_as(shop.worker).post(employee_path(shop.company, f"{task.pk}/reopen/"))

    assert response.status_code == 200
    assert response.json()["status"] == Task.Status.TODO


def test_news_of_an_undone_done_stays_quiet(shop, sent_messages, commit):
    """The reviewer's push and the group post are queued for after the undo window with the
    completion they're about; by then an undone task sends nothing."""
    task = given(shop, needs_confirmation=True)
    services.complete_task(task, by=shop.worker)
    stamp = Task.objects.get(pk=task.pk).completed_at.isoformat()
    services.reopen_task(task, by=shop.worker)
    sent_messages.clear()

    send_task_completed(task.pk, stamp)
    announce_task_done(task.pk, stamp)

    assert sent_messages == []
    # Done again later: the old job's stamp doesn't match the new completion either.
    services.complete_task(task, by=shop.worker)
    send_task_completed(task.pk, stamp)
    assert sent_messages == []


# Contract 3: snooze choices ----------------------------------------------------------------


def test_snooze_presets_hold_the_reminders_not_the_deadline(shop):
    due = timezone.now() - timedelta(minutes=10)
    task = given(shop, due_at=due, next_reminder_at=timezone.now())

    task = services.snooze_task(task, by=shop.worker, preset="15m")

    assert task.due_at == due
    assert timedelta(minutes=14) < task.snoozed_until - timezone.now() <= timedelta(minutes=15)
    assert task.next_reminder_at == task.snoozed_until
    assert task.snooze_count == 1


def test_a_snooze_never_brings_a_later_reminder_forward(shop):
    later = timezone.now() + timedelta(hours=2)
    task = given(shop, due_at=later + timedelta(hours=1), next_reminder_at=later)

    task = services.snooze_task(task, by=shop.worker, preset="15m")

    assert task.next_reminder_at == later


def test_tomorrow_morning_moves_ones_own_task(shop):
    task = TaskFactory(assignee=shop.worker, due_at=timezone.now() + timedelta(minutes=30))

    task = services.snooze_task(task, by=shop.worker, preset="tomorrow_morning")

    local = timezone.localtime(task.due_at, ZoneInfo(shop.company.timezone))
    assert (local.hour, local.minute) == (9, 0)
    assert task.snooze_count == 0
    with pytest.raises(DomainError, match="Ask for more time"):
        services.snooze_task(given(shop), by=shop.worker, preset="tomorrow_morning")
    with pytest.raises(DomainError):
        services.snooze_task(given(shop), by=shop.worker, preset="2d")


def test_snooze_over_the_api(shop, api_as):
    task = given(shop, due_at=timezone.now() - timedelta(minutes=5))
    client = api_as(shop.worker)

    response = client.post(
        employee_path(shop.company, f"{task.pk}/snooze/"), {"preset": "1h"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["snoozed_until"] is not None
    assert response.json()["due_at"] is not None
    bad = client.post(
        employee_path(shop.company, f"{task.pk}/snooze/"), {"preset": "nope"}, format="json"
    )
    assert bad.status_code == 400


# Contract 5: comments reach people ---------------------------------------------------------


def test_a_comment_reaches_the_people_on_the_task_but_not_its_author(shop, sent_messages, commit):
    task = given(shop)

    with commit():
        services.add_comment(task, by=shop.worker, text="Terminal cheki topilmayapti")

    assert texts(sent_messages, shop.lead.user.telegram_id)
    assert not texts(sent_messages, shop.worker.user.telegram_id)
    [message] = texts(sent_messages, shop.lead.user.telegram_id)
    assert "Terminal cheki topilmayapti" in message


def test_mentions_reach_branch_colleagues_and_are_checked(shop, member, sent_messages, commit):
    task = given(shop)
    neighbour = member.registered(shop.company, home_branch=shop.here)

    with commit():
        services.add_comment(
            task, by=shop.lead, text="Help Alisher, please", mentions=[neighbour.pk]
        )

    [message] = texts(sent_messages, neighbour.user.telegram_id)
    assert "mentioned you" in message
    assert Activity.objects.filter(recipient=neighbour, kind=Activity.Kind.COMMENTED).exists()
    with pytest.raises(DomainError, match="branch"):
        services.add_comment(task, by=shop.lead, text="?", mentions=[shop.colleague.pk])
    with pytest.raises(DomainError):
        services.add_comment(task, by=shop.lead, text="?", mentions=[999_999])


def test_comment_endpoints_take_mentions(shop, member, api_as, owner_api, sent_messages, commit):
    task = given(shop)
    neighbour = member.registered(shop.company, home_branch=shop.here)

    with commit():
        employee = api_as(shop.worker).post(
            employee_path(shop.company, f"{task.pk}/comments/"),
            {"text": "Can you help?", "mentions": [neighbour.pk]},
            format="json",
        )
    with commit():
        owner = owner_api(shop.owner).post(
            owner_path(shop.company, f"{task.pk}/comment/"),
            {"text": "On it", "mentions": [neighbour.pk]},
            format="json",
        )

    assert employee.status_code == 201 and owner.status_code == 201
    assert len(texts(sent_messages, neighbour.user.telegram_id)) == 2


# Contract 7: can't do it ------------------------------------------------------------------


def test_cant_do_it_pauses_reminders_and_tells_the_giver(shop, sent_messages, commit):
    task = given(shop, next_reminder_at=timezone.now())

    with commit():
        task = services.report_blocker(task, by=shop.worker, reason_code="no_stock", note="Tugagan")

    assert task.next_reminder_at is None
    assert task.blocker == "no_stock" and task.blocked_at is not None
    [message] = texts(sent_messages, shop.lead.user.telegram_id)
    assert "can't do this task" in message and "Tugagan" in message
    item = Notification.objects.get(kind="tasks.blocked", recipient=shop.lead)
    assert item.in_app and item.target_id == task.pk
    with pytest.raises(DomainError):
        services.snooze_task(task, by=shop.worker)  # nothing to snooze while it waits


def test_cant_do_it_needs_a_reason_and_shared_work(shop):
    with pytest.raises(DomainError):
        services.report_blocker(given(shop), by=shop.worker, reason_code="other")
    with pytest.raises(DomainError):
        services.report_blocker(given(shop), by=shop.worker, reason_code="tired")
    own = TaskFactory(assignee=shop.worker)
    with pytest.raises(DomainError, match="your own task"):
        services.report_blocker(own, by=shop.worker, reason_code="broken")


def test_a_new_time_answers_it(shop, sent_messages, commit):
    task = services.report_blocker(given(shop), by=shop.worker, reason_code="broken")
    new_due = timezone.now() + timedelta(days=1)
    sent_messages.clear()

    with commit():
        task = services.resolve_blocker(task, by=shop.lead, action="new_due", due_at=new_due)

    assert task.due_at == new_due and task.blocked_at is None
    assert task.next_reminder_at is not None
    assert Notification.objects.get(kind="tasks.blocked").acted_at is not None
    [message] = texts(sent_messages, shop.worker.user.telegram_id)
    assert "New deadline" in message


def test_someone_else_or_cancel_answer_it(shop, member, sent_messages, commit):
    neighbour = member.registered(shop.company, home_branch=shop.here)
    task = services.report_blocker(given(shop), by=shop.worker, reason_code="not_mine")

    with commit():
        task = services.resolve_blocker(
            task, by=shop.lead, action="reassign", assignee_id=neighbour.pk
        )

    assert task.assignee_id == neighbour.pk and task.blocked_at is None
    assert any(
        "someone else" in text for text in texts(sent_messages, shop.worker.user.telegram_id)
    )
    other = services.report_blocker(given(shop), by=shop.worker, reason_code="no_access")
    other = services.resolve_blocker(other, by=shop.lead, action="cancel")
    assert other.status == Task.Status.CANCELLED


def test_only_the_giver_or_a_manager_in_scope_answers(shop, member):
    task = services.report_blocker(given(shop), by=shop.worker, reason_code="broken")
    outsider_lead = member.registered(shop.company, "Branch lead", home_branch=shop.there)
    outsider_lead.branches.set([shop.there])
    for person in (shop.colleague, outsider_lead):
        with pytest.raises(PermissionDenied):
            services.resolve_blocker(task, by=person, action="cancel")
    assert services.resolve_blocker(task, by=shop.manager, action="cancel").status == "cancelled"


def test_blocker_endpoints(shop, api_as, owner_api):
    task = given(shop)
    report = api_as(shop.worker).post(
        employee_path(shop.company, f"{task.pk}/blocker/"),
        {"reason_code": "no_stock", "note": ""},
        format="json",
    )
    assert report.status_code == 200
    assert report.json()["blocker"]["reason_code"] == "no_stock"
    row = owner_api(shop.owner).get(owner_path(shop.company, "?blocked=true")).json()
    assert [item["id"] for item in row["results"]] == [task.pk]
    assert row["results"][0]["blocker"]["reason_code"] == "no_stock"
    twin = api_as(shop.lead).post(
        employee_path(shop.company, f"{task.pk}/blocker/resolve/"),
        {"action": "new_due", "due_at": (timezone.now() + timedelta(days=1)).isoformat()},
        format="json",
    )
    assert twin.status_code == 200 and twin.json()["blocker"] is None
    second = given(shop)
    services.report_blocker(second, by=shop.worker, reason_code="broken")
    owner = owner_api(shop.owner).post(
        owner_path(shop.company, f"{second.pk}/blocker/resolve/"),
        {"action": "cancel"},
        format="json",
    )
    assert owner.status_code == 200 and owner.json()["status"] == "cancelled"


# Contract 8: need more time ----------------------------------------------------------------


def test_more_time_is_asked_and_approved_in_the_inbox(shop, sent_messages, commit):
    task = given(shop)
    until = task.due_at + timedelta(hours=2)

    with commit():
        task = services.request_extension(task, by=shop.worker, until=until, note="Navbat bor")

    item = Notification.objects.get(kind="tasks.extension", recipient=shop.lead)
    assert [action["key"] for action in item.actions] == ["approve", "decline"]
    assert "Navbat bor" in item.body
    with commit():
        result = act_from_bot(item.pk, "approve", user=shop.lead.user)  # the bot's button
    assert result.ok
    task.refresh_from_db()
    assert task.due_at == until and task.extension_until is None
    assert any(
        "More time given" in text for text in texts(sent_messages, shop.worker.user.telegram_id)
    )


def test_declining_keeps_the_deadline(shop):
    task = given(shop)
    due = task.due_at
    services.request_extension(task, by=shop.worker, until=due + timedelta(hours=1))

    task = services.decide_extension(task, by=shop.lead, approve=False)

    assert task.due_at == due and task.extension_until is None
    assert Notification.objects.get(kind="tasks.extension").acted_at is not None


def test_more_time_has_rules(shop):
    task = given(shop)
    with pytest.raises(DomainError):
        services.request_extension(task, by=shop.worker, until=task.due_at - timedelta(minutes=5))
    with pytest.raises(DomainError):
        services.request_extension(task, by=shop.worker, until=task.due_at + timedelta(days=40))
    with pytest.raises(DomainError):
        services.request_extension(
            TaskFactory(assignee=shop.worker, due_at=timezone.now() + timedelta(hours=1)),
            by=shop.worker,
            until=timezone.now() + timedelta(hours=5),
        )
    services.request_extension(task, by=shop.worker, until=task.due_at + timedelta(hours=1))
    with pytest.raises(PermissionDenied):
        services.decide_extension(task, by=shop.colleague, approve=True)


def test_extension_endpoints(shop, api_as, owner_api):
    task = given(shop)
    until = (task.due_at + timedelta(hours=1)).isoformat()
    asked = api_as(shop.worker).post(
        employee_path(shop.company, f"{task.pk}/extension/"),
        {"until": until, "note": "Kassada navbat"},
        format="json",
    )
    assert asked.status_code == 200 and asked.json()["extension"]["note"] == "Kassada navbat"
    decided = owner_api(shop.owner).post(
        owner_path(shop.company, f"{task.pk}/extension/decide/"), {"approve": True}, format="json"
    )
    assert decided.status_code == 200 and decided.json()["extension"] is None
    second = given(shop)
    services.request_extension(second, by=shop.worker, until=second.due_at + timedelta(hours=1))
    twin = api_as(shop.lead).post(
        employee_path(shop.company, f"{second.pk}/extension/decide/"),
        {"approve": False},
        format="json",
    )
    assert twin.status_code == 200


# Contracts 9 and 10: given by me, seen -----------------------------------------------------


def test_given_by_me(shop, api_as):
    mine = given(shop)
    TaskFactory(assignee=shop.lead)  # the lead's own task
    response = api_as(shop.lead).get(employee_path(shop.company, "?given_by=me"))
    assert [row["id"] for row in response.json()["results"]] == [mine.pk]


def test_the_assignee_opening_it_marks_it_seen(shop, api_as, owner_api):
    task = given(shop)
    api_as(shop.lead).get(employee_path(shop.company, f"{task.pk}/"))
    task.refresh_from_db()
    assert task.seen_at is None  # the giver looking doesn't count

    response = api_as(shop.worker).get(employee_path(shop.company, f"{task.pk}/"))

    assert response.json()["seen_at"] is not None
    first = Task.objects.get(pk=task.pk).seen_at
    api_as(shop.worker).get(employee_path(shop.company, f"{task.pk}/"))
    assert Task.objects.get(pk=task.pk).seen_at == first  # the first time only
    row = owner_api(shop.owner).get(owner_path(shop.company, f"{task.pk}/")).json()
    assert row["seen_at"] is not None


# The person who loses or keeps a task hears (audit X-6) -----------------------------------


def test_a_moved_deadline_reaches_the_assignee(shop, sent_messages, commit):
    task = given(shop)
    with commit():
        services.update_task(task, by=shop.lead, due_at=timezone.now() + timedelta(days=2))
    [message] = texts(sent_messages, shop.worker.user.telegram_id)
    assert "New deadline" in message and "It was:" in message


def test_a_cancelled_task_reaches_the_assignee(shop, sent_messages, commit):
    with commit():
        services.cancel_task(given(shop), by=shop.lead)
    [message] = texts(sent_messages, shop.worker.user.telegram_id)
    assert "Task cancelled" in message


def test_the_person_who_loses_a_task_hears(shop, member, sent_messages, commit):
    neighbour = member.registered(shop.company, home_branch=shop.here)
    with commit():
        services.reassign_task(given(shop), by=shop.lead, assignee=neighbour)
    [message] = texts(sent_messages, shop.worker.user.telegram_id)
    assert "Given to someone else" in message
    assert texts(sent_messages, neighbour.user.telegram_id)  # and the new person gets it


def test_the_assignee_sees_why_and_by_whom_it_came_back(shop, api_as):
    task = given(shop, needs_confirmation=True)
    services.complete_task(task, by=shop.worker)
    services.return_task(task, by=shop.lead, reason="Retake it in daylight")
    services.add_comment(task, by=shop.worker, text="OK, after lunch")  # a later comment

    data = api_as(shop.worker).get(employee_path(shop.company, f"{task.pk}/")).json()

    assert data["returned_reason"] == "Retake it in daylight"
    assert data["returned_by"]["id"] == shop.lead.pk


def test_reminder_info_has_the_real_send_times(shop, api_as):
    from apps.reminders.models import ReminderLog

    task = given(shop, due_at=timezone.now() - timedelta(minutes=30))
    ReminderLog.objects.create(
        task=task, kind=ReminderLog.Kind.REMINDER, step=1, recipient=shop.worker
    )

    data = api_as(shop.worker).get(employee_path(shop.company, f"{task.pk}/")).json()

    assert len(data["reminder"]["sent_times"]) == 1
