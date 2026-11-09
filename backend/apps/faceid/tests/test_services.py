"""Face ID: what a terminal's scans do (apps/faceid/services.py), and, with attendance on, what
they do to attendance (apps.attendance.services.scan)."""

import json
from datetime import date, timedelta

import pytest

from apps.attendance import services as attendance
from apps.attendance.models import AttendanceRecord
from apps.attendance.tests.factories import shift_at
from apps.faceid import hikvision
from apps.faceid import services as face
from apps.faceid.models import FaceDevice, FaceEvent, FaceLink
from apps.faceid.tests import samples as hik
from apps.faceid.tests.conftest import DAY, local
from apps.inbox.models import Notification

pytestmark = pytest.mark.django_db

Action, Flag = FaceEvent.Action, FaceEvent.Flag


@pytest.fixture
def telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "apps.attendance.notify.send_telegram_message.delay",
        lambda bot, chat_id, text, markup=None, *a, **kw: sent.append((chat_id, text)),
    )
    return sent


@pytest.fixture
def scan(device, freeze, django_capture_on_commit_callbacks):
    """`scan(hour, minute, **event)`: the terminal posts a scan made then (delivered then, or
    `received=` later) and we handle it; returns the stored event (None when nothing was)."""
    serials = iter(range(1000, 9999))

    def post(hour, minute=0, *, received=None, terminal=device, picture=True, day=DAY, **fields):
        at = local(day, hour, minute)
        fields.setdefault("serial", next(serials))
        content_type, body = hik.multipart(
            hik.event(at=at.isoformat(), **fields), picture=hik.jpeg() if picture else None
        )
        freeze(received or at)
        with django_capture_on_commit_callbacks(execute=True):
            stored = face.receive(terminal, hikvision.parse(content_type, body))
        terminal.refresh_from_db()
        return stored[0] if stored else None

    return post


def record_of(event) -> AttendanceRecord | None:
    return AttendanceRecord.objects.filter(pk=event.record_id).first() if event.record_id else None


def records(member):
    return list(AttendanceRecord.objects.filter(membership=member).order_by("check_in_at"))


def seen_live(device, freeze, hour=7):
    """The terminal's heartbeat that morning: its clock is right."""
    content_type, body = hik.multipart(hik.heartbeat(at=local(DAY, hour, 0).isoformat()))
    freeze(local(DAY, hour, 0))
    face.receive(device, hikvision.parse(content_type, body))


def settings(company, **changes):
    return face.update_settings(company, by=None, **changes)


# The owner's terminal ------------------------------------------------------------------------


def test_the_owners_terminal_as_it_really_posts(
    staff, device, freeze, django_capture_on_commit_callbacks
):
    """Number 00000002 is linked as "2". The wall clock says 07:49:44 with the factory zone
    (+08:00) while it is 08:01 in Tashkent: the offset means nothing; a clock behind is still the
    scan's time (a past time is never replaced), and the terminal's card says the clock is slow."""
    FaceLink.objects.create(company=device.company, employee_no="2", membership=staff.bob)

    def post(at, received, serial):
        data = hik.k1t341amf(at=at, serial=serial, name="Бобур")
        content_type, body = hik.multipart(data, part="event_log", picture=hik.jpeg())
        freeze(received)
        with django_capture_on_commit_callbacks(execute=True):
            (event,) = face.receive(device, hikvision.parse(content_type, body))
        return event

    event = post("2026-10-21T07:49:44+08:00", local(DAY, 8, 1), 40585)
    assert (event.membership, event.employee_no, event.action) == (
        staff.bob,
        "00000002",
        Action.CHECKED_IN,
    )
    assert event.event_at.astimezone(local(DAY, 0).tzinfo).strftime("%H:%M:%S") == "07:49:44"
    assert Flag.CLOCK_OFF not in event.flags
    assert event.raw["dateTime"] == "2026-10-21T07:49:44+08:00"
    device.refresh_from_db()
    assert device.clock_offset_s == -676  # 11 min 16 s slow: the card warns
    later = post("2026-10-21T18:04:00+08:00", local(DAY, 18, 4), 40586)
    assert later.action == Action.CHECKED_OUT and later.event_at == local(DAY, 18, 4)


