"""Attendance analytics (apps.attendance.analytics) with golden numbers.

The week of Monday 19 to Friday 23 October 2026, "now" Friday 12:00 in Tashkent. Shifts are
09:00-18:00 with an hour's break (480 planned minutes); 10 minutes of grace either side;
overtime from 15 minutes on.

    Ali  (Chilonzor, Sales)     Mon on time 08:55-18:05 (490) · Tue 20 min late 09:20-18:00 (460)
                                Wed absent · Thu on leave · Fri in at 08:50, still in (190 so far)
    Vali (Chilonzor, Sales)     Mon 09:05-17:30, 30 min early (445) · Tue 08:40-20:00 (620,
                                140 overtime) · Wed 45 min late 09:45-18:00 (435) · Thu no shift
                                · Fri not in yet (today isn't over: not counted)
    Sara (Yunusobod, none)      Mon, Tue 09:00-18:00 (480 each) · Wed marked absent · Thu 30 min
                                late 09:30-18:00 (450)
    Bob  (Chilonzor, Warehouse) Mon 08:58-18:00 (482) · Tue no shift, came 10:00-14:00 (240)
"""

from datetime import date, timedelta

import pytest

from apps.attendance import analytics, services
from apps.attendance.tests.conftest import local
from apps.attendance.tests.factories import absent, shift_at
from apps.members.models import Department
from apps.timeoff.models import Holiday, TimeOff

pytestmark = pytest.mark.django_db

MON = date(2026, 10, 19)
TUE, WED, THU, FRI = (MON + timedelta(days=n) for n in range(1, 5))
NOW = local(FRI, 12, 0)


def visit(member, day, came, left=None):
    services.check_in(member, now=local(day, *came), quiet=True)
    if left is not None:
        services.check_out(member, now=local(day, *left), quiet=True)


@pytest.fixture
def week(staff, chilonzor, yunusobod):
    company = staff.ali.company
    services.update_settings(company, by=None, require_location=False)
    sales = Department.objects.create(company=company, name="Sales")
    warehouse = Department.objects.create(company=company, name="Warehouse")
    for person, department in ((staff.ali, sales), (staff.vali, sales), (staff.bob, warehouse)):
        person.department = department
        person.save(update_fields=["department"])

    for day in (MON, TUE, WED, THU, FRI):
        shift_at(staff.ali, day, branch=chilonzor)
    for day in (MON, TUE, WED, FRI):
        shift_at(staff.vali, day, branch=chilonzor)
    sara = {day: shift_at(staff.sara, day, branch=yunusobod) for day in (MON, TUE, WED, THU)}
    shift_at(staff.bob, MON, branch=chilonzor)
    # A shift next week: after today, never counted.
    shift_at(staff.ali, MON + timedelta(days=7), branch=chilonzor)

    visit(staff.ali, MON, (8, 55), (18, 5))
    visit(staff.ali, TUE, (9, 20), (18, 0))
    TimeOff.objects.create(
        company=company,
        membership=staff.ali,
        first_day=THU,
        last_day=THU,
        status=TimeOff.Status.APPROVED,
    )
    visit(staff.ali, FRI, (8, 50))

    visit(staff.vali, MON, (9, 5), (17, 30))
    visit(staff.vali, TUE, (8, 40), (20, 0))
    visit(staff.vali, WED, (9, 45), (18, 0))

    visit(staff.sara, MON, (9, 0), (18, 0))
    visit(staff.sara, TUE, (9, 0), (18, 0))
    absent(sara[WED])
    visit(staff.sara, THU, (9, 30), (18, 0))

    visit(staff.bob, MON, (8, 58), (18, 0))
    visit(staff.bob, TUE, (10, 0), (14, 0))
    staff.sales, staff.warehouse = sales, warehouse
    return staff


def build(staff, *, branch_ids=None, end=FRI, **kwargs):
    return analytics.build(staff.ali.company, MON, end, branch_ids=branch_ids, now=NOW, **kwargs)


def rows_by_name(data):
    return {row["employee"]["name"].split()[0]: row for row in data["rows"]}


