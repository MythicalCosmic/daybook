"""The terminal's payloads: the three body formats, every minor-code branch, heartbeats and the
bodies firmware gets wrong."""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from apps.faceid import hikvision
from apps.faceid.tests import samples as hik

TASHKENT = timezone(timedelta(hours=5))


def one(content_type, body) -> hikvision.DeviceEvent:
    parsed = hikvision.parse(content_type, body)
    assert not parsed.problem, parsed.problem
    assert len(parsed.events) == 1
    return parsed.events[0]


def test_multipart_with_the_json_part_and_the_snapshot():
    picture = hik.jpeg()
    content_type, body = hik.multipart(hik.event(), picture=picture)
    parsed = hikvision.parse(content_type, body)
    assert parsed.pictures == [picture]
    event = parsed.events[0]
    assert event.kind == "person"
    assert event.method == "face"
    assert event.employee_no == "12"
    assert event.name == "Alisher Valiyev"
    assert event.serial_no == 1234
    assert event.device_time == datetime(2026, 10, 21, 8, 57, 12, tzinfo=TASHKENT)
    assert not event.naive_time
    assert event.mac == "e8:a0:ed:12:34:56"
    assert event.ip == "192.168.1.250"
    assert event.verify_mode == "cardOrFaceOrFp"
    # The picture never lands in what we keep, nor do long strings.
    assert "Picture" not in json.dumps(event.raw)


def test_the_owners_ds_k1t341amf_event():
    """The real shapes: a zero-padded number, a Cyrillic first name, +08:00 on a hand-set wall
    clock, `major`/`minor` names, no attendanceStatus, a LAN picture link."""
    content_type, body = hik.multipart(hik.k1t341amf(), part="event_log", picture=hik.jpeg())
    parsed = hikvision.parse(content_type, body)
    (event,) = parsed.events
    assert (event.kind, event.method) == ("person", "face")
    assert event.employee_no == "00000002"
    assert hikvision.number_key(event.employee_no) == "2"
    assert event.name == "Гулирано"
    assert event.serial_no == 40585
    assert event.wants == ""  # no attendanceStatus: the terminal's direction decides
    assert event.device_time == datetime(
        2026, 10, 21, 7, 49, 44, tzinfo=timezone(timedelta(hours=8))
    )
    assert "LOCALS" not in json.dumps(event.raw)  # the LAN link is never kept
    assert parsed.pictures


@pytest.mark.parametrize(
    ("minor", "number", "kind"),
    [(0x4B, "00000004", "person"), (0x26, "00000006", "person"), (0x1, "00000008", "person"),
     (0x68, "00000009", "person"), (0x69, "00000009", "person"), (0x4C, "", "stranger"),
     (0x27, "00000006", "other"), (0x9, "", "other"), (0x68, "", "other")],
)  # fmt: skip
def test_the_minor_codes_this_terminal_lists(minor, number, kind):
    data = json.dumps(hik.k1t341amf(minor=minor, number=number)).encode()
    assert one("application/json", data).kind == kind


@pytest.mark.parametrize(
    ("value", "key"),
    [("00000002", "2"), ("2", "2"), (" 0012 ", "12"), ("0", ""), ("000", ""), ("", ""),
     ("a7", "A7")],
)  # fmt: skip
def test_number_keys(value, key):
    assert hikvision.number_key(value) == key


def test_multipart_named_event_log_without_a_content_type_and_bare_newlines():
    content_type, body = hik.multipart(
        hik.event(minor=38, number="7", name="Nodira"),
        part="event_log",
        part_type=None,
        picture=hik.jpeg(),
        newline=b"\n",
    )
    event = one(content_type, body)
    assert (event.kind, event.method, event.employee_no) == ("person", "fingerprint", "7")


def test_multipart_without_a_boundary_in_the_header():
    _content_type, body = hik.multipart(hik.event(), picture=hik.jpeg())
    event = one("multipart/form-data", body)
    assert event.employee_no == "12"


def test_bare_json_and_the_older_integer_employee_number():
    data = hik.event()
    inner = data["AccessControllerEvent"]
    del inner["employeeNoString"]
    inner["employeeNo"] = 12
    event = one("application/json", json.dumps(data).encode())
    assert event.employee_no == "12"
    assert event.kind == "person"


def test_json_without_a_content_type_or_with_a_byte_order_mark():
    body = "﻿".encode() + json.dumps(hik.event()).encode()
    assert one("", body).employee_no == "12"
    assert one("text/plain", body).employee_no == "12"


def test_older_isapi_xml():
    event = one("application/xml", hik.xml(number="37", name="Gulnora Karimova"))
    assert (event.kind, event.employee_no, event.name) == ("person", "37", "Gulnora Karimova")
    assert event.attendance_status == "checkIn"
    assert event.wants == "in"
    assert event.serial_no == 1234


def test_xml_with_a_dtd_is_refused():
    body = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><EventNotificationAlert/>'
    parsed = hikvision.parse("text/xml", body)
    assert parsed.events == [] and parsed.problem.startswith("unreadable")


def test_a_form_encoded_event():
    from urllib.parse import urlencode

    body = urlencode({"event_log": json.dumps(hik.event())}).encode()
    assert one("application/x-www-form-urlencoded", body).employee_no == "12"


