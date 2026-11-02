"""The golden numbers of docs/PLAN-OWNER.md §3.17 and §14.11, exact to the tiyin.

The §3.17 setup: Monday to Saturday workdays, Asia/Tashkent, the holiday of Thursday
1 October 2026, so October 2026 has S = 26 scheduled days and 5 200 000 so‘m a month is
200 000 a day. Employment dates and leave are patched with fixed values, like the plan says
(their real versions belong to packages G and L).
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from apps.attendance.models import AttendanceRecord
from apps.payroll import calculator, services
from apps.payroll.models import PayslipLine
from apps.payroll.tests.conftest import OCTOBER, TZ
from apps.timeoff.queries import LeaveDay, LeaveSummary

pytestmark = pytest.mark.django_db

Kind = PayslipLine.Kind
D = Decimal


@pytest.fixture
def hired(monkeypatch):
    """`hired({member: (first day, last day or None)})`: fixed employment dates."""
    dates = {}

    def employment_dates(company, member_ids):
        ids = set(member_ids)
        return {pk: span for pk, span in dates.items() if pk in ids}

    monkeypatch.setattr("apps.hr.queries.employment_dates", employment_dates)

    def set_dates(table):
        dates.update({member.pk: span for member, span in table.items()})

    return set_dates


@pytest.fixture
def on_leave(monkeypatch):
    """`on_leave(member, days, kind="sick", pay_percent=60, paid=True)`: fixed leave days."""
    table: dict[int, list[LeaveDay]] = {}

    def leave_summary(company, start, end, *, member_ids=None):
        return {
            pk: LeaveSummary(pk, tuple(day for day in days if start <= day.day <= end))
            for pk, days in table.items()
            if member_ids is None or pk in set(member_ids)
        }

    monkeypatch.setattr("apps.timeoff.queries.leave_summary", leave_summary)

    def add(member, days, *, kind="sick", pay_percent=60, paid=True):
        table.setdefault(member.pk, []).extend(
            LeaveDay(day, 1, kind, paid, pay_percent) for day in days
        )

    return add


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def record(
    member,
    day,
    start=(9, 0),
    end=(18, 0),
    *,
    worked=None,
    overtime=0,
    approved=True,
    status=AttendanceRecord.Status.CLOSED,
    late=0,
):
    """A checked-out attendance record from `start` to `end` local (an end before the start is
    the next morning)."""
    check_in = at(day, *start)
    check_out = at(day, *end)
    if check_out <= check_in:
        check_out += timedelta(days=1)
    minutes = int((check_out - check_in).total_seconds() // 60) if worked is None else worked
    return AttendanceRecord.objects.create(
        company=member.company,
        membership=member,
        date=day,
        status=status,
        check_in_at=check_in,
        check_out_at=check_out if status != AttendanceRecord.Status.OPEN else None,
        worked_minutes=minutes,
        overtime_minutes=overtime,
        overtime_status=(
            AttendanceRecord.Overtime.NONE
            if not overtime
            else AttendanceRecord.Overtime.APPROVED
            if approved
            else AttendanceRecord.Overtime.PENDING
        ),
        is_late=bool(late),
        late_minutes=late,
        branch=member.home_branch,
    )


def absent(member, day):
    return AttendanceRecord.objects.create(
        company=member.company,
        membership=member,
        date=day,
        status=AttendanceRecord.Status.ABSENT,
        branch=member.home_branch,
    )


def pay(member, amount="5200000", **fields):
    fields.setdefault("effective_from", date(2026, 1, 1))
    return services.set_pay(member, by=None, amount=D(amount), **fields)


def month(member, period=OCTOBER):
    inputs, people = calculator.gather(member.company, period)
    person = next(p for p in people if p.member_id == member.pk)
    return calculator.compute(person, inputs), inputs


def total(result, *kinds):
    return sum((line.amount for line in result.lines if not kinds or line.kind in kinds), D(0))


@pytest.fixture
def ali(shop, staff, hired):
    hired({staff.ali: (date(2025, 6, 1), None)})
    return staff.ali


class TestMonthlyProration:
    def test_full_month(self, ali):
        pay(ali)
        result, _inputs = month(ali)
        assert result.scheduled_days == 26 and result.paid_days == 26
        assert total(result) == D("5200000.00")
        assert [line.kind for line in result.lines] == [Kind.BASE]

    def test_hired_thursday_15_october(self, shop, staff, hired):
        hired({staff.vali: (date(2026, 10, 15), None)})
        pay(staff.vali)
        result, _inputs = month(staff.vali)
        assert total(result) == D("3000000.00")
        assert result.paid_days == 15
        not_employed = next(line for line in result.lines if line.kind == Kind.PRORATION)
        assert not_employed.params["code"] == "not_employed"
        assert not_employed.quantity == 11 and not_employed.amount == D("-2200000.00")

    def test_hired_15_october_with_a_setup_from_that_day(self, shop, staff, hired):
        hired({staff.vali: (date(2026, 10, 15), None)})
        pay(staff.vali, effective_from=date(2026, 10, 15))
        result, _inputs = month(staff.vali)
        assert total(result) == D("3000000.00")
        assert [line.kind for line in result.lines] == [Kind.BASE]

    def test_two_unpaid_absences(self, ali):
        pay(ali)
        absent(ali, date(2026, 10, 5))
        absent(ali, date(2026, 10, 6))
        result, _inputs = month(ali)
        assert result.paid_days == 24 and result.absent_days == 2
        assert total(result) == D("4800000.00")

    def test_three_sick_days_at_60_percent(self, ali, on_leave):
        pay(ali)
        on_leave(ali, [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14)])
        result, _inputs = month(ali)
        assert total(result) == D("4960000.00")
        sick = next(line for line in result.lines if line.params.get("code") == "partial_leave")
        assert sick.amount == D("-240000.00") and sick.quantity == 3
        assert result.paid_leave_days == 3

    def test_unpaid_leave_and_holidays_are_never_deducted(self, ali, on_leave):
        pay(ali)
        on_leave(ali, [date(2026, 10, 1), date(2026, 10, 2)], kind="unpaid", paid=False)
        result, _inputs = month(ali)
        # 1 October is a holiday: only the 2nd comes off.
        assert total(result) == D("5000000.00")
        assert result.unpaid_leave_days == 1

    def test_calendar_proration(self, shop, staff, hired):
        hired({staff.vali: (date(2026, 10, 15), None)})
        pay(staff.vali, proration="calendar")
        result, _inputs = month(staff.vali)
        base = total(result, Kind.BASE)
        assert base == D("2851612.90")  # 5 200 000 x 17 / 31
        assert total(result) == D("2852000.00")  # rounded to 1 000 at the end
        assert total(result, Kind.ROUNDING) == D("387.10")

    def test_no_proration(self, shop, staff, hired):
        hired({staff.vali: (date(2026, 10, 30), None)})
        pay(staff.vali, proration="none")
        result, _inputs = month(staff.vali)
        assert total(result) == D("5200000.00")

    def test_a_raise_in_the_middle_of_the_month(self, ali):
        pay(ali)
        pay(ali, amount="6500000", effective_from=date(2026, 10, 15))
        result, _inputs = month(ali)
        bases = [line for line in result.lines if line.kind == Kind.BASE]
        # 11 working days at 5 200 000 / 26, 15 at 6 500 000 / 26.
        assert [line.amount for line in bases] == [D("2200000.00"), D("3750000.00")]
        assert total(result) == D("5950000.00")

    def test_rounding_happens_once_at_the_end(self, ali):
        pay(ali, amount="4500000")
        absent(ali, date(2026, 10, 5))
        result, _inputs = month(ali)
        assert total(result, Kind.PRORATION) == D("-173076.92")
        assert total(result, Kind.ROUNDING) == D("76.92")
        assert total(result) == D("4327000.00")


class TestExtras:
    def test_holiday_work_pays_double_on_top(self, ali):
        pay(ali)
        record(ali, date(2026, 10, 1))
        result, _inputs = month(ali)
        holiday = next(line for line in result.lines if line.kind == Kind.HOLIDAY_WORK)
        assert holiday.amount == D("400000.00")
        assert total(result) == D("5600000.00")

    def test_approved_overtime_only(self, ali):
        pay(ali)
        record(ali, date(2026, 10, 12), (9, 0), (22, 0), overtime=240)
        record(ali, date(2026, 10, 13), (9, 0), (22, 0), overtime=240, approved=False)
        result, _inputs = month(ali)
        overtime = next(line for line in result.lines if line.kind == Kind.OVERTIME)
        # 4 h x 25 000 (5 200 000 / (26 x 8)) x 2.
        assert overtime.amount == D("200000.00") and overtime.rate == D("25000.00")
        assert result.overtime_minutes == 240

    def test_no_overtime_for_someone_not_eligible(self, ali):
        pay(ali, overtime_eligible=False)
        record(ali, date(2026, 10, 12), (9, 0), (22, 0), overtime=240)
        result, _inputs = month(ali)
        assert not [line for line in result.lines if line.kind == Kind.OVERTIME]


class TestNightWork:
    """§14.11: monthly 5 200 000, S = 26, daily_hours 8 → hourly 25 000; 4 night shifts with
    8 night hours each = 32 h → 0.5 x 25 000 x 32 = 400 000."""

    def test_monthly_night_premium(self, ali):
        pay(ali)
        for day in (5, 6, 7, 8):
            record(ali, date(2026, 10, day), (22, 0), (6, 0))
        result, _inputs = month(ali)
        night = next(line for line in result.lines if line.kind == Kind.NIGHT_WORK)
        assert night.amount == D("400000.00")
        assert night.quantity == D("32.00") and night.rate == D("25000.00")
        assert result.night_minutes == 32 * 60
        assert total(result) == D("5600000.00")

    def test_hourly_night_premium_on_top_of_the_hours(self, ali):
        pay(ali, amount="25000", pay_type="hourly")
        for day in (5, 6, 7, 8):
            record(ali, date(2026, 10, day), (20, 0), (8, 0))
        result, _inputs = month(ali)
        assert total(result, Kind.BASE) == D("1200000.00")  # 48 h x 25 000
        assert total(result, Kind.NIGHT_WORK) == D("400000.00")

    def test_a_20_to_08_record_counts_8_night_hours_even_across_a_month_end(self, ali):
        pay(ali)
        record(ali, date(2026, 10, 31), (20, 0), (8, 0))
        result, _inputs = month(ali)
        assert result.night_minutes == 8 * 60
        november, _ = month(ali, date(2026, 11, 1))
        assert november.night_minutes == 0

    def test_night_minutes(self):
        night = calculator.night_minutes
        assert (
            night(at(date(2026, 10, 5), 20), at(date(2026, 10, 6), 8), TZ, time(22), time(6)) == 480
        )
        assert (
            night(at(date(2026, 10, 5), 5), at(date(2026, 10, 5), 9), TZ, time(22), time(6)) == 60
        )
        assert (
            night(at(date(2026, 10, 5), 9), at(date(2026, 10, 5), 18), TZ, time(22), time(6)) == 0
        )

    def test_no_premium_without_attendance_records(self, ali):
        pay(ali)
        result, _inputs = month(ali)
        assert not [line for line in result.lines if line.kind == Kind.NIGHT_WORK]

    def test_an_open_record_has_no_night_hours_yet(self, ali):
        pay(ali)
        record(ali, date(2026, 10, 5), (22, 0), (6, 0), status=AttendanceRecord.Status.OPEN)
        result, _inputs = month(ali)
        assert result.night_minutes == 0


class TestDailyAndHourly:
    def test_daily_earner(self, ali, on_leave):
        pay(ali, amount="200000", pay_type="daily")
        for day in (5, 6, 7):
            record(ali, date(2026, 10, day))
        on_leave(ali, [date(2026, 10, 12), date(2026, 10, 13)], kind="annual", pay_percent=100)
        result, _inputs = month(ali)
        assert total(result, Kind.BASE) == D("600000.00")
        assert total(result, Kind.LEAVE_COMPENSATION) == D("400000.00")

    def test_hourly_earner_unapproved_overtime_is_not_paid(self, ali):
        pay(ali, amount="25000", pay_type="hourly")
        record(ali, date(2026, 10, 5), (9, 0), (19, 0), worked=600, overtime=120, approved=False)
        result, _inputs = month(ali)
        assert total(result, Kind.BASE) == D("200000.00")  # 8 h, not 10


class TestUsd:
    def test_dollar_pay_at_the_run_rate(self, ali):
        pay(ali, amount="1000", currency="USD")
        inputs, people = calculator.gather(ali.company, OCTOBER, usd_rate=D("12650"))
        result = calculator.compute(people[0], inputs)
        assert total(result) == D("12650000.00")
        base = result.lines[0]
        assert base.params["original"] == "1000.00" and base.params["usd_rate"] == "12650.00"

    def test_without_a_rate_there_is_no_payslip_line(self, ali):
        pay(ali, amount="1000", currency="USD")
        result, _inputs = month(ali)
        assert result.lines == [] and result.warnings[0]["code"] == "no_usd_rate"
