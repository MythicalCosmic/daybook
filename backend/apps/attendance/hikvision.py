"""Reading what a Hikvision access terminal posts to its HTTP Listening host.

The terminal (MinMoe DS-K1T341AMF and its kin) recognises people itself and posts every event to
the host, port and URL the owner typed in. Firmware differs, so everything here is tolerant and
pure (nothing touches the database):

    parsed = hikvision.parse(content_type, body)
    parsed.events     # DeviceEvent list (usually one)
    parsed.pictures   # the JPEG snapshots that came with it
    parsed.problem    # why nothing could be read ("" when something could)
    parsed.excerpt    # the start of the unreadable part, to keep for a look

Bodies we read:

1. `multipart/form-data`: a JSON part (named `AccessControllerEvent` or `event_log`, typed
   `application/json` or not typed at all) and zero or more JPEG parts (`Picture`).
2. `application/json`: the event alone (a list of events is read too).
3. XML (older ISAPI): `<EventNotificationAlert>` with `<eventType>` and an
   `<AccessControllerEvent>` child holding the same fields as elements.

An event is a **person** when it carries an employee number (not "0") and its minor code isn't a
failed verification or a door event; a **stranger** when a face didn't match (76, 80, or a face
combination that failed) or a face event came without a number; a **heartbeat** keeps the
terminal's status fresh; anything else is **other** (logged, does nothing).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qs
from xml.etree import ElementTree

# Major event type of access control events (alarms, exceptions and operations are others).
MAJOR_EVENT = 5

# Minor codes (subEventType) of a verified person, by how they were verified.
FACE_PASS = frozenset({54, 57, 60, 63, 66, 75, 77})
FINGERPRINT_PASS = frozenset({38, 40, 43, 46, 69, 72})
CARD_PASS = frozenset({1, 2})
# A face didn't match: an unknown face, or someone else's card or finger with this face.
FACE_FAILED = frozenset({55, 58, 61, 64, 67, 76, 78, 80})
# Other failed or refused verifications (an invalid card, a finger that didn't match, no right
# at this hour, a timeout): logged only.
FAILED = frozenset(
    {
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        39,
        41,
        42,
        44,
        45,
        47,
        48,
        49,
        56,
        59,
        62,
        65,
        68,
        70,
        71,
        73,
        74,
        79,
    }
)
# Door, lock, button and alarm states: never a person, whatever number comes with them.
DOOR = frozenset(set(range(17, 38)) | {50, 51, 52, 53, 81, 82})
FACE_MINORS = FACE_PASS | FACE_FAILED
# What a known minor tells about the way someone was verified.
METHODS = (
    (FACE_PASS | FACE_FAILED, "face"),
    (FINGERPRINT_PASS | {39, 41, 44, 47, 49, 70, 73}, "fingerprint"),
    (CARD_PASS | {3, 6, 7, 8, 9}, "card"),
)

# attendanceStatus values (set on the terminal, or by its attendance schedule).
CHECK_IN_STATUSES = frozenset({"checkin", "overtimein"})
CHECK_OUT_STATUSES = frozenset({"checkout", "overtimeout"})
BREAK_STATUSES = frozenset({"breakout", "breakin"})

# The event JSON we keep (`FaceEvent.raw`), at most this big; long strings (embedded pictures,
# face templates) never stay.
MAX_RAW_BYTES = 8 * 1024
MAX_RAW_STRING = 512
# How much of an unreadable part we keep to look at.
MAX_EXCERPT = 2048
JPEG_MAGIC = b"\xff\xd8\xff"

PERSON, STRANGER, OTHER, HEARTBEAT = "person", "stranger", "other", "heartbeat"


@dataclass
class DeviceEvent:
    """One event as the terminal described it."""

    event_type: str = ""
    device_time: datetime | None = None
    # The terminal's time came without an offset: read it in the company's timezone.
    naive_time: bool = False
    major: int | None = None
    minor: int | None = None
    employee_no: str = ""
    name: str = ""
    serial_no: int | None = None
    attendance_status: str = ""
    verify_mode: str = ""
    user_type: str = ""
    mac: str = ""
    ip: str = ""
    device_id: str = ""
    device_name: str = ""
    model: str = ""
    pictures_number: int = 0
    raw: dict = field(default_factory=dict)

    @property
    def is_heartbeat(self) -> bool:
        return "heart" in self.event_type.lower()

    @property
    def has_number(self) -> bool:
        return bool(self.employee_no) and self.employee_no.strip("0") != ""

    @property
    def kind(self) -> str:
        """person · stranger · heartbeat · other (the rules in the module docstring)."""
        if self.is_heartbeat:
            return HEARTBEAT
        if self.major is not None and self.major != MAJOR_EVENT:
            return OTHER
        minor = self.minor
        if minor in FACE_FAILED:
            return STRANGER
        if minor in FAILED or minor in DOOR:
            return OTHER
        if self.has_number:
            return PERSON
        if minor in FACE_MINORS or (minor is None and "face" in self.verify_mode.lower()):
            return STRANGER
        return OTHER

    @property
    def method(self) -> str:
        """face · fingerprint · card · other, from the minor code (else the verify mode)."""
        for minors, method in METHODS:
            if self.minor in minors:
                return method
        mode = self.verify_mode.lower()
        if self.kind in (PERSON, STRANGER) and mode in ("face", "fp", "card"):
            return {"face": "face", "fp": "fingerprint", "card": "card"}[mode]
        return "other" if self.kind in (PERSON, STRANGER) else ""

    @property
    def status(self) -> str:
        """The attendance status in lower case ("checkin", "breakout", "" …)."""
        return self.attendance_status.replace("_", "").lower()

    @property
    def wants(self) -> str:
        """What the terminal says the scan is: in · out · break · "" (it doesn't say)."""
        if self.status in CHECK_IN_STATUSES:
            return "in"
        if self.status in CHECK_OUT_STATUSES:
            return "out"
        if self.status in BREAK_STATUSES:
            return "break"
        return ""


@dataclass
class ParsedBody:
    events: list[DeviceEvent] = field(default_factory=list)
    pictures: list[bytes] = field(default_factory=list)
    problem: str = ""
    excerpt: str = ""


# Reading the body ------------------------------------------------------------------------------


def parse(content_type: str, body: bytes) -> ParsedBody:
    """Whatever a terminal posted, as events and pictures. Never raises for a bad body: the
    reason is in `problem` and the start of the part in `excerpt`."""
    content_type = (content_type or "").strip()
    body = body or b""
    mime = content_type.split(";", 1)[0].strip().lower()
    if not body.strip():
        return ParsedBody(problem="empty")
    if mime.startswith("multipart/") or _looks_multipart(body):
        return _parse_multipart(content_type, body)
    if mime == "application/x-www-form-urlencoded":
        return _parse_form(body)
    return _parse_document(body, mime)


def _parse_document(data: bytes, mime: str = "") -> ParsedBody:
    """A JSON or XML event (the part of a multipart body, or the whole body)."""
    if data.startswith(JPEG_MAGIC):
        return ParsedBody(pictures=[data], problem="no event")
    text = _text(data).strip().lstrip("﻿")
    try:
        if text.startswith(("{", "[")) or "json" in mime:
            return ParsedBody(events=_from_json(json.loads(text)))
        if text.startswith("<") or "xml" in mime:
            return ParsedBody(events=_from_xml(text))
    except (ValueError, ElementTree.ParseError, RecursionError) as exc:
        return ParsedBody(problem=f"unreadable: {type(exc).__name__}", excerpt=text[:MAX_EXCERPT])
    return ParsedBody(problem="unknown format", excerpt=text[:MAX_EXCERPT])


def _parse_form(body: bytes) -> ParsedBody:
    """`event_log=<json>` sent as a form: the first field that reads as an event."""
    try:
        fields = parse_qs(_text(body), keep_blank_values=False)
    except ValueError:
        fields = {}
    for values in fields.values():
        for value in values:
            parsed = _parse_document(value.encode())
            if parsed.events:
                return parsed
    return _parse_document(body)


@dataclass
class _Part:
    name: str
    filename: str
    content_type: str
    data: bytes


def _parse_multipart(content_type: str, body: bytes) -> ParsedBody:
    parts = _split_multipart(content_type, body)
    if not parts:
        return ParsedBody(problem="unreadable multipart", excerpt=_text(body[:MAX_EXCERPT]))
    result = ParsedBody()
    problems = []
    for part in parts:
        if _is_picture(part):
            if part.data.startswith(JPEG_MAGIC) or part.data[:4] in (b"\x89PNG", b"RIFF"):
                result.pictures.append(part.data)
            continue
        if not part.data.strip():
            continue
        parsed = _parse_document(part.data, part.content_type)
        result.events += parsed.events
        result.pictures += parsed.pictures
        if parsed.problem and not parsed.events:
            problems.append((parsed.problem, parsed.excerpt))
    if not result.events:
        problem, excerpt = problems[0] if problems else ("no event", "")
        result.problem, result.excerpt = problem, excerpt
    return result


def _looks_multipart(body: bytes) -> bool:
    head = body.lstrip()[:200]
    return head.startswith(b"--") and b"content-disposition" in head.lower()


def _boundary(content_type: str, body: bytes) -> bytes | None:
    match = re.search(r'boundary\s*=\s*"?([^";]+)"?', content_type, re.IGNORECASE)
    if match:
        return match.group(1).strip().encode("latin-1", "replace")
    # No boundary in the header (some firmware): the body's first line is the delimiter.
    first = body.lstrip().split(b"\n", 1)[0].strip()
    return first[2:] if first.startswith(b"--") and len(first) > 2 else None


def _split_multipart(content_type: str, body: bytes) -> list[_Part]:
    boundary = _boundary(content_type, body)
    if not boundary:
        return []
    parts = []
    for chunk in body.split(b"--" + boundary)[1:]:
        if chunk.startswith(b"--"):
            break  # the closing delimiter
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]
        head, data = _split_head(chunk)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        elif data.endswith(b"\n"):
            data = data[:-1]
        headers = _headers(head)
        disposition = headers.get("content-disposition", "")
        parts.append(
            _Part(
                name=_param(disposition, "name"),
                filename=_param(disposition, "filename"),
                content_type=headers.get("content-type", "").lower(),
                data=data,
            )
        )
    return parts