def test_the_five_people_on_the_terminal_link_themselves(staff, device, scan):
    """Mushtariy, Zulfiya, Muhammadyusuf, Гулирано and Шахзодбек are on the owner's terminal by
    first name; each is one Daybook person, so each links automatically."""
    people = [
        (staff.manager, "Mushtariy", "Karimova", "00000002", "Mushtariy"),
        (staff.lead, "Zulfiya", "Rahimova", "00000004", "Zulfiya"),
        (staff.bob, "Muhammadyusuf", "Aliyev", "00000006", "Muhammadyusuf"),
        (staff.accountant, "Gulirano", "Saidova", "00000008", "Гулирано"),
        (staff.sara, "Shahzodbek", "Tursunov", "00000009", "Шахзодбек"),
    ]
    staff.sara.face_links.all().delete()
    for index, (person, first, last, number, on_device) in enumerate(people):
        person.first_name, person.last_name = first, last
        person.save()
        event = scan(9, index * 5, number=number, name=on_device)
        assert event.membership == person, on_device
        assert Flag.AUTO_LINKED in event.flags
        link = FaceLink.objects.get(number_key=number.lstrip("0"))
        assert link.membership == person and link.auto and link.employee_no == number


# Attendance ---------------------------------------------------------------------------------


def test_one_door_checks_in_then_out(staff, scan, telegram, chilonzor):
    first = scan(8, 57)
    assert first.action == Action.CHECKED_IN
    assert first.membership == staff.ali
    record = record_of(first)
    assert record.in_source == AttendanceRecord.Source.FACE
    assert record.branch == chilonzor
    assert record.flags == [AttendanceRecord.Flag.UNSCHEDULED]  # no shift; no location flags
    assert record.in_photo  # the check-in keeps its own copy of the snapshot
    assert first.photo
    last = scan(18, 4)
    assert last.action == Action.CHECKED_OUT
    record.refresh_from_db()
    assert record.status == AttendanceRecord.Status.CLOSED
    assert record.out_source == AttendanceRecord.Source.FACE
    assert AttendanceRecord.Flag.NO_LOCATION not in record.flags
    assert record.worked_minutes == 9 * 60 + 7
    texts = [text for _chat, text in telegram]
    assert texts[0].startswith("You came in: 08:57, Chilonzor.")
    assert texts[1].startswith("You left: 18:04. You worked 9 h 7 min today.")


def test_with_the_attendance_switch_off_scans_are_only_seen(staff, scan, telegram):
    settings(staff.ali.company, attendance=False)
    event = scan(8, 57)
    assert event.action == Action.SEEN and event.membership == staff.ali
    assert records(staff.ali) == [] and telegram == []
    assert event.photo


def test_without_the_attendance_module_scans_are_only_seen(staff, scan):
    company = staff.ali.company
    company.features = ["face_id"]
    company.save()
    assert scan(8, 57).action == Action.SEEN
    assert records(staff.ali) == []


def test_a_late_arrival_says_so_and_keeps_the_group_post(staff, scan, telegram, monkeypatch):
    posts = []
    monkeypatch.setattr(
        "apps.attendance.notify.late_arrival", lambda record_id: posts.append(record_id)
    )
    shift_at(staff.ali, DAY)  # 09:00 to 18:00 at Chilonzor
    event = scan(9, 25)
    record = record_of(event)
    assert record.is_late and record.late_minutes == 25
    assert "Late by 25 min." in telegram[0][1]
    assert posts == [record.pk]


def test_a_second_scan_soon_after_is_a_repeat(staff, scan):
    scan(8, 57)
    again = scan(8, 58)
    assert again.action == Action.REPEAT
    assert len(records(staff.ali)) == 1
    assert records(staff.ali)[0].status == AttendanceRecord.Status.OPEN


