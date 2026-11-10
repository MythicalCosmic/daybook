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
    # Its people scan when they come and when they leave.
    assert faceid_conf.get_settings(company).scan_mode == "both"
    assert FaceEvent.objects.filter(company=company, action="checked_out").exists()
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
    assert records.filter(status=AttendanceRecord.Status.AUTO_CLOSED).count() == 1  # Nodir
    assert records.filter(is_late=True).exists()
    assert built.scans > 100
    people = list(employees)
    states = {state["state"] for state in queries.today_states(company, people, NOW).values()}
    assert {"in", "leave"} <= states
    assert FaceEvent.objects.filter(company=company, kind=FaceEvent.Kind.STRANGER).exists()
    assert WorkShift.objects.filter(company=company, date__gt=NOW.date()).exists()  # the roster

    # Tidy, as the director and the manager would have left it: only the last two days'
    # overtime waits, and nothing from before today is unread.
    waiting = records.filter(overtime_status=AttendanceRecord.Overtime.PENDING)
    assert not waiting.filter(date__lt=NOW.date() - timedelta(days=2)).exists()
    assert records.filter(overtime_status=AttendanceRecord.Overtime.APPROVED).exists()
    start_of_today = datetime.combine(NOW.date(), time(0), tzinfo=TZ)
    unread = Notification.objects.filter(company=company, read_at__isnull=True)
    assert unread.exists() and not unread.filter(created_at__lt=start_of_today).exists()


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
    assert Company.objects.count() == 1
    assert Membership.objects.filter(first_name="Ravshan").count() == 1


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
    assert waiting > 30 and [row[0] for row in built.pending] == sorted(
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
    # By the evening everyone has left but the newcomer (he never scans out); the terminals
    # kept their heartbeat.
    people = list(queries.employees(company, branch_ids=None))
    found = queries.today_states(company, people, clock[-1])
    still_in = [p.first_name for p in people if (found.get(p.pk) or {}).get("state") == "in"]
    assert "out" in {state["state"] for state in found.values() if state}
    assert still_in in ([], ["Ravshan"])
    assert set(
        FaceDevice.objects.filter(company=company).values_list("last_heartbeat_at", flat=True)
    ) == {clock[-1]}