def _split_head(chunk: bytes) -> tuple[bytes, bytes]:
    """A part's headers and data, split at the first blank line (CRLF or bare LF)."""
    candidates = [
        (index, size)
        for index, size in ((chunk.find(b"\r\n\r\n"), 4), (chunk.find(b"\n\n"), 2))
        if index >= 0
    ]
    if not candidates:
        return b"", chunk
    index, size = min(candidates)
    head = chunk[:index]
    # A part without headers starts straight with its data (a JSON or XML event).
    if not HEADER_LINE.match(head.split(b"\n", 1)[0]):
        return b"", chunk
    return head, chunk[index + size :]


HEADER_LINE = re.compile(rb"^[A-Za-z][A-Za-z0-9-]*\s*:")


def _headers(head: bytes) -> dict[str, str]:
    headers = {}
    for line in _text(head).splitlines():
        name, colon, value = line.partition(":")
        if colon:
            headers[name.strip().lower()] = value.strip()
    return headers


def _param(header: str, name: str) -> str:
    match = re.search(rf'(?:^|;)\s*{name}\s*=\s*"([^"]*)"', header, re.IGNORECASE) or re.search(
        rf"(?:^|;)\s*{name}\s*=\s*([^;]*)", header, re.IGNORECASE
    )
    return match.group(1).strip() if match else ""


