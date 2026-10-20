from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members.models import Membership
from apps.tasks.models import Task
from apps.tasks.tests.factories import TaskFactory
from apps.timeoff import services
from apps.timeoff.callbacks import TimeOffAction, TimeOffDecision
from apps.timeoff.models import TimeOff

pytestmark = pytest.mark.django_db

TASHKENT = ZoneInfo("Asia/Tashkent")


@pytest.fixture
def today():
    return timezone.localdate(timezone=TASHKENT)


@pytest.fixture
def worker(company, member):
    return member.registered(company, first_name="Ali", last_name="Valiyev")


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager", first_name="Mona")


def to(sent_messages, member) -> list[dict]:
    return [m for m in sent_messages if m["chat_id"] == member.user.telegram_id]


def test_a_request_goes_to_the_approvers(
    worker, manager, today, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        time_off = services.request_time_off(
            worker,
            first_day=today + timedelta(days=2),
            last_day=today + timedelta(days=4),
            reason="Wedding",
        )

    assert time_off.status == TimeOff.Status.PENDING
    assert time_off.days == 3
    [message] = to(sent_messages, manager)
    assert "Ali Valiyev" in message["text"]
    assert "Wedding" in message["text"]
    assert "days: 3" in message["text"]
    buttons = [b["callback_data"] for b in message["reply_markup"]["inline_keyboard"][0]]
    assert [TimeOffDecision.unpack(data).action for data in buttons] == [
        TimeOffAction.APPROVE,
        TimeOffAction.REJECT,
    ]
    assert not to(sent_messages, worker)


def test_people_who_approve_time_off_just_take_it(
    manager, today, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        time_off = services.request_time_off(manager, first_day=today, last_day=today)

    assert time_off.status == TimeOff.Status.APPROVED
    assert time_off.decided_by == manager.user
    assert sent_messages == []


@pytest.mark.parametrize(
    ("first", "last", "problem"),
    [
        (3, 2, "before the first"),
        (-1, 1, "in the past"),
        (0, 60, "at most 60 days"),
    ],
)
def test_impossible_requests_are_refused(worker, today, first, last, problem):
    with pytest.raises(DomainError, match=problem):
        services.request_time_off(
            worker, first_day=today + timedelta(days=first), last_day=today + timedelta(days=last)
        )


def test_the_same_days_cannot_be_asked_for_twice(worker, today):
    services.request_time_off(
        worker, first_day=today + timedelta(days=1), last_day=today + timedelta(days=3)
    )

    with pytest.raises(DomainError, match="already asked"):
        services.request_time_off(
            worker, first_day=today + timedelta(days=3), last_day=today + timedelta(days=5)
        )
    # Days next to it are fine.
    services.request_time_off(
        worker, first_day=today + timedelta(days=4), last_day=today + timedelta(days=5)
    )


def test_only_registered_members_ask(company, member, today):
    newcomer = member(company, status=Membership.Status.PENDING)

    with pytest.raises(DomainError):
        services.request_time_off(newcomer, first_day=today, last_day=today)


def test_approving_tells_the_person_and_is_logged(
    worker, manager, today, sent_messages, django_capture_on_commit_callbacks
):
    time_off = services.request_time_off(
        worker, first_day=today + timedelta(days=1), last_day=today + timedelta(days=1)
    )

    with django_capture_on_commit_callbacks(execute=True):
        services.decide(time_off.pk, True, by=manager.user)

    time_off.refresh_from_db()
    assert time_off.status == TimeOff.Status.APPROVED
    assert time_off.decided_by == manager.user
    [message] = to(sent_messages, worker)
    assert "approved" in message["text"]
    entry = AuditLog.objects.get()
    assert (entry.action, entry.actor) == (AuditLog.Action.TIME_OFF_APPROVED, manager.user)


def test_rejecting_tells_the_person(
    worker, manager, today, sent_messages, django_capture_on_commit_callbacks
):
    time_off = services.request_time_off(worker, first_day=today, last_day=today)

    with django_capture_on_commit_callbacks(execute=True):
        services.decide(time_off.pk, False, by=manager.user)

    [message] = to(sent_messages, worker)
    assert "declined" in message["text"]


def test_only_approvers_decide_and_only_once(company, member, worker, manager, today):
    time_off = services.request_time_off(worker, first_day=today, last_day=today)

    with pytest.raises(PermissionDenied):
        services.decide(time_off.pk, True, by=member.registered(company).user)
    services.decide(time_off.pk, True, by=manager.user)
    with pytest.raises(DomainError, match="already approved"):
        services.decide(time_off.pk, False, by=manager.user)


def test_nobody_decides_on_their_own_time_off(company, manager, today):
    time_off = TimeOff.objects.create(
        company=company, membership=manager, first_day=today, last_day=today
    )

    with pytest.raises(PermissionDenied):
        services.decide(time_off.pk, True, by=manager.user)


def test_approval_for_today_clears_todays_daily_tasks(company, worker, manager, today):
    noon = datetime.combine(today, time(12), tzinfo=TASHKENT)
    daily = TaskFactory(
        assignee=worker,
        created_by=manager,
        kind=Task.Kind.DAILY,
        due_at=noon,
        next_reminder_at=noon,
    )
    assigned = TaskFactory(assignee=worker, created_by=manager, due_at=noon)
    tomorrow = TaskFactory(
        assignee=worker, created_by=manager, kind=Task.Kind.DAILY, due_at=noon + timedelta(days=1)
    )
    time_off = services.request_time_off(worker, first_day=today, last_day=today)

    services.decide(time_off.pk, True, by=manager.user)

    daily.refresh_from_db()
    assert (daily.status, daily.next_reminder_at) == (Task.Status.CANCELLED, None)
    assigned.refresh_from_db()
    tomorrow.refresh_from_db()
    assert assigned.status == tomorrow.status == Task.Status.TODO  # a manager decides about these


def test_the_person_can_cancel_until_it_starts(worker, manager, today):
    pending = services.request_time_off(
        worker, first_day=today + timedelta(days=5), last_day=today + timedelta(days=5)
    )
    upcoming = services.request_time_off(
        worker, first_day=today + timedelta(days=1), last_day=today + timedelta(days=2)
    )
    started = services.request_time_off(worker, first_day=today, last_day=today)
    services.decide(upcoming.pk, True, by=manager.user)
    services.decide(started.pk, True, by=manager.user)

    with pytest.raises(PermissionDenied):
        services.cancel(pending, by=manager)
    assert services.cancel(pending, by=worker).status == TimeOff.Status.CANCELLED
    assert services.cancel(upcoming, by=worker).status == TimeOff.Status.CANCELLED
    with pytest.raises(DomainError, match="already started"):
        services.cancel(started, by=worker)
