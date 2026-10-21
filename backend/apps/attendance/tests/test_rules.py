"""Pure rules: schedule plans, record minutes, geofence distance."""

from datetime import date, time, timedelta

import pytest

from apps.attendance import geo, rules
from apps.attendance.models import AttendanceRecord, AttendanceSettings, WorkSchedule
from apps.attendance.tests.conftest import CHILONZOR, DAY, YUNUSOBOD, local
from apps.attendance.tests.factories import WorkScheduleFactory, shift_at, weekly_schedule

pytestmark = pytest.mark.django_db


def test_weekly_plan_follows_the_weekday(shop):
    schedule = weekly_schedule(shop, days=[0, 2], starts=time(9, 0), ends=time(18, 0), pause=45)
    assert rules.plan_for(schedule, DAY) == rules.DayPlan(time(9, 0), time(18, 0), 45)  # Wed
    assert rules.plan_for(schedule, DAY + timedelta(days=1)) is None  # Thu


def test_rotation_counts_from_its_first_day(shop):
    schedule = WorkScheduleFactory(
        company=shop,
        kind=WorkSchedule.Kind.ROTATING,
        rotation="WWOO",
        rotation_start=date(2026, 10, 19),
        rotation_starts_at=time(9, 0),
        rotation_ends_at=time(21, 0),
    )
    planned = [rules.plan_for(schedule, date(2026, 10, 19) + timedelta(days=n)) for n in range(6)]
    assert [plan is not None for plan in planned] == [True, True, False, False, True, True]


def test_flexible_and_archived_schedules_plan_nothing(shop):
    flexible = WorkScheduleFactory(company=shop, kind=WorkSchedule.Kind.FLEXIBLE)
    archived = weekly_schedule(shop, is_active=False)
    assert rules.plan_for(flexible, DAY) is None
    assert rules.plan_for(archived, DAY) is None


def test_weekly_minutes(shop):
    schedule = weekly_schedule(shop, days=range(6), starts=time(9, 0), ends=time(18, 0), pause=60)
    assert rules.weekly_minutes(schedule) == 6 * 8 * 60
    night = weekly_schedule(shop, days=[5], starts=time(22, 0), ends=time(7, 0), pause=60)
    assert rules.weekly_minutes(night) == 8 * 60


def _record(shift, check_in, check_out=None):
    return AttendanceRecord(
        company=shift.company,
        membership=shift.membership,
        shift=shift,
        date=shift.date,
        check_in_at=check_in,
        check_out_at=check_out,
    )


def test_lateness_counts_only_beyond_the_grace(staff):
    settings = AttendanceSettings(grace_minutes=10)
    shift = shift_at(staff.ali, DAY)
    within = _record(shift, local(DAY, 9, 10))
    rules.compute(within, settings)
    assert (within.is_late, within.late_minutes) == (False, 0)
    beyond = _record(shift, local(DAY, 9, 11))
    rules.compute(beyond, settings)
    assert (beyond.is_late, beyond.late_minutes) == (True, 11)


def test_worked_minutes_leave_out_the_break_and_overtime_waits(staff):
    settings = AttendanceSettings(overtime_after_minutes=15, early_leave_grace_minutes=10)
    shift = shift_at(staff.ali, DAY, break_minutes=60)  # 8 h planned
    record = _record(shift, local(DAY, 8, 55), local(DAY, 19, 0))
    rules.compute(record, settings)
    assert record.worked_minutes == 10 * 60 + 5 - 60
    assert record.overtime_minutes == 65
    assert record.overtime_status == AttendanceRecord.Overtime.PENDING

    short = _record(shift, local(DAY, 9, 0), local(DAY, 18, 14))
    rules.compute(short, settings)
    assert short.overtime_minutes == 0
    assert short.overtime_status == AttendanceRecord.Overtime.NONE


def test_early_leave_and_short_days_keep_no_break(staff):
    settings = AttendanceSettings(early_leave_grace_minutes=10)
    shift = shift_at(staff.ali, DAY)
    record = _record(shift, local(DAY, 9, 0), local(DAY, 12, 0))
    rules.compute(record, settings)
    assert record.worked_minutes == 180  # under four hours: no break deducted
    assert record.early_leave_minutes == 6 * 60


def test_a_decided_overtime_keeps_its_decision(staff):
    settings = AttendanceSettings()
    shift = shift_at(staff.ali, DAY)
    record = _record(shift, local(DAY, 9, 0), local(DAY, 20, 0))
    record.overtime_status = AttendanceRecord.Overtime.APPROVED
    rules.compute(record, settings)
    assert record.overtime_status == AttendanceRecord.Overtime.APPROVED


def test_haversine_distance_between_the_branches():
    # Chilonzor to Yunusobod is a little under 12 km as the crow flies.
    meters = geo.distance_m(*CHILONZOR, *YUNUSOBOD)
    assert 11_000 < meters < 12_000
    assert geo.distance_m(*CHILONZOR, *CHILONZOR) == 0


def test_points_are_validated_and_rounded():
    assert geo.valid_point("41.2", "69.2")
    assert not geo.valid_point("91", "0")
    assert not geo.valid_point("x", "0")
    assert str(geo.coordinate("41.28568049")) == "41.285680"
