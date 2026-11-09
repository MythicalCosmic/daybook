"""The week the report tests count (test_analytics, test_reports).

Monday 19 to Friday 23 October 2026, "now" Friday 12:00 in Tashkent. Shifts are 09:00-18:00
with an hour's break (480 planned minutes); 10 minutes of grace either side; overtime from 15
minutes on.

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

from apps.attendance import services
from apps.attendance.tests.conftest import local
from apps.attendance.tests.factories import absent, shift_at
from apps.members.models import Department
from apps.timeoff.models import TimeOff

MON = date(2026, 10, 19)
TUE, WED, THU, FRI = (MON + timedelta(days=n) for n in range(1, 5))
NOW = local(FRI, 12, 0)


def visit(member, day, came, left=None):
    services.check_in(member, now=local(day, *came), quiet=True)
    if left is not None:
        services.check_out(member, now=local(day, *left), quiet=True)


def make_week(staff, chilonzor, yunusobod):
    """The week above for the attendance tests' `staff`; adds `staff.sales` and
    `staff.warehouse` (the departments)."""
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