def test_a_scan_right_after_checking_in_in_the_app_is_a_repeat(staff, scan, freeze):
    freeze(local(DAY, 8, 56))
    attendance.update_settings(staff.ali.company, by=None, require_location=False)
    attendance.check_in(staff.ali)
    assert scan(8, 57).action == Action.REPEAT
    assert records(staff.ali)[0].status == AttendanceRecord.Status.OPEN


def test_the_terminal_retrying_an_event_counts_it_once(staff, scan):
    assert scan(8, 57, serial=55) is not None
    assert scan(8, 57, serial=55) is None
    assert FaceEvent.objects.count() == 1


def test_attendance_status_decides_at_a_one_door_terminal(staff, scan):
    event = scan(13, 0, status="checkOut")
    assert event.action == Action.CHECKED_IN
    assert Flag.MISSED_ENTRY in event.flags
    assert AttendanceRecord.Flag.MISSED_ENTRY in record_of(event).flags
    again = scan(14, 0, status="checkIn")
    assert again.action == Action.REPEAT and Flag.ALREADY_IN in again.flags
    pause = scan(15, 0, status="breakOut")
    assert pause.action == Action.IGNORED and Flag.BREAK in pause.flags
    assert scan(18, 0, status="checkOut").action == Action.CHECKED_OUT


def test_entrance_and_exit_terminals(staff, device, scan, chilonzor):
    exit_door = FaceDevice.objects.create(
        company=chilonzor.company, branch=chilonzor, name="Chiqish", direction="out"
    )
    device.direction = FaceDevice.Direction.IN
    device.save()
    assert scan(8, 57).action == Action.CHECKED_IN
    assert scan(12, 0).action == Action.REPEAT  # the entrance never checks out
    assert scan(13, 0, terminal=exit_door).action == Action.CHECKED_OUT
    late = scan(18, 4, terminal=exit_door)
    assert late.action == Action.CHECKED_OUT
    (record,) = records(staff.ali)
    assert record.check_out_at == local(DAY, 18, 4)


def test_a_burst_after_an_outage_updates_attendance_quietly(staff, device, scan, telegram, freeze):
    seen_live(device, freeze)
    evening = local(DAY, 21, 30)
    came = scan(8, 57, received=evening)
    left = scan(18, 4, received=evening)
    assert (came.action, left.action) == (Action.CHECKED_IN, Action.CHECKED_OUT)
    assert came.event_at == local(DAY, 8, 57)
    assert Flag.DELIVERED_LATE in came.flags
    (record,) = records(staff.ali)
    assert record.check_in_at == local(DAY, 8, 57) and record.check_out_at == local(DAY, 18, 4)
    assert telegram == []
    assert not Notification.objects.filter(kind="faceid.scan").exists()


def test_a_late_check_out_replaces_the_systems_guess(staff, scan, freeze):
    shift_at(staff.ali, DAY)
    scan(8, 57)
    freeze(local(DAY, 21, 5))
    attendance.auto_close(staff.ali.company)
    (record,) = records(staff.ali)
    assert record.status == AttendanceRecord.Status.AUTO_CLOSED
    out = scan(18, 4, received=local(DAY + timedelta(days=1), 8, 0))
    assert out.action == Action.CHECKED_OUT and Flag.LATE_CHECK_OUT in out.flags
    record.refresh_from_db()
    assert record.status == AttendanceRecord.Status.CLOSED
    assert record.check_out_at == local(DAY, 18, 4)
    assert AttendanceRecord.Flag.AUTO_CLOSED not in record.flags


def test_a_scan_older_than_the_record_changes_nothing(staff, device, scan, freeze):
    seen_live(device, freeze)
    attendance.update_settings(staff.ali.company, by=None, require_location=False)
    freeze(local(DAY, 9, 5))
    attendance.check_in(staff.ali)
    old = scan(8, 57, received=local(DAY, 9, 40))
    assert old.action == Action.IGNORED and Flag.OUT_OF_ORDER in old.flags
    assert records(staff.ali)[0].status == AttendanceRecord.Status.OPEN


