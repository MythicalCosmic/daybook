"""Check-in and check-out: shifts matched by window (overnight too), geofence distance and
flags against the shift's branch or the home branch, one record per double tap, the location
read only at the tap."""

import io
import threading
from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from PIL import Image

from apps.attendance import conf, services
from apps.attendance.models import AttendanceRecord, AttendanceSettings
from apps.attendance.tests.conftest import CHILONZOR, DAY, YUNUSOBOD, local
from apps.attendance.tests.factories import shift_at
from apps.core.exceptions import DomainError

pytestmark = pytest.mark.django_db

NEAR = (CHILONZOR[0] + Decimal("0.0003"), CHILONZOR[1])  # about 33 m away
FAR = (CHILONZOR[0] + Decimal("0.0108"), CHILONZOR[1])  # about 1.2 km away


def tap(member, when, point=NEAR, accuracy=15, **kwargs):
    return services.check_in(
        member, lat=point[0], lng=point[1], accuracy=accuracy, now=when, **kwargs
    )


def test_on_time_check_in_matches_the_shift(staff):
    shift = shift_at(staff.ali, DAY)
    result = tap(staff.ali, local(DAY, 8, 52))
    record = result.record
    assert result.created
    assert (record.shift, record.date, record.status) == (shift, DAY, AttendanceRecord.Status.OPEN)
    assert record.branch == shift.branch
    assert 25 < record.in_distance_m < 45
    assert record.flags == []
    assert not record.is_late


def test_late_check_in_beyond_the_grace(staff):
    shift_at(staff.ali, DAY)
    record = tap(staff.ali, local(DAY, 9, 25)).record
    assert record.is_late and record.late_minutes == 25


def test_overnight_shift_matches_by_window_not_calendar_day(staff):
    # Tuesday's night shift 22:00-06:00; a check-in early on Wednesday still belongs to it.
    tuesday = DAY - timedelta(days=1)
    night = shift_at(staff.ali, tuesday, time(22, 0), time(6, 0))
    shift_at(staff.ali, DAY, time(14, 0), time(22, 0))
    record = tap(staff.ali, local(DAY, 0, 40)).record
    assert record.shift == night
    assert record.date == tuesday
    assert record.is_late and record.late_minutes == 160


def test_early_check_in_belongs_to_the_coming_shift(staff):
    shift = shift_at(staff.ali, DAY, time(22, 0), time(6, 0))
    record = tap(staff.ali, local(DAY, 21, 10)).record
    assert record.shift == shift
    assert not record.is_late


def test_unscheduled_check_in_is_flagged(staff):
    record = tap(staff.ali, local(DAY, 11, 0)).record
    assert record.shift is None
    assert AttendanceRecord.Flag.UNSCHEDULED in record.flags
    assert record.branch == staff.ali.home_branch


def test_outside_the_geofence_is_flagged_and_managers_hear(
    staff, django_capture_on_commit_callbacks
):
    from apps.inbox.models import Notification

    shift_at(staff.ali, DAY)
    with django_capture_on_commit_callbacks(execute=True):
        result = tap(staff.ali, local(DAY, 8, 55), point=FAR)
    assert result.outside
    assert AttendanceRecord.Flag.OUTSIDE_GEOFENCE in result.record.flags
    assert 1100 < result.distance_m < 1300
    recipients = set(
        Notification.objects.filter(kind="attendance.outside").values_list(
            "recipient_id", flat=True
        )
    )
    assert staff.manager.pk in recipients and staff.lead.pk in recipients
    assert staff.ali.pk not in recipients


def test_reject_mode_refuses_outside(staff):
    shift_at(staff.ali, DAY)
    services.update_settings(
        staff.ali.company, by=staff.manager, outside_action=AttendanceSettings.OutsideAction.REJECT
    )
    with pytest.raises(DomainError, match="from Chilonzor"):
        tap(staff.ali, local(DAY, 8, 55), point=FAR)
    assert not AttendanceRecord.objects.exists()


def test_accuracy_gives_some_room_and_low_accuracy_is_marked(staff):
    shift_at(staff.ali, DAY)
    # 200 m away but the reading is only good to 80 m: not called outside.
    point = (CHILONZOR[0] + Decimal("0.0018"), CHILONZOR[1])
    record = tap(staff.ali, local(DAY, 8, 55), point=point, accuracy=80).record
    assert AttendanceRecord.Flag.OUTSIDE_GEOFENCE not in record.flags
    services.check_out(staff.ali, lat=point[0], lng=point[1], accuracy=600, now=local(DAY, 18, 0))
    record.refresh_from_db()
    assert AttendanceRecord.Flag.LOW_ACCURACY in record.flags


def test_geofence_uses_the_shifts_branch(staff, yunusobod):
    shift_at(staff.ali, DAY, branch=yunusobod)
    record = tap(staff.ali, local(DAY, 8, 55), point=YUNUSOBOD).record
    assert record.branch == yunusobod
    assert record.in_distance_m == 0


def test_location_is_required_by_default(staff):
    with pytest.raises(DomainError, match="location"):
        services.check_in(staff.ali, now=local(DAY, 9, 0))
    services.update_settings(staff.ali.company, by=staff.manager, require_location=False)
    record = services.check_in(staff.ali, now=local(DAY, 9, 0)).record
    assert AttendanceRecord.Flag.NO_LOCATION in record.flags