def test_each_person_gets_their_week(week):
    data = analytics.summary(build(week))

    rows = rows_by_name(data)
    assert list(rows) == ["Ali", "Bob", "Sara", "Vali"]  # by name; nobody without days
    ali = rows["Ali"]
    assert {key: ali[key] for key in ali if key != "employee"} == {
        "days_scheduled": 5,
        "days_present": 3,
        "days_absent": 1,
        "days_leave": 1,
        "days_excused": 0,
        "worked_minutes": 490 + 460 + 190,
        "late_count": 1,
        "late_minutes": 20,
        "early_leave_count": 0,
        "early_leave_minutes": 0,
        "overtime_minutes": 0,
        "arrivals": 3,
        "on_time": 2,
        "punctuality_percent": 66.7,
        "attendance_percent": 75.0,
    }
    vali = rows["Vali"]
    assert (vali["days_scheduled"], vali["days_present"], vali["days_absent"]) == (3, 3, 0)
    assert (vali["late_count"], vali["late_minutes"]) == (1, 45)
    assert (vali["early_leave_count"], vali["early_leave_minutes"]) == (1, 30)
    assert vali["overtime_minutes"] == 140
    assert vali["worked_minutes"] == 445 + 620 + 435
    assert vali["attendance_percent"] == 100.0
    sara = rows["Sara"]
    assert (sara["days_scheduled"], sara["days_present"], sara["days_absent"]) == (4, 3, 1)
    assert (sara["worked_minutes"], sara["late_minutes"]) == (1410, 30)
    bob = rows["Bob"]
    # The extra day without a shift counts as present, not as scheduled, and has no lateness.
    assert (bob["days_scheduled"], bob["days_present"], bob["arrivals"]) == (1, 2, 1)
    assert (bob["worked_minutes"], bob["punctuality_percent"]) == (482 + 240, 100.0)

    assert ali["employee"] == {
        "id": week.ali.pk,
        "name": week.ali.full_name,
        "photo_url": None,
        "position": {"id": week.cashier.pk, "name": "Cashier"},
        "department": {"id": week.sales.pk, "name": "Sales"},
        "branch": {"id": week.ali.home_branch_id, "name": "Chilonzor"},
    }
    assert data["range"] == {"from": "2026-10-19", "to": "2026-10-23"}
    assert data["counted_until"] == "2026-10-23"


def test_the_totals_add_up(week):
    totals = analytics.summary(build(week))["totals"]

    assert totals == {
        "people": 4,
        "days_scheduled": 13,
        "days_present": 11,
        "days_absent": 2,
        "days_leave": 1,
        "days_excused": 0,
        "worked_minutes": 1140 + 1500 + 1410 + 722,
        "late_count": 3,
        "late_minutes": 95,
        "early_leave_count": 1,
        "early_leave_minutes": 30,
        "overtime_minutes": 140,
        "arrivals": 10,
        "on_time": 7,
        "punctuality_percent": 70.0,
        "attendance_percent": 83.3,
    }


def test_branches_and_departments(week, chilonzor, yunusobod):
    report = build(week)

    branches = analytics.branches(report)["rows"]
    assert [(row["branch"]["name"], row["people"]) for row in branches] == [
        ("Chilonzor", 3),
        ("Yunusobod", 1),
    ]
    chl = branches[0]
    assert (chl["days_scheduled"], chl["days_present"], chl["days_absent"]) == (9, 8, 1)
    assert (chl["late_count"], chl["late_minutes"], chl["punctuality_percent"]) == (2, 65, 71.4)
    assert chl["attendance_percent"] == 87.5
    assert branches[1]["branch"] == {"id": yunusobod.pk, "name": "Yunusobod", "code": "YNS"}

    departments = analytics.departments(report)["rows"]
    assert [
        (row["department"] and row["department"]["name"], row["people"]) for row in departments
    ] == [
        ("Sales", 2),
        ("Warehouse", 1),
        (None, 1),  # people without a department last
    ]
    sales = departments[0]
    assert (sales["days_scheduled"], sales["days_present"], sales["worked_minutes"]) == (8, 6, 2640)
    assert (sales["punctuality_percent"], sales["attendance_percent"]) == (66.7, 85.7)


def test_the_daily_trend(week):
    days = analytics.trend(build(week))["days"]

    assert [
        (d["date"][8:], d["scheduled"], d["present"], d["late"], d["absent"], d["leave"])
        for d in days
    ] == [
        ("19", 4, 4, 0, 0, 0),
        ("20", 3, 4, 1, 0, 0),
        ("21", 3, 1, 1, 2, 0),
        ("22", 2, 1, 1, 0, 1),
        ("23", 1, 1, 0, 0, 0),  # today: Ali came; Vali isn't in yet and isn't counted
    ]