def _is_picture(part: _Part) -> bool:
    return (
        part.content_type.startswith("image/")
        or part.filename.lower().endswith((".jpg", ".jpeg", ".png"))
        or part.data.startswith(JPEG_MAGIC)
    )


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


# Events ----------------------------------------------------------------------------------------


def _from_json(value) -> list[DeviceEvent]:
    if isinstance(value, list):
        return [
            event for item in value[:20] if isinstance(item, dict) for event in _from_json(item)
        ]
    if not isinstance(value, dict):
        raise ValueError("not an event")
    return [_event(value)]


def _from_xml(text: str) -> list[DeviceEvent]:
    # Terminals never send a DTD: refusing one keeps entity tricks out of the parser.
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise ValueError("DTD in an event")
    root = ElementTree.fromstring(text)
    return [_event(_xml_dict(root))]


def _xml_dict(element) -> dict:
    """An element's children as a dict (namespaces dropped); repeated or nested ones as dicts."""
    found: dict = {}
    for child in element:
        tag = child.tag.rsplit("}", 1)[-1]
        found[tag] = _xml_dict(child) if len(child) else (child.text or "").strip()
    return found


def _event(data: dict) -> DeviceEvent:
    inner = data.get("AccessControllerEvent")
    inner = inner if isinstance(inner, dict) else {}
    # Some firmware flatten the fields onto the top level.
    merged = {**data, **inner}

    def text(*names) -> str:
        for name in names:
            value = merged.get(name)
            if value not in (None, "") and not isinstance(value, dict | list):
                return _clean(str(value))
        return ""

    def number(*names) -> int | None:
        for name in names:
            value = merged.get(name)
            if isinstance(value, bool) or value in (None, ""):
                continue
            try:
                return int(str(value).strip())
            except ValueError:
                continue
        return None

    moment, naive = _time(text("dateTime", "time"))
    employee_no = text("employeeNoString", "employeeNo", "employeeID")[:32]
    return DeviceEvent(
        event_type=text("eventType") or ("AccessControllerEvent" if inner else ""),
        device_time=moment,
        naive_time=naive,
        major=number("majorEventType", "major"),
        minor=number("subEventType", "minorEventType", "minor"),
        employee_no=employee_no,
        name=text("name", "personName")[:100],
        serial_no=_serial(number("serialNo")),
        attendance_status=text("attendanceStatus")[:16],
        verify_mode=text("currentVerifyMode", "verifyMode")[:48],
        user_type=text("userType")[:16],
        mac=text("macAddress")[:32],
        ip=text("ipAddress", "ipv4Address")[:45],
        device_id=text("deviceID", "serialNumber", "deviceSerialNo")[:64],
        device_name=text("deviceName")[:64],
        model=text("deviceModel", "model", "deviceType")[:64],
        pictures_number=number("picturesNumber") or 0,
        raw=cap(data),
    )


