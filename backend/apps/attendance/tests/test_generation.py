"""Shifts generated from schedules: idempotent, never over manual or swapped shifts, no shifts on
holidays, leave for approved time off, nothing for suspended people."""

from datetime import time, timedelta

import pytest

from apps.attendance import services
from apps.attendance.models import WorkShift
from apps.attendance.tests.conftest import DAY, local
from apps.attendance.tests.factories import assign, shift_at, weekly_schedule
from apps.members.models import Membership
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db


@pytest.fixture
def planned(staff, freeze):
    freeze(local(DAY, 6, 0))
    schedule = weekly_schedule(staff.ali.company, days=range(6))  # Mon-Sat 09-18
    assign(staff.ali, schedule, DAY)
    return schedule


def _days(member):
    return sorted(
        WorkShift.objects.filter(membership=member)
        .exclude(status=WorkShift.Status.CANCELLED)
        .values_list("date", flat=True)
    )


def test_generation_is_idempotent_and_published(staff, planned):
    made = services.generate_shifts(staff.ali.company, days=6)
    assert made == 6  # Wed..Tue minus Sunday
    assert services.generate_shifts(staff.ali.company, days=6) == 0
    shifts = WorkShift.objects.filter(membership=staff.ali)
    assert shifts.count() == 6
    assert all(shift.published_at is not None for shift in shifts)
    first = shifts.order_by("date").first()
    assert first.source == WorkShift.Source.SCHEDULE
    assert first.branch == staff.ali.home_branch
    assert first.position == staff.ali.position
    assert (first.starts_at, first.ends_at) == (local(DAY, 9), local(DAY, 18))


def test_generation_never_overwrites_manual_swapped_or_cancelled_shifts(staff, planned):
    manual = shift_at(staff.ali, DAY, time(13, 0), time(22, 0))
    swapped = shift_at(staff.ali, DAY + timedelta(days=1), source=WorkShift.Source.SWAP)
    cancelled = shift_at(staff.ali, DAY + timedelta(days=2), status=WorkShift.Status.CANCELLED)
    services.generate_shifts(staff.ali.company, days=3)
    manual.refresh_from_db()
    assert (manual.starts_at, manual.source) == (local(DAY, 13), WorkShift.Source.MANUAL)
    assert WorkShift.objects.filter(membership=staff.ali, date=swapped.date).count() == 1
    # A shift a manager removed is not made again.
    assert (
        not WorkShift.objects.filter(membership=staff.ali, date=cancelled.date)
        .exclude(pk=cancelled.pk)
        .exists()
    )


def test_holidays_get_no_shifts(staff, planned):
    Holiday.objects.create(company=staff.ali.company, date=DAY + timedelta(days=1), name="Holiday")
    services.generate_shifts(staff.ali.company, days=2)
    assert DAY + timedelta(days=1) not in _days(staff.ali)


def test_time_off_makes_leave_shifts(staff, planned):
    time_off = TimeOff.objects.create(
        company=staff.ali.company,
        membership=staff.ali,
        first_day=DAY,
        last_day=DAY,
        status=TimeOff.Status.APPROVED,
    )
    services.generate_shifts(staff.ali.company, days=1)
    leave = WorkShift.objects.get(membership=staff.ali, date=DAY)
    assert (leave.status, leave.time_off) == (WorkShift.Status.LEAVE, time_off)


def test_suspended_people_get_no_shifts_while_suspended(staff, planned):
    staff.ali.status = Membership.Status.SUSPENDED
    staff.ali.suspended_until = DAY + timedelta(days=1)
    staff.ali.save()
    services.generate_shifts(staff.ali.company, days=3)  # Wed to Sat
    assert _days(staff.ali) == [DAY + timedelta(days=2), DAY + timedelta(days=3)]


def test_rotating_and_overnight_shifts(staff, freeze):
    freeze(local(DAY, 6, 0))
    company = staff.vali.company
    night = weekly_schedule(company, days=[2], starts=time(22, 0), ends=time(6, 0))
    assign(staff.vali, night, DAY)
    services.generate_shifts(company, days=0)
    shift = WorkShift.objects.get(membership=staff.vali)
    assert shift.date == DAY
    assert shift.ends_at == local(DAY + timedelta(days=1), 6)


def test_effective_from_is_respected(staff, freeze):
    freeze(local(DAY, 6, 0))
    schedule = weekly_schedule(staff.ali.company, days=range(7))
    assign(staff.ali, schedule, DAY + timedelta(days=2))
    services.generate_shifts(staff.ali.company, days=3)
    assert _days(staff.ali) == [DAY + timedelta(days=2), DAY + timedelta(days=3)]


def test_changing_a_schedule_regenerates_untouched_future_shifts(staff, planned):
    company = staff.ali.company
    services.generate_shifts(company, days=3)
    manual = WorkShift.objects.filter(membership=staff.ali, date=DAY + timedelta(days=1)).first()
    manual.source = WorkShift.Source.MANUAL
    manual.save()
    days = [
        {"weekday": d, "starts_at": time(10, 0), "ends_at": time(19, 0), "break_minutes": 60}
        for d in range(6)
    ]
    services.update_schedule(planned, by=staff.manager, days=days)
    regenerated = WorkShift.objects.get(membership=staff.ali, date=DAY + timedelta(days=2))
    assert regenerated.starts_at == local(DAY + timedelta(days=2), 10)
    manual.refresh_from_db()
    assert manual.starts_at == local(DAY + timedelta(days=1), 9)


def test_assigning_a_schedule_audits_and_generates(staff, freeze):
    from apps.audit.models import AuditLog

    freeze(local(DAY, 6, 0))
    company = staff.ali.company
    schedule = services.create_schedule(
        company,
        by=staff.manager,
        name="Morning",
        days=[{"weekday": 2, "starts_at": time(8, 0), "ends_at": time(17, 0), "break_minutes": 60}],
    )
    assert (
        services.assign_schedule(company, schedule, [staff.ali.pk, staff.vali.pk], by=staff.manager)
        == 2
    )
    assert WorkShift.objects.filter(date=DAY, membership__in=[staff.ali, staff.vali]).count() == 2
    assert AuditLog.objects.filter(action="attendance.schedule_assigned").exists()


def test_a_branch_lead_cannot_assign_people_of_another_branch(staff, planned):
    with pytest.raises(Exception, match="aren't in your team"):
        services.assign_schedule(staff.ali.company, planned, [staff.sara.pk], by=staff.lead)