def test_the_terminals_old_history_is_skipped(staff, device, scan, telegram):
    """Pointed at us, a terminal uploads everything it ever stored, oldest first (here 2022):
    nothing is kept, decoded, recorded or sent; the terminal counts what it skipped. The first live
    scan after it is handled as usual."""
    old_day = date(2022, 10, 11)
    for minute in range(5):
        skipped = scan(16, minute, day=old_day, received=local(DAY, 9, 0), number="1", name="Abdu")
        assert skipped is None
    assert FaceEvent.objects.count() == 0
    assert AttendanceRecord.objects.count() == 0
    assert not Notification.objects.exists() and telegram == []
    device.refresh_from_db()
    assert device.history_skipped == 5
    assert device.history_until == local(old_day, 16, 4)
    assert device.history_seen_at == local(DAY, 9, 0)
    assert device.last_event_at is None  # history never makes the terminal look live
    assert device.clock_offset_s is None  # nor tells its clock
    live = scan(9, 1, received=local(DAY, 9, 1) + timedelta(seconds=20))
    assert live.action == Action.CHECKED_IN and live.event_at == local(DAY, 9, 1)
    assert Notification.objects.filter(kind="faceid.scan").exists()
    assert telegram  # the person's own message


def test_a_scan_more_than_a_day_old_is_history(staff, device, scan):
    device.created_at = local(DAY - timedelta(days=5), 9)
    device.save()
    assert scan(8, 57, day=DAY - timedelta(days=2), received=local(DAY, 9, 0)) is None
    device.refresh_from_db()
    assert device.history_skipped == 1 and FaceEvent.objects.count() == 0


def test_a_clock_ahead_takes_the_arrival_time(staff, scan):
    ahead = scan(10, 20, received=local(DAY, 10, 0))
    assert Flag.CLOCK_OFF in ahead.flags
    assert ahead.event_at == local(DAY, 10, 0)


def test_a_delayed_live_scan_keeps_its_time_and_sends_nothing(staff, device, scan, telegram):
    """Two hours late (the shop's internet was down): attendance takes the terminal's time,
    quietly; it is no arrival to announce now."""
    late = scan(8, 57, received=local(DAY, 10, 57))
    assert late.action == Action.CHECKED_IN and late.event_at == local(DAY, 8, 57)
    assert Flag.CLOCK_OFF not in late.flags and Flag.DELIVERED_LATE in late.flags
    assert record_of(late).check_in_at == local(DAY, 8, 57)
    assert telegram == [] and not Notification.objects.filter(kind="faceid.scan").exists()


def test_a_terminal_at_another_branch_than_the_shift(staff, scan, yunusobod, chilonzor):
    shift_at(staff.ali, DAY, branch=yunusobod)
    event = scan(8, 57)
    record = record_of(event)
    assert record.branch == chilonzor
    assert AttendanceRecord.Flag.OTHER_BRANCH in record.flags
    assert Flag.OTHER_BRANCH in event.flags


def test_fingerprint_and_card_passes_count_like_a_face(staff, scan):
    finger = scan(8, 57, minor=38, mode="fp")
    assert finger.action == Action.CHECKED_IN and finger.method == "fingerprint"
    card = scan(18, 0, minor=1, mode="card")
    assert card.action == Action.CHECKED_OUT and card.method == "card"


def test_someone_suspended_is_not_checked_in(staff, scan):
    staff.ali.status = staff.ali.Status.SUSPENDED
    staff.ali.save()
    event = scan(8, 57)
    assert event.action == Action.IGNORED and Flag.NOT_APPROVED in event.flags


# Who: links, names, strangers --------------------------------------------------------------


