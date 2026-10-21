"""Pure rules of attendance: what a schedule plans for a day, and the minutes a record earns.

Nothing here writes to the database; services, jobs and queries share these functions.
"""

from dataclasses import dataclass
from datetime import date, time

from apps.attendance import clock
from apps.attendance.models import AttendanceRecord, AttendanceSettings, WorkSchedule

# A shift's break is deducted once someone worked longer than this.
BREAK_AFTER_MINUTES = 4 * 60
# A second tap this soon after the first is the same check-in or check-out.
DOUBLE_TAP_SECONDS = 120
# How long an unscheduled check-in may stay open before it is closed for the person.
UNSCHEDULED_AUTO_CLOSE_HOURS = 16
# "Still working?" is asked this long after the shift's end.
STILL_WORKING_AFTER_MINUTES = 60
# How far apart, at most, the coordinates a check-in may come with can be from the branch
# before the distance is called implausible (a fake or broken location): 2 000 km.
MAX_PLAUSIBLE_DISTANCE_M = 2_000_000


@dataclass(frozen=True)
class DayPlan:
    """The hours a schedule plans on one day."""

    starts_at: time
    ends_at: time
    break_minutes: int


def plan_for(schedule: WorkSchedule | None, day: date, weekly_days: dict | None = None):
    """What `schedule` plans on `day`: a `DayPlan`, or None for a day off (and always None for
    flexible or archived schedules). `weekly_days` ({weekday: WorkScheduleDay}) saves a query
    per call when the caller already has them."""
    if schedule is None or not schedule.is_active:
        return None
    if schedule.kind == WorkSchedule.Kind.WEEKLY:
        if weekly_days is None:
            weekly_days = {row.weekday: row for row in schedule.days.all()}
        row = weekly_days.get(day.weekday())
        return DayPlan(row.starts_at, row.ends_at, row.break_minutes) if row else None
    if schedule.kind == WorkSchedule.Kind.ROTATING:
        pattern = schedule.rotation
        if not (
            pattern
            and schedule.rotation_start
            and schedule.rotation_starts_at
            and schedule.rotation_ends_at
        ):
            return None
        index = (day - schedule.rotation_start).days % len(pattern)
        if pattern[index] != "W":
            return None
        return DayPlan(
            schedule.rotation_starts_at, schedule.rotation_ends_at, schedule.rotation_break_minutes
        )
    return None


def weekly_minutes(schedule: WorkSchedule) -> int:
    """Planned minutes in an average week (for the schedules list)."""
    if schedule.kind == WorkSchedule.Kind.WEEKLY:
        total = 0
        for row in schedule.days.all():
            total += _span(row.starts_at, row.ends_at) - row.break_minutes
        return max(0, total)
    if schedule.kind == WorkSchedule.Kind.ROTATING and schedule.rotation:
        if not (schedule.rotation_starts_at and schedule.rotation_ends_at):
            return 0
        per_day = (
            _span(schedule.rotation_starts_at, schedule.rotation_ends_at)
            - schedule.rotation_break_minutes
        )
        work = schedule.rotation.count("W")
        return max(0, round(per_day * work * 7 / len(schedule.rotation)))
    return 0


def _span(starts: time, ends: time) -> int:
    start = starts.hour * 60 + starts.minute
    end = ends.hour * 60 + ends.minute
    if end <= start:
        end += 24 * 60
    return end - start


def compute(record: AttendanceRecord, settings: AttendanceSettings) -> None:
    """Fill `record`'s late, early-leave, worked and overtime minutes from its times and shift.

    Lateness and early leave count only beyond their grace minutes (and then in full). The
    shift's break is deducted from a span of more than four hours. Overtime is worked time
    beyond the shift's planned minutes, from `overtime_after_minutes` on; it waits for
    approval unless already decided."""
    shift = record.shift
    record.late_minutes = 0
    record.is_late = False
    record.early_leave_minutes = 0
    record.worked_minutes = 0
    overtime = 0
    if record.check_in_at is not None:
        if shift is not None:
            delay = clock.minutes_between(shift.starts_at, record.check_in_at)
            if delay > settings.grace_minutes:
                record.late_minutes = delay
                record.is_late = True
        if record.check_out_at is not None:
            span = max(0, clock.minutes_between(record.check_in_at, record.check_out_at))
            pause = shift.break_minutes if shift is not None and span > BREAK_AFTER_MINUTES else 0
            record.worked_minutes = max(0, span - pause)
            if shift is not None:
                early = clock.minutes_between(record.check_out_at, shift.ends_at)
                if early > settings.early_leave_grace_minutes:
                    record.early_leave_minutes = early
                extra = record.worked_minutes - shift.minutes
                if extra >= max(1, settings.overtime_after_minutes):
                    overtime = extra
    record.overtime_minutes = overtime
    if overtime == 0:
        record.overtime_status = AttendanceRecord.Overtime.NONE
    elif record.overtime_status == AttendanceRecord.Overtime.NONE:
        record.overtime_status = AttendanceRecord.Overtime.PENDING


def add_flag(record: AttendanceRecord, flag: str) -> None:
    if flag not in record.flags:
        record.flags = [*record.flags, flag]


def drop_flag(record: AttendanceRecord, flag: str) -> None:
    if flag in record.flags:
        record.flags = [value for value in record.flags if value != flag]