def test_the_punctuality_ranking(week):
    data = analytics.punctuality(build(week))

    assert [
        (row["rank"], row["employee"]["name"].split()[0], row["punctuality_percent"])
        for row in data["rows"]
    ] == [(1, "Bob", 100.0), (2, "Ali", 66.7), (3, "Sara", 66.7), (4, "Vali", 66.7)]
    assert data["rows"][3]["average_late_minutes"] == 45
    assert data["average"] == 70.0


def test_equal_standing_shares_a_rank(staff, chilonzor):
    services.update_settings(staff.ali.company, by=None, require_location=False)
    for person in (staff.ali, staff.vali):
        shift_at(person, MON, branch=chilonzor)
        visit(person, MON, (8, 55), (18, 0))

    rows = analytics.punctuality(build(staff))["rows"]

    assert [row["rank"] for row in rows] == [1, 1]


def test_branch_scope_keeps_its_branches_days(week, chilonzor):
    data = analytics.summary(build(week, branch_ids=[chilonzor.pk]))

    assert list(rows_by_name(data)) == ["Ali", "Bob", "Vali"]
    assert data["totals"]["days_scheduled"] == 9
    assert analytics.summary(build(week, branch_ids=[]))["rows"] == []


def test_a_department_filter_takes_the_departments_below(week):
    company = week.ali.company
    shelves = Department.objects.create(company=company, name="Shelves", parent=week.warehouse)
    week.vali.department = shelves
    week.vali.save(update_fields=["department"])

    picked = analytics.departments_below(company, [week.warehouse.pk])
    data = analytics.summary(build(week, department_ids=picked))

    assert list(rows_by_name(data)) == ["Bob", "Vali"]
    assert analytics.departments_below(company, []) is None


def test_the_future_and_today_before_it_is_over(week):
    """A period running past today counts up to today; nobody is absent today."""
    data = analytics.summary(build(week, end=date(2026, 10, 31)))

    assert data["counted_until"] == "2026-10-23"
    assert rows_by_name(data)["Ali"]["days_scheduled"] == 5  # not next Monday's shift
    future = analytics.build(
        week.ali.company, date(2026, 11, 1), date(2026, 11, 30), branch_ids=None, now=NOW
    )
    assert analytics.summary(future)["rows"] == []
    assert analytics.summary(future)["counted_until"] is None
    assert analytics.trend(future)["days"] == []


def test_holidays_and_excused_days(staff, chilonzor):
    company = staff.ali.company
    services.update_settings(company, by=None, require_location=False)
    Holiday.objects.create(company=company, date=MON, name="Holiday")
    shift_at(staff.ali, MON, branch=chilonzor)
    visit(staff.ali, MON, (9, 0), (13, 0))  # came in on the holiday anyway
    shift_at(staff.vali, MON, branch=chilonzor)  # didn't: no absence on a holiday
    record = absent(shift_at(staff.vali, TUE, branch=chilonzor))
    services.excuse(record, by=None, reason="Doctor")

    rows = rows_by_name(analytics.summary(build(staff)))

    ali, vali = rows["Ali"], rows["Vali"]
    assert (ali["days_scheduled"], ali["days_present"], ali["worked_minutes"]) == (0, 1, 240)
    assert (vali["days_scheduled"], vali["days_absent"], vali["days_excused"]) == (1, 0, 1)
    assert vali["attendance_percent"] is None  # nothing left to attend


def test_rejected_overtime_doesnt_count(staff, chilonzor):
    services.update_settings(staff.ali.company, by=None, require_location=False)
    shift_at(staff.ali, MON, branch=chilonzor)
    visit(staff.ali, MON, (9, 0), (20, 0))
    record = staff.ali.attendance_records.get()
    assert record.overtime_minutes == 120
    assert rows_by_name(analytics.summary(build(staff)))["Ali"]["overtime_minutes"] == 120

    services.decide_overtime(record, by=None, approve=False, reason="Not asked for")

    assert rows_by_name(analytics.summary(build(staff)))["Ali"]["overtime_minutes"] == 0


def test_one_persons_month_for_the_bot(week):
    figures = analytics.person(week.vali, MON, FRI, now=NOW)

    assert (figures.days_scheduled, figures.days_present, figures.late_count) == (3, 3, 1)
    assert figures.overtime_minutes == 140
