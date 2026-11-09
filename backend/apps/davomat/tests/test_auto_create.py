"""`auto_create_employees` (docs/DAVOMAT.md §1.4): a terminal's scan with a number nobody has
makes the employee (named as on the terminal, the number linked) and counts for them, through
Face ID's real receiving path and the owner's terminal's own payload shape."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from apps.attendance.models import AttendanceRecord
from apps.audit.models import AuditLog
from apps.davomat import queries
from apps.davomat.audit_actions import DavomatAction
from apps.davomat.models import DavomatSettings, Employee
from apps.faceid import hikvision
from apps.faceid import services as face
from apps.faceid.models import FaceDevice, FaceEvent, FaceLink
from apps.faceid.tests import samples as hik
from apps.members.models import Membership

pytestmark = pytest.mark.django_db

TZ = ZoneInfo("Asia/Tashkent")
DAY = date(2026, 10, 21)
Action, Flag = FaceEvent.Action, FaceEvent.Flag


def at(hour, minute=0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), tzinfo=TZ)


@pytest.fixture
def freeze(monkeypatch):
    def set_now(moment: datetime) -> datetime:
        monkeypatch.setattr("django.utils.timezone.now", lambda: moment)
        return moment

    return set_now


@pytest.fixture
def terminal(org, freeze) -> FaceDevice:
    """The main branch's door terminal, added at 06:00."""
    freeze(at(6))
    return FaceDevice.objects.create(company=org.company, branch=org.main, name="Kirish")


@pytest.fixture
def scan(terminal, freeze, django_capture_on_commit_callbacks):
    """`scan(hour, minute, number=, name=)`: the owner's DS-K1T341AMF posts a scan made then (a
    zero-padded number, a first name, the factory +08:00 zone on a wall clock set by hand)."""
    serials = iter(range(40585, 49999))

    def post(hour, minute=0, *, number="00000002", name="Гулирано", device=terminal):
        moment = at(hour, minute)
        wall = moment.replace(tzinfo=None).isoformat() + "+08:00"
        data = hik.k1t341amf(number=number, name=name, serial=next(serials), at=wall)
        content_type, body = hik.multipart(data, part="event_log", picture=hik.jpeg())
        freeze(moment)
        with django_capture_on_commit_callbacks(execute=True):
            stored = face.receive(device, hikvision.parse(content_type, body))
        return stored[0] if stored else None

    return post


def test_an_unknown_number_becomes_an_employee_and_checks_in(org, scan):
    event = scan(8, 1)

    person = event.membership
    assert person is not None and event.action == Action.CHECKED_IN
    assert Flag.AUTO_LINKED in event.flags
    assert (person.first_name, person.last_name) == ("Гулирано", "")
    assert person.status == Membership.Status.APPROVED
    assert queries.role_kind(person.role) == "employee"
    assert list(person.branches.all()) == [org.main] and person.home_branch == org.main
    link = FaceLink.objects.get(company=org.company, number_key="2")
    assert link.membership == person and link.employee_no == "00000002" and not link.ignored
    assert Employee.objects.get(membership=person).source == Employee.Source.TERMINAL
    record = AttendanceRecord.objects.get(membership=person)
    assert record.check_in_at == at(8, 1)
    assert AuditLog.objects.filter(
        action=DavomatAction.EMPLOYEE_AUTO_CREATED, target_id=person.pk
    ).exists()


def test_the_next_scan_is_the_same_employee(org, scan):
    first = scan(8, 1)
    later = scan(18, 4, number="2")  # "2" and "00000002" are one number

    assert later.membership == first.membership
    assert later.action == Action.CHECKED_OUT
    assert Employee.objects.count() == 1


def test_a_full_name_splits_and_no_name_gets_the_number(org, scan):
    full = scan(8, 0, number="00000007", name="Ali  Valiyev")
    bare = scan(8, 5, number="00000009", name="")

    assert (full.membership.first_name, full.membership.last_name) == ("Ali", "Valiyev")
    assert bare.membership.first_name == "Employee 00000009"


def test_a_name_that_matches_an_employee_links_them_instead(org, scan):
    aziza = org.employee("Aziza", "Karimova")  # added by hand, no number yet

    event = scan(8, 1, number="00000004", name="Азиза")

    assert event.membership == aziza
    assert Employee.objects.count() == 1
    assert FaceLink.objects.get(number_key="4").membership == aziza


def test_switched_off_the_number_waits(org, scan):
    DavomatSettings.objects.filter(company=org.company).update(auto_create_employees=False)

    event = scan(8, 1)

    assert event.action == Action.NOT_LINKED and event.membership is None
    assert not Employee.objects.exists()


def test_daybook_never_makes_anyone(org, scan, settings):
    settings.EDITION = "daybook"

    event = scan(8, 1)

    assert event.action == Action.NOT_LINKED
    assert not Employee.objects.exists() and not FaceLink.objects.exists()


def test_a_number_set_aside_stays_aside(org, scan):
    face.ignore_number(org.company, by=None, employee_no="00000002")

    event = scan(8, 1)

    assert event.action == Action.IGNORED and not Employee.objects.exists()


def test_unknown_faces_and_test_scans_make_nobody(org, scan, terminal, freeze):
    data = hik.event(minor=76, number=None, name="", at=at(8, 0).isoformat())
    content_type, body = hik.multipart(data, picture=hik.jpeg())
    freeze(at(8, 0))
    face.receive(terminal, hikvision.parse(content_type, body))
    face.simulate(terminal, by=org.owner)

    assert not Employee.objects.exists()


def test_a_closed_branch_sends_them_to_the_first_open_one(org, scan, terminal):
    org.main.is_active = False
    org.main.save()

    event = scan(8, 1)

    assert list(event.membership.branches.all()) == [org.second]


def test_the_employee_shows_in_the_list_at_once(org, scan, owner_api):
    scan(8, 1)

    rows = owner_api(org.owner).get(org.url("employees/")).json()["results"]

    assert [(row["first_name"], row["face_numbers"], row["source"]) for row in rows] == [
        ("Гулирано", ["00000002"], "terminal")
    ]


def test_a_failure_never_loses_the_scan(org, scan, monkeypatch):
    def broken(*args, **kwargs):
        FaceLink.objects.create(company=org.company, employee_no="X1", ignored=True)
        raise RuntimeError("a bug")

    monkeypatch.setattr("apps.davomat.services.create_employee", broken)

    event = scan(8, 1)

    assert event is not None and event.action == Action.NOT_LINKED
    assert not FaceLink.objects.filter(employee_no="X1").exists()  # rolled back
    assert FaceEvent.objects.filter(pk=event.pk).exists()