@pytest.mark.parametrize(
    ("minor", "number", "kind", "method"),
    [
        (75, "12", "person", "face"),  # face verification passed
        (76, "", "stranger", "face"),  # an unknown face
        (76, "12", "stranger", "face"),  # someone's card, another face
        (80, "", "stranger", "face"),  # face recognition failed
        (75, "", "stranger", "face"),  # a face event without a number
        (1, "12", "person", "card"),  # a valid card
        (9, "", "other", "card"),  # an invalid card
        (9, "12", "other", "card"),
        (38, "12", "person", "fingerprint"),  # fingerprint passed
        (39, "", "other", "fingerprint"),  # fingerprint failed
        (39, "12", "other", "fingerprint"),
        (60, "12", "person", "face"),  # face and card
        (6, "12", "other", "card"),  # no right at this hour
        (21, "12", "other", ""),  # the door unlocked
        (22, "", "other", ""),  # the door locked
        (75, "0", "stranger", "face"),  # number 0 is nobody
        (999, "12", "person", "other"),  # a pass we don't know: the number decides
        (999, "", "other", ""),
    ],
)
def test_minor_codes(minor, number, kind, method):
    event = one("application/json", json.dumps(hik.event(minor=minor, number=number)).encode())
    assert (event.kind, event.method) == (kind, method)


def test_other_majors_are_never_people():
    data = hik.event(major=2, minor=39)  # an exception, whatever its minor
    assert one("application/json", json.dumps(data).encode()).kind == "other"


def test_heartbeat():
    event = one("application/json", json.dumps(hik.heartbeat()).encode())
    assert event.kind == "heartbeat"
    assert event.device_time is not None


@pytest.mark.parametrize(
    ("status", "wants"),
    [
        ("checkIn", "in"),
        ("overtimeIn", "in"),
        ("checkOut", "out"),
        ("overtimeOut", "out"),
        ("breakOut", "break"),
        ("breakIn", "break"),
        ("undefined", ""),
        ("", ""),
    ],
)
def test_attendance_status(status, wants):
    data = json.dumps(hik.event(status=status)).encode()
    assert one("application/json", data).wants == wants


@pytest.mark.parametrize(
    ("text", "expected", "naive"),
    [
        ("2026-10-21T08:57:12+05:00", datetime(2026, 10, 21, 8, 57, 12, tzinfo=TASHKENT), False),
        ("2026-10-21T03:57:12Z", datetime(2026, 10, 21, 3, 57, 12, tzinfo=UTC), False),
        ("2026-10-21T08:57:12+0500", datetime(2026, 10, 21, 8, 57, 12, tzinfo=TASHKENT), False),
        ("2026-10-21 08:57:12", datetime(2026, 10, 21, 8, 57, 12), True),
        (
            "2026-10-21T08:57:12.250+05:00",
            datetime(2026, 10, 21, 8, 57, 12, 250000, TASHKENT),
            False,
        ),
        ("not a time", None, False),
        ("", None, False),
    ],
)
def test_terminal_times(text, expected, naive):
    data = json.dumps(hik.event(at=text)).encode()
    event = one("application/json", data)
    assert event.device_time == expected
    assert event.naive_time is naive


@pytest.mark.parametrize(
    ("content_type", "body", "problem"),
    [
        ("application/json", b"", "empty"),
        ("application/json", b"   \r\n", "empty"),
        (
            "application/json",
            b'{"eventType": "AccessControllerEvent", "AccessControllerEvent": {',
            "unreadable",
        ),
        ("application/json", b"[1, 2, 3]", ""),
        ("application/json", b'"just a string"', "unreadable"),
        ("text/plain", b"hello there", "unknown format"),
        ("application/xml", b"<EventNotificationAlert><broken>", "unreadable"),
        ("multipart/form-data; boundary=zzz", b"garbage without parts", "unreadable multipart"),
    ],
)
def test_broken_bodies_never_raise(content_type, body, problem):
    parsed = hikvision.parse(content_type, body)
    assert parsed.events == []
    assert parsed.problem.startswith(problem)
    if problem not in ("", "empty"):
        assert parsed.excerpt or problem == "unreadable multipart"


def test_a_multipart_body_with_only_a_picture_keeps_it():
    picture = hik.jpeg()
    content_type, body = hik.multipart(None, picture=picture)
    parsed = hikvision.parse(content_type, body)
    assert parsed.events == [] and parsed.pictures == [picture]
    assert parsed.problem == "no event"


def test_a_truncated_json_part_is_kept_for_a_look():
    content_type, body = hik.multipart(b'{"eventType":\t"AccessControllerEvent",\t"Acc')
    parsed = hikvision.parse(content_type, body)
    assert parsed.events == []
    assert parsed.problem.startswith("unreadable")
    assert parsed.excerpt.startswith('{"eventType"')


def test_names_lose_control_characters_and_extra_spaces():
    data = hik.event(name="  Alisher\x00\x00  Valiyev ")
    assert one("application/json", json.dumps(data).encode()).name == "Alisher Valiyev"


def test_raw_is_capped_and_drops_long_strings():
    data = hik.event(faceTemplate="A" * 50_000)
    for index in range(400):
        data["AccessControllerEvent"][f"extra{index}"] = "x" * 100
    event = one("application/json", json.dumps(data).encode())
    encoded = json.dumps(event.raw)
    assert len(encoded) <= hikvision.MAX_RAW_BYTES + 200
    assert "A" * 600 not in encoded