def test_an_unknown_number_links_by_name(staff, scan):
    staff.bob.last_name = "Ergashev"
    staff.bob.save()
    event = scan(8, 57, number="31", name="  ERGASHEV   bob ")
    assert event.action == Action.CHECKED_IN and Flag.AUTO_LINKED in event.flags
    link = FaceLink.objects.get(employee_no="31")
    assert link.membership == staff.bob and link.auto


def test_no_link_when_the_name_is_ambiguous_or_the_person_has_a_number(staff, scan):
    event = scan(8, 57, number="40", name="Ali")  # Ali already has number 12
    assert event.action == Action.NOT_LINKED and event.photo  # kept and shown all the same
    staff.bob.first_name = "Vali"
    staff.bob.save()
    staff.vali.face_links.all().delete()
    assert scan(9, 0, number="41", name="Vali").action == Action.NOT_LINKED  # two Valis
    assert not FaceLink.objects.filter(employee_no__in=["40", "41"]).exists()


def test_an_ignored_number_is_logged_only(staff, device, scan):
    FaceLink.objects.create(company=device.company, employee_no="88", ignored=True)
    event = scan(8, 57, number="88", name="Guard")
    assert event.action == Action.IGNORED and Flag.IGNORED_NUMBER in event.flags


def test_unknown_faces_alert_at_most_every_ten_minutes(staff, scan):
    settings(staff.ali.company, alert_strangers=True)
    first = scan(8, 40, minor=76, number="", name="")
    second = scan(8, 45, minor=76, number="", name="", serial=None)
    third = scan(8, 52, minor=76, number="", name="", serial=None)
    assert [event.action for event in (first, second, third)] == [Action.STRANGER] * 3
    assert Flag.ALERTED in first.flags
    assert Flag.ALERTED not in second.flags
    assert Flag.ALERTED in third.flags
    alerts = Notification.objects.filter(kind="faceid.stranger")
    assert alerts.filter(recipient=staff.manager).count() == 2
    assert first.photo  # every scan keeps its snapshot


def test_strangers_alert_nobody_by_default(staff, scan):
    assert scan(8, 40, minor=76, number="", name="").action == Action.STRANGER
    assert not Notification.objects.filter(kind="faceid.stranger").exists()


def test_other_events_are_logged_only(staff, scan):
    door = scan(8, 57, minor=21)
    assert (door.kind, door.action) == ("other", Action.IGNORED)
    assert records(staff.ali) == []


# Telegram ----------------------------------------------------------------------------------


def test_who_came_goes_once_a_day_with_the_snapshot(staff, scan):
    scan(8, 57)
    scan(13, 0)  # the same person later: no second message
    scan(9, 10, number="77", name="Dilshod Karimov")  # not in Daybook: still "who came"
    notices = Notification.objects.filter(kind="faceid.scan")
    viewers = set(notices.values_list("recipient_id", flat=True))
    assert {staff.manager.pk, staff.lead.pk, staff.accountant.pk} <= viewers
    assert staff.ali.pk not in viewers and staff.sara.pk not in viewers
    titles = set(notices.values_list("title", flat=True))
    assert titles == {"Ali · 08:57 · Kirish", "Dilshod Karimov (No 77) · 09:10 · Kirish"}
    assert notices.filter(recipient=staff.manager).count() == 2
    first = FaceEvent.objects.get(event_at=local(DAY, 8, 57))
    assert Flag.ARRIVAL in first.flags


def test_every_scan_or_nothing(staff, scan):
    company = staff.ali.company
    settings(company, telegram="every_scan")
    scan(8, 57)
    scan(18, 0)
    assert Notification.objects.filter(kind="faceid.scan", recipient=staff.manager).count() == 2
    settings(company, telegram="off")
    scan(8, 0, day=DAY + timedelta(days=1), number="77", name="Dilshod")
    assert Notification.objects.filter(kind="faceid.scan", recipient=staff.manager).count() == 2
    # With "who came" off, a new number still reaches the managers, once a day.
    scan(9, 0, day=DAY + timedelta(days=1), number="77", name="Dilshod")
    unlinked = Notification.objects.filter(kind="faceid.unlinked", recipient=staff.manager)
    assert unlinked.count() == 1


