"""Time off recorded for someone (past days allowed) and revoked approved time off."""

from datetime import timedelta
from io import BytesIO

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.audit.models import AuditLog
from apps.companies.tests.factories import BranchFactory
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification
from apps.members.permissions import Perm
from apps.members.tests.factories import AccessRoleFactory
from apps.timeoff import services
from apps.timeoff.models import TimeOff
from apps.timeoff.signals import time_off_approved, time_off_cancelled

pytestmark = pytest.mark.django_db


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def manager(company, member):
    return member.registered(company, "Manager", first_name="Bekzod")


@pytest.fixture
def worker(company, member):
    worker = member.registered(company, first_name="Ali", last_name="Valiyev")
    branch = company.branches.first()
    worker.branches.set([branch])
    return worker


@pytest.fixture
def signals():
    seen = []

    def approved(sender, time_off, by, signal=None, **kwargs):
        seen.append(("approved", time_off.pk, kwargs))

    def cancelled(sender, time_off, by, signal=None, **kwargs):
        seen.append(("cancelled", time_off.pk, kwargs))

    time_off_approved.connect(approved, weak=False)
    time_off_cancelled.connect(cancelled, weak=False)
    yield seen
    time_off_approved.disconnect(approved)
    time_off_cancelled.disconnect(cancelled)


def jpeg() -> SimpleUploadedFile:
    out = BytesIO()
    Image.new("RGB", (40, 30), "white").save(out, "JPEG")
    return SimpleUploadedFile("note.jpg", out.getvalue(), content_type="image/jpeg")


