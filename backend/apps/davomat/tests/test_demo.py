"""The Davomat demo (`manage.py davomat_demo`, apps/davomat/demo.py)."""

from datetime import date, datetime, time, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command

from apps.attendance.models import AttendanceRecord, WorkShift
from apps.companies.models import Company
from apps.core import demo_time
from apps.davomat import demo, queries
from apps.davomat.models import Employee
from apps.faceid import conf as faceid_conf
from apps.faceid.models import FaceDevice, FaceEvent
from apps.inbox.models import Notification
from apps.members.models import Membership
from apps.signin import services as signin

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
NOW = datetime.combine(date(2026, 11, 10), time(10, 30), tzinfo=TZ)  # a Tuesday morning


@pytest.fixture
def built(davomat):
    with demo_time.quiet():
        return demo.build(NOW)


def test_the_demo_organization(built):
    """One build for every check (it takes a few seconds)."""
    company = built.company
    assert company.name == "Namuna MChJ" and company.default_language == "uz"
    assert sorted(company.branches.values_list("name", flat=True)) == [
        "Bosh ofis",
        "Chilonzor filiali",
    ]
    assert FaceDevice.objects.filter(company=company).count() == 2
    assert demo.is_demo(company)
    employees = queries.employees(company, branch_ids=None)
    # Fifteen, the newcomer the terminal added, the director and the branch manager.
    assert employees.count() == 18
    assert queries.is_employee(built.owner) and queries.is_user(built.owner)
    assert signin.can_sign_in(built.owner.user) and signin.can_sign_in(built.manager.user)
    assert queries.role_kind(built.manager.role) == "manager"
    assert built.owner.user.check_password(demo.PASSWORD)

    # The newcomer added himself this morning.
    newcomer = Membership.objects.get(company=company, first_name="Ravshan")
    assert Employee.objects.get(membership=newcomer).source == Employee.Source.TERMINAL
    assert newcomer.face_links.get().employee_no == "00000016"
    assert AttendanceRecord.objects.filter(membership=newcomer).exists()

    # The week and this morning have attendance.
    records = AttendanceRecord.objects.filter(company=company)
    assert records.filter(status=AttendanceRecord.Status.ABSENT).exists()
    assert records.filter(is_late=True).exists()
    assert built.scans > 90
    people = list(employees)
    states = {state["state"] for state in queries.today_states(company, people, NOW).values()}
    assert {"in", "leave"} <= states
    assert FaceEvent.objects.filter(company=company, kind=FaceEvent.Kind.STRANGER).exists()
    assert WorkShift.objects.filter(company=company, date__gt=NOW.date()).exists()  # the roster

    # People scan only when they come, as Daybook's do: no scan checked anyone out, someone who
    # stepped out and came back this morning is only seen, and every past day closed quietly at
    # the shift's end (no forgotten check-out, no overtime from a check-out nobody made).
    assert faceid_conf.get_settings(company).scan_mode == "arrival"
    events = FaceEvent.objects.filter(company=company)
    assert not events.filter(action=FaceEvent.Action.CHECKED_OUT).exists()
    start_of_today = datetime.combine(NOW.date(), time(0), tzinfo=TZ)
    assert events.filter(action=FaceEvent.Action.SEEN, event_at__gte=start_of_today).exists()
    past = records.filter(date__lt=NOW.date(), check_in_at__isnull=False).select_related("shift")
    assert past.count() > 50
    assert {(record.status, record.out_source) for record in past} == {("closed", "system")}
    assert all(record.check_out_at == record.shift.ends_at for record in past)
    assert not any("auto_closed" in record.flags for record in past)
    assert not records.exclude(overtime_status=AttendanceRecord.Overtime.NONE).exists()

    # Tidy, as the director and the manager would have left it: nothing from before today is
    # unread.
    unread = Notification.objects.filter(company=company, read_at__isnull=True)
    assert unread.exists() and not unread.filter(created_at__lt=start_of_today).exists()
    assert not unread.filter(kind="attendance.auto_closed").exists()


def test_the_command_needs_the_edition(db):
    with pytest.raises(CommandError, match="EDITION=davomat"):
        call_command("davomat_demo", stdout=StringIO())