def _clean(value: str) -> str:
    """No control characters (some firmware pad names with NUL bytes), single spaces."""
    value = "".join(char for char in value if char >= " " or char == "\t")
    return " ".join(value.split())


def _serial(value: int | None) -> int | None:
    return value if value is not None and 0 <= value < 2**63 else None


TIME_PATTERN = re.compile(
    r"^(\d{4})-?(\d{2})-?(\d{2})[T ](\d{2}):?(\d{2}):?(\d{2})(?:[.,]\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$",
    re.IGNORECASE,
)


def _time(value: str) -> tuple[datetime | None, bool]:
    """The terminal's moment, and whether it came without an offset."""
    if not value:
        return None, False
    try:
        moment = datetime.fromisoformat(value.replace(" ", "T", 1))
    except ValueError:
        match = TIME_PATTERN.match(value.strip())
        if not match:
            return None, False
        year, month, day, hour, minute, second, offset = match.groups()
        offset = offset or ""
        if offset and offset.upper() != "Z" and ":" not in offset:
            offset = f"{offset[:3]}:{offset[3:]}"
        try:
            moment = datetime.fromisoformat(
                f"{year}-{month}-{day}T{hour}:{minute}:{second}{offset.replace('z', 'Z')}"
            )
        except ValueError:
            return None, False
    # A clock reset to its factory date (2000-01-01) is kept as it is: the service judges it.
    return moment, moment.tzinfo is None


def cap(data: dict) -> dict:
    """The event as we keep it: no long strings (pictures, templates), at most MAX_RAW_BYTES."""
    kept = _drop_long(data)
    if len(json.dumps(kept, ensure_ascii=False, default=str)) <= MAX_RAW_BYTES:
        return kept
    flat = {key: value for key, value in kept.items() if not isinstance(value, dict | list)}
    inner = kept.get("AccessControllerEvent")
    if isinstance(inner, dict):
        flat["AccessControllerEvent"] = {
            key: value for key, value in inner.items() if not isinstance(value, dict | list)
        }
    flat["truncated"] = True
    encoded = json.dumps(flat, ensure_ascii=False, default=str)
    if len(encoded) <= MAX_RAW_BYTES:
        return flat
    return {"truncated": True, "excerpt": encoded[: MAX_RAW_BYTES // 2]}


def _drop_long(value, depth: int = 0):
    if depth > 6:
        return None
    if isinstance(value, dict):
        return {
            str(key)[:64]: _drop_long(item, depth + 1) for key, item in list(value.items())[:80]
        }
    if isinstance(value, list):
        return [_drop_long(item, depth + 1) for item in value[:40]]
    if isinstance(value, str) and len(value) > MAX_RAW_STRING:
        return f"<{len(value)} characters left out>"
    return value
