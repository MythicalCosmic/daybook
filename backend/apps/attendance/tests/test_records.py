"""Manager edits, excuses, overtime decisions and "I forgot to check in" corrections, all
audited."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied

from apps.attendance import services
from apps.attendance.models import AttendanceCorrection, AttendanceRecord
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import absent, shift_at
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db

YESTERDAY = DAY - timedelta(days=1)


@pytest.fixture(autouse=True)
def morning(freeze):
    return freeze(local(DAY, 10, 0))


@pytest.fixture
def worked(staff):
    shift = shift_at(staff.ali, YESTERDAY)
    services.update_settings(staff.ali.company, by=staff.manager, require_location=False)
    services.check_in(staff.ali, now=local(YESTERDAY, 8, 58))
    services.check_out(staff.ali, now=local(YESTERDAY, 18, 2))
    return AttendanceRecord.objects.get(shift=shift)


def test_manager_edit_is_audited_with_the_reason(staff, worked):
    record = services.edit_record(
        worked,
        by=staff.manager,
        check_out_at=local(YESTERDAY, 19, 30),
        reason="Stayed for inventory",
    )
    assert record.check_out_at == local(YESTERDAY, 19, 30)
    assert AttendanceRecord.Flag.EDITED in record.flags
    assert record.overtime_status == AttendanceRecord.Overtime.PENDING
    log = AuditLog.objects.get(action="attendance.record_edited")
    assert log.details["reason"] == "Stayed for inventory"
    assert "check_out_at" in log.details["changes"]


def test_edits_need_a_reason_a_manager_and_sane_times(staff, worked):
    with pytest.raises(DomainError, match="reason"):
        services.edit_record(worked, by=staff.manager, reason=" ")
    with pytest.raises(PermissionDenied):
        services.edit_record(worked, by=staff.accountant, reason="x", note="hi")
    with pytest.raises(DomainError, match="after the check-in"):
        services.edit_record(
            worked, by=staff.manager, check_out_at=local(YESTERDAY, 8, 0), reason="x"
        )


def test_a_branch_lead_cannot_touch_another_branch(staff):
    services.update_settings(staff.sara.company, by=staff.manager, require_location=False)
    services.check_in(staff.sara, now=local(DAY, 9, 0))
    record = AttendanceRecord.objects.get(membership=staff.sara)
    with pytest.raises(PermissionDenied):
        services.edit_record(record, by=staff.lead, note="x", reason="x")


def test_excuse_an_absence(staff):
    record = absent(shift_at(staff.ali, YESTERDAY))
    services.excuse(record, by=staff.manager, reason="Sick, will bring a note")
    record.refresh_from_db()
    assert record.status == AttendanceRecord.Status.EXCUSED
    assert AuditLog.objects.filter(action="attendance.record_excused").exists()


def test_overtime_decisions(staff, worked, django_capture_on_commit_callbacks):
    record = services.edit_record(
        worked, by=staff.manager, check_out_at=local(YESTERDAY, 20, 0), reason="r"
    )
    with django_capture_on_commit_callbacks(execute=True):
        services.decide_overtime(record, by=staff.manager, approve=True)
    record.refresh_from_db()
    assert record.overtime_status == AttendanceRecord.Overtime.APPROVED
    assert Notification.objects.filter(kind="attendance.decision", recipient=staff.ali).exists()
    with pytest.raises(DomainError, match="already been decided"):
        services.decide_overtime(record, by=staff.manager, approve=False, reason="no")


def test_correction_for_a_day_without_a_record(staff, django_capture_on_commit_callbacks):
    shift = shift_at(staff.ali, YESTERDAY)
    with django_capture_on_commit_callbacks(execute=True):
        correction = services.request_correction(
            staff.ali,
            date=YESTERDAY,
            check_in_at=local(YESTERDAY, 8, 55),
            check_out_at=local(YESTERDAY, 18, 5),
            reason="No internet in the stockroom",
        )
    copy = Notification.objects.get(kind="attendance.correction", recipient=staff.manager)
    assert copy.in_app is False and [a["key"] for a in copy.actions] == ["approve", "reject"]
    with django_capture_on_commit_callbacks(execute=True):
        services.decide_correction(correction, by=staff.manager, approve=True)
    record = AttendanceRecord.objects.get(membership=staff.ali)
    assert record.shift == shift
    assert record.status == AttendanceRecord.Status.CLOSED
    assert record.worked_minutes == 9 * 60 + 10 - 60
    assert AttendanceRecord.Flag.EDITED in record.flags
    assert AuditLog.objects.filter(action="attendance.correction_approved").exists()
    copy.refresh_from_db()
    assert copy.acted_at is not None  # the Telegram buttons are gone


def test_correction_fixes_a_forgotten_check_out(staff, worked):
    worked.status = AttendanceRecord.Status.AUTO_CLOSED
    worked.save()
    correction = services.request_correction(
        staff.ali, date=YESTERDAY, check_out_at=local(YESTERDAY, 18, 40), reason="Phone died"
    )
    assert correction.record == worked
    services.decide_correction(correction, by=staff.manager, approve=True)
    worked.refresh_from_db()
    assert (worked.status, worked.check_out_at) == (
        AttendanceRecord.Status.CLOSED,
        local(YESTERDAY, 18, 40),
    )


def test_correction_rules(staff, worked):
    with pytest.raises(DomainError, match="hasn't come"):
        services.request_correction(
            staff.ali, date=DAY + timedelta(days=1), check_in_at=local(DAY, 9), reason="x"
        )
    with pytest.raises(DomainError, match="too long ago"):
        services.request_correction(
            staff.ali, date=DAY - timedelta(days=40), check_in_at=local(DAY, 9), reason="x"
        )
    with pytest.raises(DomainError, match="both"):
        services.request_correction(
            staff.vali, date=YESTERDAY, check_in_at=local(YESTERDAY, 9), reason="x"
        )
    services.request_correction(
        staff.ali, date=YESTERDAY, check_out_at=local(YESTERDAY, 18, 30), reason="x"
    )
    with pytest.raises(DomainError, match="already asked"):
        services.request_correction(
            staff.ali, date=YESTERDAY, check_out_at=local(YESTERDAY, 18, 31), reason="y"
        )


def test_rejecting_a_correction_needs_a_reason(staff, worked, django_capture_on_commit_callbacks):
    correction = services.request_correction(
        staff.ali, date=YESTERDAY, check_out_at=local(YESTERDAY, 21, 0), reason="x"
    )
    with pytest.raises(DomainError, match="reason"):
        services.decide_correction(correction, by=staff.manager, approve=False)
    with django_capture_on_commit_callbacks(execute=True):
        services.decide_correction(
            correction, by=staff.manager, approve=False, reason="You left at 18:02"
        )
    correction.refresh_from_db()
    worked.refresh_from_db()
    assert correction.status == AttendanceCorrection.Status.REJECTED
    assert worked.check_out_at == local(YESTERDAY, 18, 2)
    told = Notification.objects.get(kind="attendance.decision", recipient=staff.ali)
    assert "rejected" in told.title


def test_manual_record_for_an_empty_day(staff):
    shift = shift_at(staff.ali, YESTERDAY)
    record = services.create_record(
        staff.ali.company,
        by=staff.manager,
        membership=staff.ali,
        date=YESTERDAY,
        check_in_at=local(YESTERDAY, 9, 0),
        check_out_at=local(YESTERDAY, 18, 0),
        reason="Forgot his phone",
    )
    assert record.shift == shift and record.in_source == AttendanceRecord.Source.MANUAL
    with pytest.raises(DomainError, match="already has a record"):
        services.create_record(
            staff.ali.company,
            by=staff.manager,
            membership=staff.ali,
            date=YESTERDAY,
            check_in_at=local(YESTERDAY, 9, 0),
            check_out_at=local(YESTERDAY, 18, 0),
            reason="again",
        )