def test_the_command_fills_an_empty_install_and_resets_only_itself(davomat, monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    out = StringIO()

    call_command("davomat_demo", "--days", "2", stdout=out)
    with pytest.raises(CommandError, match="--reset"):
        call_command("davomat_demo", stdout=StringIO())
    call_command("davomat_demo", "--reset", "--days", "2", stdout=StringIO())

    assert "Namuna MChJ: 18 employees, 2 terminals" in out.getvalue()
    assert "People scan only when they come" in out.getvalue()
    assert Company.objects.count() == 1
    assert Membership.objects.filter(first_name="Ravshan").count() == 1


def test_the_command_can_show_people_scanning_both_ways(davomat, monkeypatch):
    """`--scan-mode both`: they scan when they leave too, from 18:00 on (yesterday Nodir forgot,
    so the system closed his day), and a second scan is the departure, never only "seen"."""
    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    out = StringIO()

    call_command("davomat_demo", "--days", "2", "--scan-mode", "both", stdout=out)

    company = Company.objects.get()
    assert faceid_conf.get_settings(company).scan_mode == "both"
    assert "when they come and when they leave" in out.getvalue()
    events = FaceEvent.objects.filter(company=company)
    departures = events.filter(action=FaceEvent.Action.CHECKED_OUT)
    assert departures.count() > 10
    assert {event.event_at.astimezone(TZ).hour for event in departures} == {18}
    assert not events.filter(action=FaceEvent.Action.SEEN).exists()
    records = AttendanceRecord.objects.filter(company=company)
    forgot = records.get(status=AttendanceRecord.Status.AUTO_CLOSED)
    assert forgot.membership.first_name == "Nodir" and "auto_closed" in forgot.flags


def test_the_command_never_removes_a_real_organization(org):
    with pytest.raises(CommandError, match="isn't the demo"):
        call_command("davomat_demo", "--reset", stdout=StringIO())

    assert Company.objects.get() == org.company


def test_a_live_demo_fills_in_as_the_morning_goes(davomat, monkeypatch):
    early = datetime.combine(NOW.date(), time(8, 30), tzinfo=TZ)
    with demo_time.quiet():
        built = demo.build(early, live=True)
    company = built.company
    today = FaceEvent.objects.filter(company=company, event_at__gte=early - timedelta(hours=3))
    assert not today.exists()  # nothing of this morning yet
    assert not Membership.objects.filter(company=company, first_name="Ravshan").exists()
    waiting = len(built.pending)
    assert waiting > 15 and [row[0] for row in built.pending] == sorted(
        row[0] for row in built.pending
    )

    clock = [early]
    monkeypatch.setattr("django.utils.timezone.now", lambda: clock[-1])

    def sleep(seconds):
        clock.append(clock[-1] + timedelta(seconds=seconds))

    lines = []
    with demo_time.quiet():
        assert demo.run_live(built, say=lines.append, sleep=sleep) == waiting

    assert today.count() == waiting and len(lines) == waiting
    assert lines[0].startswith("08:") and "Bosh ofis" in lines[0]
    # The newcomer came today and the terminal made him an employee.
    newcomer = Membership.objects.get(company=company, first_name="Ravshan")
    assert Employee.objects.get(membership=newcomer).source == Employee.Source.TERMINAL
    # People scan only when they come: everyone who came is in, nobody was checked out by a
    # scan, those who stepped out and came back were only seen; the terminals kept their
    # heartbeat.
    people = list(queries.employees(company, branch_ids=None))
    found = queries.today_states(company, people, clock[-1])
    assert "out" not in {state["state"] for state in found.values() if state}
    arrivals = today.filter(action=FaceEvent.Action.CHECKED_IN)
    came = set(arrivals.values_list("membership", flat=True))
    assert len(came) > 10 and all(found[member_id]["state"] == "in" for member_id in came)
    assert not today.filter(action=FaceEvent.Action.CHECKED_OUT).exists()
    assert today.filter(action=FaceEvent.Action.SEEN).count() == 2
    assert set(
        FaceDevice.objects.filter(company=company).values_list("last_heartbeat_at", flat=True)
    ) == {clock[-1]}