def test_arrivals_reach_the_branchs_groups_when_asked(staff, scan, monkeypatch):
    posted = []
    monkeypatch.setattr(
        "apps.faceid.notify.groups.broadcast",
        lambda company_id, event, text, **kw: posted.append((text, kw.get("photo"))),
    )
    settings(staff.ali.company, group_posts=True, group_photos=True)
    scan(8, 57)
    (text, photo) = posted[0]
    assert text == "<b>Ali</b>: 08:57, Kirish." and photo


# Privacy and the module switch --------------------------------------------------------------


def test_a_company_without_the_module_keeps_nothing_personal(staff, device, scan):
    company = device.company
    company.features = ["attendance"]
    company.save()
    event = scan(8, 57)
    assert event.action == Action.MODULE_OFF
    assert (event.employee_no, event.name_on_device, event.photo.name) == ("", "", "")
    assert "Alisher" not in json.dumps(event.raw)
    assert records(staff.ali) == []


def test_a_disabled_terminal_changes_nothing(staff, device, scan):
    device.enabled = False
    device.save()
    assert scan(8, 57) is None
    assert FaceEvent.objects.count() == 0
    assert device.last_seen_at is not None


def test_no_snapshots_are_kept_at_zero_days(staff, scan):
    settings(staff.ali.company, photo_days=0)
    event = scan(8, 57)
    assert not event.photo and not record_of(event).in_photo


def test_old_snapshots_are_deleted(staff, scan):
    event = scan(8, 57)
    record = record_of(event)
    assert face.cleanup_photos(local(DAY + timedelta(days=29), 3)) == 0
    assert face.cleanup_photos(local(DAY + timedelta(days=31), 3)) == 2
    event.refresh_from_db()
    record.refresh_from_db()
    assert not event.photo and not record.in_photo


def test_a_test_scan_shows_but_changes_nothing(staff, device, freeze):
    freeze(local(DAY, 10, 0))
    event = face.simulate(device, by=staff.manager)
    assert event.action == Action.IGNORED and Flag.SIMULATED in event.flags
    assert event.membership == staff.manager and event.photo
    assert AttendanceRecord.objects.count() == 0
    assert not FaceLink.objects.filter(membership=staff.manager).exists()
    device.refresh_from_db()
    assert device.last_event_at is None  # a test never makes the terminal look connected
    assert not Notification.objects.filter(kind="faceid.scan").exists()


def test_settings_are_checked(staff):
    from apps.core.exceptions import DomainError

    with pytest.raises(DomainError):
        settings(staff.ali.company, repeat_minutes=0)
    with pytest.raises(DomainError):
        settings(staff.ali.company, telegram="sometimes")


def test_setup_values(settings_module, device):
    settings_module.PUBLIC_DEVICE_HOST = ""
    settings_module.DASHBOARD_URL = "https://144.91.81.29.nip.io"
    values = face.setup(device)
    assert values["host"] == "144.91.81.29.nip.io" and values["addressing"] == "hostname"
    assert values["path"] == f"/api/v1/devices/hik/{device.token}/" and len(values["path"]) < 128
    assert values["https"] == {"port": 443, "url": f"https://144.91.81.29.nip.io{values['path']}"}
    assert values["recommended"] == "https" and values["heartbeat_minutes"] == 5
    settings_module.PUBLIC_DEVICE_HOST = "144.91.81.29"
    assert face.setup(device)["addressing"] == "ipaddress"


@pytest.fixture
def settings_module(settings):
    return settings


def test_names_match_across_scripts():
    assert face.name_key("Шахзодбек") == face.name_key("Shahzodbek")
    assert face.name_key("Ғулом Ўринов") == face.name_key("G‘ulom O‘rinov")
    assert face.name_key("Гулирано") == face.name_key("gulirano")
    assert face.latin("Чўлпон Хўжаева") == "cho'lpon xo'jaeva"