def test_recording_sick_leave_in_the_past(
    worker, manager, today, signals, sent_messages, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        time_off = services.record_time_off(
            worker,
            by=manager,
            first_day=today - timedelta(days=5),
            last_day=today - timedelta(days=3),
            reason="Sick leave",
            attachment=jpeg(),
        )

    assert time_off.status == TimeOff.Status.APPROVED
    assert time_off.recorded_by == manager
    assert time_off.attachment.name.endswith(".jpg")
    assert AuditLog.objects.get(action="timeoff.recorded").target_id == time_off.pk
    assert signals == [("approved", time_off.pk, {})]
    [told] = [m for m in sent_messages if m["chat_id"] == worker.user.telegram_id]
    assert "recorded by Bekzod" in told["text"]
    assert Notification.objects.get(kind="timeoff.recorded").recipient == worker


def test_a_self_request_in_the_past_still_fails(worker, today):
    with pytest.raises(DomainError):
        services.request_time_off(
            worker, first_day=today - timedelta(days=1), last_day=today - timedelta(days=1)
        )


def test_recording_needs_the_permission_and_the_branch(company, member, worker, today):
    plain = member.registered(company)
    with pytest.raises(PermissionDenied):
        services.record_time_off(worker, by=plain, first_day=today, last_day=today)

    other = BranchFactory(company=company, name="Yunusobod")
    role = AccessRoleFactory(company=company, permissions=[Perm.TIME_OFF_APPROVE])
    far_manager = member.registered(company, role.name, home_branch=other)
    far_manager.branches.set([other])
    with pytest.raises(PermissionDenied):
        services.record_time_off(worker, by=far_manager, first_day=today, last_day=today)


def test_recording_limits(worker, manager, today, monkeypatch):
    with pytest.raises(DomainError):
        services.record_time_off(
            worker, by=manager, first_day=today - timedelta(days=400), last_day=today
        )
    services.record_time_off(worker, by=manager, first_day=today, last_day=today)
    with pytest.raises(DomainError, match="already has time off"):
        services.record_time_off(worker, by=manager, first_day=today, last_day=today)
    # Payroll finalized up to yesterday: nothing before today can be recorded.
    monkeypatch.setattr(services, "payroll_locked_until", lambda company: today - timedelta(days=1))
    with pytest.raises(DomainError, match="finalized"):
        services.record_time_off(
            worker,
            by=manager,
            first_day=today - timedelta(days=2),
            last_day=today - timedelta(days=2),
        )


def approved(worker, first, last):
    return TimeOff.objects.create(
        company=worker.company,
        membership=worker,
        first_day=first,
        last_day=last,
        status=TimeOff.Status.APPROVED,
    )


def test_revoking_before_it_starts_cancels_it(
    worker, manager, today, signals, django_capture_on_commit_callbacks
):
    time_off = approved(worker, today + timedelta(days=3), today + timedelta(days=5))

    with django_capture_on_commit_callbacks(execute=True):
        services.revoke(time_off, by=manager, reason="Inventory that week")

    time_off.refresh_from_db()
    assert time_off.status == TimeOff.Status.CANCELLED
    assert time_off.revoke_reason == "Inventory that week"
    [(kind, pk, extra)] = signals
    assert kind == "cancelled" and pk == time_off.pk
    assert extra["previous_status"] == TimeOff.Status.APPROVED
    assert (extra["cancelled_from"], extra["cancelled_to"]) == (
        today + timedelta(days=3),
        today + timedelta(days=5),
    )
    assert Notification.objects.get(kind="timeoff.revoked").recipient == worker


def test_revoking_once_started_shortens_it(worker, manager, today, signals):
    time_off = approved(worker, today - timedelta(days=2), today + timedelta(days=2))

    services.revoke(time_off, by=manager, reason="Needed back")

    time_off.refresh_from_db()
    assert time_off.status == TimeOff.Status.APPROVED
    assert time_off.last_day == today - timedelta(days=1)
    assert time_off.revoked_at is not None


def test_revoking_from_a_day_inside_it(
    worker, manager, today, signals, django_capture_on_commit_callbacks
):
    time_off = approved(worker, today + timedelta(days=1), today + timedelta(days=6))

    with django_capture_on_commit_callbacks(execute=True):
        services.revoke(
            time_off, by=manager, reason="Saturday shift", from_day=today + timedelta(days=4)
        )

    time_off.refresh_from_db()
    assert time_off.last_day == today + timedelta(days=3)
    assert signals[0][2]["cancelled_from"] == today + timedelta(days=4)


# Payroll's lock, read from package H's `payroll.queries.finalized_until` when it exists ---------


def test_without_payrolls_finalized_until_nothing_is_locked(worker, manager, today, monkeypatch):
    from apps.payroll import queries as payroll_queries

    monkeypatch.delattr(payroll_queries, "finalized_until", raising=False)

    assert services.payroll_locked_until(worker.company) is None
    long_ago = today - timedelta(days=60)
    services.record_time_off(worker, by=manager, first_day=long_ago, last_day=long_ago)
    started = approved(worker, today - timedelta(days=2), today + timedelta(days=2))
    services.revoke(started, by=manager, reason="Needed back", from_day=today - timedelta(days=1))


def test_payrolls_finalized_until_locks_recording_and_revoking(worker, manager, today, monkeypatch):
    from apps.payroll import queries as payroll_queries

    asked = []

    def finalized_until(company):
        asked.append(company.pk)
        return today - timedelta(days=5)

    monkeypatch.setattr(payroll_queries, "finalized_until", finalized_until, raising=False)

    assert services.payroll_locked_until(worker.company) == today - timedelta(days=5)
    with pytest.raises(DomainError, match="finalized"):
        services.record_time_off(
            worker, by=manager, first_day=today - timedelta(days=6), last_day=today
        )
    services.record_time_off(
        worker, by=manager, first_day=today - timedelta(days=4), last_day=today - timedelta(days=4)
    )
    started = approved(worker, today - timedelta(days=9), today + timedelta(days=2))
    with pytest.raises(DomainError, match="finalized"):
        services.revoke(started, by=manager, reason="x", from_day=today - timedelta(days=6))
    services.revoke(started, by=manager, reason="Needed back", from_day=today - timedelta(days=3))
    assert set(asked) == {worker.company_id}


def test_only_approved_time_off_can_be_revoked_and_a_reason_is_needed(worker, manager, today):
    pending = TimeOff.objects.create(
        company=worker.company, membership=worker, first_day=today, last_day=today
    )
    with pytest.raises(DomainError):
        services.revoke(pending, by=manager, reason="x")
    done = approved(worker, today + timedelta(days=9), today + timedelta(days=9))
    with pytest.raises(DomainError):
        services.revoke(done, by=manager, reason="  ")