def test_selfie_is_required_when_asked_and_stored_privately(staff, settings):
    services.update_settings(staff.ali.company, by=staff.manager, require_photo=True)
    with pytest.raises(DomainError, match="selfie"):
        tap(staff.ali, local(DAY, 9, 0))
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(buffer, "PNG")
    buffer.seek(0)
    buffer.name = "me.png"
    record = tap(staff.ali, local(DAY, 9, 0), photo=buffer).record
    assert record.in_photo.name.startswith(f"attendance/selfies/{staff.ali.company_id}/")
    assert record.in_photo.name.endswith(".jpg")
    assert str(settings.PRIVATE_MEDIA_ROOT) in record.in_photo.path


def test_double_tap_makes_one_record(staff):
    shift_at(staff.ali, DAY)
    first = tap(staff.ali, local(DAY, 8, 55))
    second = tap(
        staff.ali,
        local(
            DAY,
            8,
            55,
        )
        + timedelta(seconds=20),
    )
    assert first.record.pk == second.record.pk
    assert not second.created
    assert AttendanceRecord.objects.filter(membership=staff.ali).count() == 1
    with pytest.raises(DomainError, match="already checked in"):
        tap(staff.ali, local(DAY, 9, 30))


@pytest.mark.django_db(transaction=True)
def test_concurrent_taps_make_one_record(staff):
    shift_at(staff.ali, DAY)
    results, errors = [], []

    def run():
        try:
            results.append(tap(staff.ali, local(DAY, 8, 55)).record.pk)
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert len(set(results)) == 1
    assert AttendanceRecord.objects.filter(membership=staff.ali).count() == 1


def test_check_out_closes_and_counts_overtime(staff, django_capture_on_commit_callbacks):
    from apps.inbox.models import Notification

    shift_at(staff.ali, DAY)
    tap(staff.ali, local(DAY, 8, 55))
    with django_capture_on_commit_callbacks(execute=True):
        result = services.check_out(
            staff.ali, lat=NEAR[0], lng=NEAR[1], accuracy=12, now=local(DAY, 19, 30)
        )
    record = result.record
    assert record.status == AttendanceRecord.Status.CLOSED
    assert record.worked_minutes == 10 * 60 + 35 - 60
    assert record.overtime_minutes == 95
    assert record.overtime_status == AttendanceRecord.Overtime.PENDING
    # Approvals live in Needs you: the Telegram copy is the only notification row.
    copy = Notification.objects.filter(kind="attendance.overtime", recipient=staff.manager).get()
    assert copy.in_app is False


def test_check_out_without_check_in_and_double_tap(staff):
    with pytest.raises(DomainError, match="haven't checked in"):
        services.check_out(staff.ali, lat=NEAR[0], lng=NEAR[1], now=local(DAY, 18, 0))
    shift_at(staff.ali, DAY)
    tap(staff.ali, local(DAY, 9, 0))
    first = services.check_out(staff.ali, lat=NEAR[0], lng=NEAR[1], now=local(DAY, 18, 0))
    again = services.check_out(staff.ali, lat=NEAR[0], lng=NEAR[1], now=local(DAY, 18, 1))
    assert first.record.pk == again.record.pk


def test_checking_in_again_during_the_shift_reopens_it(staff):
    shift_at(staff.ali, DAY)
    tap(staff.ali, local(DAY, 8, 58))
    services.check_out(staff.ali, lat=NEAR[0], lng=NEAR[1], now=local(DAY, 13, 0))
    again = tap(staff.ali, local(DAY, 13, 5)).record
    assert again.status == AttendanceRecord.Status.OPEN
    assert again.check_in_at == local(DAY, 8, 58)
    assert again.check_out_at is None
    assert AttendanceRecord.objects.filter(membership=staff.ali).count() == 1


def test_late_check_in_posts_to_attendance_groups(
    staff, django_capture_on_commit_callbacks, monkeypatch
):
    posted = []
    monkeypatch.setattr(
        "apps.groups.services.broadcast",
        lambda company_id, event, text, **kw: posted.append((event, text)),
    )
    shift_at(staff.ali, DAY)
    with django_capture_on_commit_callbacks(execute=True):
        tap(staff.ali, local(DAY, 9, 40))
    assert posted and posted[0][0] == "attendance"
    assert "Ali" in posted[0][1] and "40 min" in posted[0][1]


def test_suspended_people_cannot_check_in(staff):
    from apps.members.models import Membership

    staff.ali.status = Membership.Status.SUSPENDED
    staff.ali.save()
    with pytest.raises(DomainError, match="paused"):
        tap(staff.ali, local(DAY, 9, 0))


def test_module_off_refuses(staff):
    company = staff.ali.company
    company.features = []
    company.save()
    with pytest.raises(DomainError, match="switched on"):
        tap(staff.ali, local(DAY, 9, 0))


def test_location_is_kept_only_from_the_two_taps(staff):
    """No tracking: a record holds the check-in and check-out points and nothing else."""
    location_fields = {
        field.name
        for field in AttendanceRecord._meta.get_fields()
        if field.name.endswith(("_lat", "_lng", "accuracy_m"))
    }
    assert location_fields == {
        "in_lat",
        "in_lng",
        "in_accuracy_m",
        "out_lat",
        "out_lng",
        "out_accuracy_m",
    }
    assert conf.get_settings(staff.ali.company).require_location
