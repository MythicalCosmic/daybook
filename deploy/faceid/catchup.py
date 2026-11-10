#!/usr/bin/env python3
"""Today's scans now, while a Face ID terminal still uploads its old ones.

A Hikvision terminal pointed at the server for the first time uploads every scan it ever stored,
oldest first, one or two a second: tens of thousands of old scans, often hours of them. The
server skips the old ones, but a scan made today waits behind them all. This helper runs on a
computer in the terminal's network (an installer's laptop, or the server itself when it sits
there): every few seconds it asks the terminal for its newest scans and sends each one, with its
picture, to the terminal's address on the server, exactly as the terminal itself posts them.
The server keeps each scan once, so when the terminal's own upload gets to them it adds
nothing. The helper stops by itself once the terminal has caught up.

    HIK_PASS=... python3 catchup.py --terminal 192.168.1.250
    python3 catchup.py --terminal 192.168.1.250 --check     # only tests both connections

On Windows: `py catchup.py --terminal 192.168.1.250` (it asks for the password).

The terminal's password comes from the environment variable HIK_PASS, or is asked for; it is
never printed or written anywhere. Python 3.9 or newer, nothing to install.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import hashlib
import http.client
import ipaddress
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

# The terminal's address on the server: filled in when this file is downloaded from the
# dashboard (Face ID, Terminals, the terminal); otherwise give it with --url.
DEVICE_URL = ""

VERSION = "1.0"
AGENT = f"faceid-catchup/{VERSION}"
# How often the server is asked how far the terminal's own upload has come, and how often that
# is said here.
STATUS_EVERY = 60.0
REPORT_EVERY = 300.0
# A search runs from a little before the newest scan sent (two scans can share a second) to well
# past now, so midnight never closes it.
OVERLAP = timedelta(minutes=2)
AHEAD = timedelta(days=1)
# Results per page (a terminal may give fewer), and at most this many pages per search.
PAGE = 30
MAX_PAGES = 40
TIMEOUT = 15
# A picture that can't be fetched this many times is left out: the scan goes without it.
PICTURE_TRIES = 3
# After a failed connection the wait doubles, up to this many seconds.
MAX_BACKOFF = 60.0
# A terminal clock this far from this computer's is worth a word.
CLOCK_TOLERANCE = timedelta(minutes=10)
JPEG = b"\xff\xd8\xff"
# Access control events (major 5); minor 0 asks for all of them.
MAJOR_ACCESS = 5
# Minor codes of a verification (face, finger, card), passed or failed: these are scans.
PASSED = frozenset({1, 2, 38, 40, 43, 46, 54, 57, 60, 63, 66, 69, 72, 75, 77})
FACE_FAILED = frozenset({55, 58, 61, 64, 67, 76, 78, 80})
# Fields of a search result the terminal's own post doesn't carry (the picture travels as a
# part, its link only works on this network).
LEFT_OUT = frozenset({"major", "minor", "time", "pictureURL", "picURL"})
# HIK_PASS left as the dashboard shows it: ask instead.
PLACEHOLDERS = frozenset({"", "…", "...", "<password>"})
DEVICE_PATH = re.compile(r"/api/v1/devices/hik/[A-Za-z0-9_-]{16,64}/?$")

_STOP = threading.Event()


def stop() -> None:
    """Ask a running catch-up to stop at its next pause (as Ctrl+C does)."""
    _STOP.set()


def say(text: str = "") -> None:
    print(text, flush=True)


def stamp() -> str:
    return time.strftime("%H:%M:%S")


def human(number) -> str:
    """12040 as "12 040"."""
    try:
        return f"{int(number):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


class Stop(Exception):
    """Stop now and say why: a wrong address, a refused sign-in."""


class Unreachable(Exception):
    """A connection that failed this time; try again later."""

    def __init__(self, where: str, reason: str):
        super().__init__(f"Can't reach {where} ({reason})")
        self.where, self.reason = where, reason


class Refused(Exception):
    """An answer other than the one asked for (an HTTP status)."""

    def __init__(self, status: int, body: bytes = b""):
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        found = re.search(r"statusString\"?\s*[:>]\s*\"?([^\"<,}]+)", text)
        self.status, self.detail = status, found.group(1).strip() if found else ""
        super().__init__(f"HTTP {status}" + (f": {self.detail}" if self.detail else ""))


def reason(error: BaseException) -> str:
    """A connection problem in a few words."""
    inner = getattr(error, "reason", error)
    if isinstance(inner, (TimeoutError, OSError)) and "timed out" in str(inner):
        return "timed out"
    if isinstance(inner, ConnectionRefusedError):
        return "connection refused"
    if isinstance(inner, ssl.SSLCertVerificationError):
        return "its certificate can't be checked"
    text = str(getattr(inner, "strerror", None) or inner).strip()
    return text[:120] or type(inner).__name__


def tls_problem(error: BaseException | None) -> bool:
    """HTTPS that can't work from here: a certificate this computer can't check, a TLS failure,
    or nothing listening for HTTPS."""
    inner = getattr(error, "reason", error)
    return isinstance(inner, (ssl.SSLError, ConnectionRefusedError))


# Times -------------------------------------------------------------------------------------


def parse_time(value) -> datetime | None:
    """An ISAPI time ("2026-11-10T09:41:07+05:00", "...Z", "...+0500"), aware when it carries an
    offset; None when it isn't one."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace(" ", "T", 1)
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    # Fractions of a second: Python 3.9 reads only 3 or 6 digits.
    text = re.sub(r"(T\d{2}:\d{2}:\d{2})\.\d+", r"\1", text)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def posix_offset(zone: str) -> timezone | None:
    """A terminal's POSIX time zone ("CST-8:00:00": west of Greenwich is positive) as an offset
    (UTC+08:00)."""
    found = re.match(r"^\s*[A-Za-z]{3,}([+-]?)(\d{1,2})(?::(\d{2}))?", zone or "")
    if not found:
        return None
    sign, hours, minutes = found.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
    if delta >= timedelta(hours=24):
        return None
    return timezone(delta if sign == "-" else -delta)


def isapi_time(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def shown(value) -> str:
    """An ISO moment from the server as "2023-03-02 09:15"."""
    return value[:16].replace("T", " ") if isinstance(value, str) and value else "—"


class TerminalClock:
    """The terminal's own time: its reading kept as the difference to this computer's clock,
    with its UTC offset, so every search asks in the terminal's own terms whatever its clock
    says. Without a reading, this computer's time and offset."""

    def __init__(self, reading: datetime | None = None):
        here = datetime.now(timezone.utc)
        self.measured = reading is not None
        if reading is None:
            self.zone, self.skew = here.astimezone().tzinfo, timedelta(0)
        else:
            self.zone, self.skew = reading.tzinfo, reading - here

    def now(self) -> datetime:
        return (datetime.now(timezone.utc) + self.skew).astimezone(self.zone)

    def wall(self, moment: datetime) -> datetime:
        """`moment` in the terminal's zone (a time without an offset is taken as it stands)."""
        return moment.replace(tzinfo=self.zone) if moment.tzinfo is None else moment

    def off_by(self) -> timedelta:
        """How far the terminal's date and clock are from this computer's. The server reads a
        scan's date and clock in the organization's time zone, whatever offset the terminal
        adds, so the wall clocks are compared."""
        if not self.measured:
            return timedelta(0)
        return self.now().replace(tzinfo=None) - datetime.now()


# The terminal ------------------------------------------------------------------------------


def terminal_base(address: str) -> str:
    """ "192.168.1.250", "192.168.1.250:8080" or "http://192.168.1.250" as its base URL."""
    text = (address or "").strip().rstrip("/")
    if "://" not in text:
        text = f"http://{text}"
    parts = urlsplit(text)
    problem = f"{address!r} isn't a terminal's address (e.g. 192.168.1.250)."
    try:
        port = parts.port
    except ValueError as exc:
        raise Stop(problem) from exc
    if parts.scheme not in ("http", "https") or not parts.hostname or port == 0:
        raise Stop(problem)
    return f"{parts.scheme}://{parts.netloc}"


def read_challenge(headers) -> dict | None:
    """A 401's Digest challenge (else Basic, else None)."""
    offered = headers.get_all("WWW-Authenticate") if headers is not None else None
    basic = None
    for value in offered or []:
        scheme, _space, rest = value.strip().partition(" ")
        if scheme.lower() == "digest":
            try:
                items = urllib.request.parse_keqv_list(urllib.request.parse_http_list(rest))
            except ValueError:
                return None
            return {"scheme": "digest", **{key.lower(): item for key, item in items.items()}}
        if scheme.lower() == "basic":
            basic = {"scheme": "basic"}
    return basic


def refused_sign_in(user: str, body: bytes) -> str:
    """What a refused sign-in means, with the tries left (Hikvision says so in the answer)."""
    text = body.decode("utf-8", "replace") if body else ""
    locked = re.search(r"<lockStatus>\s*lock\s*</lockStatus>", text, re.IGNORECASE)
    unlock = re.search(r"<unlockTime>(\d+)</unlockTime>", text)
    if locked and unlock and int(unlock.group(1)) > 0:
        minutes = max(1, round(int(unlock.group(1)) / 60))
        return (
            "The terminal has locked its sign-in after wrong passwords: try again in about "
            f"{minutes} min."
        )
    left = re.search(r"<retryLoginTime>(\d+)</retryLoginTime>", text)
    tries = f" ({left.group(1)} tries left before it locks)" if left else ""
    return (
        f"The terminal refused the user {user!r} with this password{tries}. Check both and run "
        "this again: a few wrong tries in a row lock the terminal's sign-in for about half an "
        "hour."
    )


class Terminal:
    """The terminal's ISAPI. Its digest sign-in is done here, one answer to one challenge per
    request: a wrong password costs a single failed sign-in and stops everything, never the
    burst of retries that locks a terminal for half an hour."""

    def __init__(self, address: str, user: str, password: str):
        self.base = terminal_base(address)
        parts = urlsplit(self.base)
        self.address = parts.netloc
        self.host = parts.hostname or ""
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.user, self.password = user, password
        self.mac = ""
        # The terminal is on this network: never through a proxy. Its HTTPS certificate is its
        # own (self-signed), so it isn't checked.
        handlers: list = [urllib.request.ProxyHandler({})]
        if parts.scheme == "https":
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self.opener = urllib.request.build_opener(*handlers)

    def ip(self) -> str:
        """The terminal's address when it is an IP address (what its own posts say)."""
        try:
            return str(ipaddress.ip_address(self.host))
        except ValueError:
            return ""

    def _send(self, method: str, url: str, body: bytes | None, headers: dict):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=TIMEOUT) as answer:
                return answer.status, answer.headers, answer.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.headers, error.read()
            finally:
                error.close()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise Unreachable("the terminal", reason(error)) from error

    def call(self, method: str, target: str, body: bytes | None = None, kind: str = "") -> bytes:
        """The body of a 200 answer to `target` (a path, or a link on the terminal). Raises Stop
        when the sign-in is refused, Unreachable when the connection fails, Refused for any other
        answer."""
        parts = urlsplit(target)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        url = self.base + path
        challenge = None
        for _attempt in range(2):
            headers = {"User-Agent": AGENT, "Accept": "*/*"}
            if kind:
                headers["Content-Type"] = kind
            if challenge is not None:
                headers["Authorization"] = self.authorization(challenge, method, path)
            status, answer, data = self._send(method, url, body, headers)
            if status != 401:
                break
            if challenge is not None:
                raise Stop(refused_sign_in(self.user, data))
            challenge = read_challenge(answer)
            if challenge is None:
                raise Stop(refused_sign_in(self.user, data))
        if status != 200:
            raise Refused(status, data)
        return data

    def authorization(self, challenge: dict, method: str, uri: str) -> str:
        if challenge["scheme"] == "basic":
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            return f"Basic {token}"
        algorithm = challenge.get("algorithm") or "MD5"
        name = "sha256" if algorithm.upper().startswith("SHA-256") else "md5"

        def digest(text: str) -> str:
            return hashlib.new(name, text.encode("utf-8"), usedforsecurity=False).hexdigest()

        realm, nonce = challenge.get("realm", ""), challenge.get("nonce", "")
        cnonce, count = os.urandom(8).hex(), "00000001"
        secret = digest(f"{self.user}:{realm}:{self.password}")
        if algorithm.upper().endswith("-SESS"):
            secret = digest(f"{secret}:{nonce}:{cnonce}")
        target = digest(f"{method}:{uri}")
        qops = [item.strip().lower() for item in challenge.get("qop", "").split(",")]
        if "auth" in qops:
            response = digest(f"{secret}:{nonce}:{count}:{cnonce}:auth:{target}")
        else:
            response = digest(f"{secret}:{nonce}:{target}")
        fields = [
            f'username="{self.user}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'response="{response}"',
        ]
        if challenge.get("opaque"):
            fields.append(f'opaque="{challenge["opaque"]}"')
        fields.append(f'algorithm="{algorithm}"')
        if "auth" in qops:
            fields.append(f'qop=auth, nc={count}, cnonce="{cnonce}"')
        return "Digest " + ", ".join(fields)

    def info(self) -> dict:
        """Its model, firmware and MAC address; the first request, so it also tests the sign-in."""
        text = self.call("GET", "/ISAPI/System/deviceInfo").decode("utf-8", "replace")
        found = {}
        for tag in ("deviceName", "model", "serialNumber", "macAddress", "firmwareVersion"):
            match = re.search(rf"<{tag}>([^<]*)</{tag}>", text)
            if match and match.group(1).strip():
                found[tag] = match.group(1).strip()
        self.mac = found.get("macAddress", "")
        return found

    def clock(self) -> datetime | None:
        """Its date and clock now, with its UTC offset (None when it doesn't say)."""
        try:
            text = self.call("GET", "/ISAPI/System/time").decode("utf-8", "replace")
        except Refused:
            return None
        local = re.search(r"<localTime>([^<]+)</localTime>", text)
        moment = parse_time(local.group(1)) if local else None
        if moment is None or moment.tzinfo is not None:
            return moment
        zone = re.search(r"<timeZone>([^<]+)</timeZone>", text)
        offset = posix_offset(zone.group(1)) if zone else None
        return moment.replace(tzinfo=offset or datetime.now(timezone.utc).astimezone().tzinfo)

    def events(self, start: datetime, end: datetime) -> list[dict]:
        """Every access event between `start` and `end`, page after page."""
        search, position, found = uuid.uuid4().hex[:16], 0, []
        for _page in range(MAX_PAGES):
            condition = {
                "searchID": search,
                "searchResultPosition": position,
                "maxResults": PAGE,
                "major": MAJOR_ACCESS,
                "minor": 0,
                "startTime": isapi_time(start),
                "endTime": isapi_time(end),
            }
            data = self.call(
                "POST",
                "/ISAPI/AccessControl/AcsEvent?format=json",
                json.dumps({"AcsEventCond": condition}).encode(),
                "application/json",
            )
            try:
                block = json.loads(data.decode("utf-8", "replace")).get("AcsEvent") or {}
                rows = [row for row in block.get("InfoList") or [] if isinstance(row, dict)]
            except (ValueError, AttributeError):
                raise Refused(200, b"an answer that isn't an event list") from None
            found.extend(rows)
            position += len(rows)
            if str(block.get("responseStatusStrg", "")).upper() != "MORE" or not rows:
                break
        return found

    def picture(self, link: str) -> bytes | None:
        """A scan's picture (None: there is none). The link names the terminal by the address it
        knows itself by; it is fetched from the address used here."""
        if not isinstance(link, str) or not urlsplit(link.strip()).path:
            return None
        try:
            data = self.call("GET", link.strip())
        except Refused:
            return None
        return data if data.startswith(JPEG) else None


# Events ------------------------------------------------------------------------------------


def serial_of(event: dict) -> int | None:
    try:
        number = int(str(event.get("serialNo", "")).strip())
    except ValueError:
        return None
    return number if number >= 0 else None


def number_of(event: dict) -> str:
    number = str(event.get("employeeNoString") or event.get("employeeNo") or "").strip()
    return number if number.lstrip("0") else ""


def minor_of(event: dict) -> int | None:
    try:
        return int(event.get("minor"))
    except (TypeError, ValueError):
        return None


def is_scan(event: dict) -> bool:
    """A face, finger or card at the terminal (not a door or an alarm)."""
    minor = minor_of(event)
    return minor in PASSED or minor in FACE_FAILED or bool(number_of(event) or event.get("name"))


def who(event: dict) -> str:
    name = " ".join(str(event.get("name") or "").split())
    if name:
        return name
    number = number_of(event)
    return f"No {number}" if number else "unknown face"


def terminal_post(event: dict, terminal: Terminal, picture: bytes | None) -> tuple[bytes, str]:
    """(body, content type) of the event as the terminal's own HTTP Listening posts it: the event
    JSON (`event_log`), then the picture (`Picture`)."""
    inner = {"majorEventType": event.get("major", MAJOR_ACCESS), "subEventType": event.get("minor")}
    inner.update((key, value) for key, value in event.items() if key not in LEFT_OUT)
    push = {
        "ipAddress": terminal.ip(),
        "portNo": terminal.port,
        "protocol": "HTTP",
        "macAddress": terminal.mac,
        "channelID": 1,
        "dateTime": event.get("time"),
        "activePostCount": 1,
        "eventType": "AccessControllerEvent",
        "eventState": "active",
        "eventDescription": "Access Controller Event",
        "AccessControllerEvent": inner,
    }
    push = {key: value for key, value in push.items() if value not in ("", None)}
    boundary = f"MIME_boundary_{uuid.uuid4().hex}"
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="event_log"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        + json.dumps(push, ensure_ascii=False).encode("utf-8")
        + b"\r\n"
    ]
    if picture:
        parts.append(
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="Picture"; filename="Picture.jpg"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode()
            + picture
            + b"\r\n"
        )
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


# The server --------------------------------------------------------------------------------

WRONG_URL = (
    "The server doesn't know this terminal's address (404): its code may have changed. Download "
    "the helper again from the terminal's page (Face ID › Terminals › Setup), or give the URL "
    "shown there with --url."
)


def check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or not DEVICE_PATH.search(url):
        raise Stop(
            "That isn't a terminal's address on the server: it looks like "
            "https://<server>/api/v1/devices/hik/<code>/ (the terminal's Setup page shows it)."
        )
    return url


class Server:
    """The terminal's address on the server, where its own upload goes too."""

    def __init__(self, url: str):
        self.url = check_url(url)
        # The server is out there: this computer's proxy settings apply.
        self.opener = urllib.request.build_opener()
        self.downgraded = ""

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc

    def _send(self, method: str, body: bytes | None = None, kind: str = ""):
        headers = {"User-Agent": AGENT, "Accept": "application/json"}
        if kind:
            headers["Content-Type"] = kind
        request = urllib.request.Request(self.url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as answer:
                return answer.status, answer.headers, answer.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.headers, error.read()
            finally:
                error.close()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise Unreachable("the server", reason(error)) from error

    def status(self) -> dict:
        """What the address answers: OK, and how far the terminal's own upload has come."""
        status, _headers, data = self._send("GET")
        if status == 404:
            raise Stop(WRONG_URL)
        if status != 200:
            raise Unreachable("the server", f"HTTP {status}")
        try:
            answer = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            answer = None
        if not isinstance(answer, dict) or str(answer.get("statusCode")) != "200":
            raise Refused(status, b"an answer that isn't a terminal address's")
        return answer

    def connect(self) -> dict:
        """The first answer. An HTTPS address this computer can't use (a certificate it can't
        check, or no HTTPS there) is tried once over plain HTTP, the way the terminal itself
        posts; the address with a port of its own isn't."""
        try:
            return self.status()
        except Unreachable as problem:
            parts = urlsplit(self.url)
            if parts.scheme != "https" or parts.port or not tls_problem(problem.__cause__):
                raise
            secure = self.url
            self.url = "http://" + secure[len("https://") :]
            try:
                answer = self.status()
            except (Unreachable, Refused, Stop):
                self.url = secure
                raise problem from None
            self.downgraded = problem.reason
            return answer

    def post(self, body: bytes, kind: str) -> tuple[int, float]:
        """(status, seconds to wait): 200 delivered; 429 wait and send it again; 404 stops."""
        status, headers, _data = self._send("POST", body, kind)
        if status == 404:
            raise Stop(WRONG_URL)
        if status == 429:
            try:
                wait = float(headers.get("Retry-After") or 5)
            except ValueError:
                wait = 5.0
            return status, min(max(wait, 1.0), 120.0)
        if status >= 500:
            raise Unreachable("the server", f"HTTP {status}")
        return status, 0.0


def history_line(history) -> str:
    """How far the terminal's own upload of its stored scans has come, as the server says."""
    if not isinstance(history, dict):
        return (
            "The server doesn't say how far the terminal's own upload has come: stop this with "
            "Ctrl+C once today's scans show."
        )
    skipped, until = human(history.get("skipped")), shown(history.get("until"))
    if history.get("active"):
        return f"The terminal is still sending old scans: {skipped} skipped so far, up to {until}."
    if history.get("skipped"):
        return f"The terminal's old scans are done ({skipped} skipped, up to {until})."
    return "The terminal hasn't sent old scans so far."


# Catching up -------------------------------------------------------------------------------


class CatchUp:
    """Ask the terminal for new scans every few seconds and send each to the server, until the
    terminal's own upload has caught up (the server says so), the hours are up, or Ctrl+C."""

    def __init__(self, terminal: Terminal, server: Server, *, since, interval, hours):
        self.terminal, self.server = terminal, server
        self.since = timedelta(minutes=since)
        self.interval = interval
        self.deadline = time.monotonic() + hours * 3600
        self.hours = hours
        self.clock = TerminalClock()
        self.cutoff: datetime | None = None
        self.last_serial: int | None = None
        self.newest: datetime | None = None
        self.picture_tries: dict[int, int] = {}
        self.sent = 0
        self.history_seen = False
        self.next_status = 0.0
        self.next_report = 0.0
        self.trouble = ""
        self.failures = 0

    # Starting

    def start(self) -> int:
        try:
            info = self.terminal.info()
        except Unreachable as problem:
            raise Stop(
                f"Can't reach the terminal at {self.terminal.address} ({problem.reason}): is this "
                "computer on the terminal's network, and is that its address?"
            ) from None
        except Refused as problem:
            raise Stop(f"The terminal at {self.terminal.address} answered {problem}.") from None
        try:
            self.clock = TerminalClock(self.terminal.clock())
        except Unreachable as problem:
            raise Stop(f"The terminal stopped answering ({problem.reason}).") from None
        try:
            answer = self.server.connect()
        except Unreachable as problem:
            raise Stop(f"Can't reach the server {self.server.host} ({problem.reason}).") from None
        except Refused:
            raise Stop(f"{self.server.host} doesn't answer like a terminal's address.") from None
        say(f"Face ID catch-up: terminal {self.terminal.address}, server {self.server.host}")
        say(f"  Signed in to the terminal as {self.terminal.user} ({describe(info)}).")
        warning = clock_warning(self.clock)
        if warning:
            say(f"  {warning}")
        if self.server.downgraded:
            say(f"  {downgrade_note(self.server.downgraded)}")
        history = answer.get("history")
        self.history_seen = isinstance(history, dict) and bool(history.get("active"))
        say(f"  {history_line(history)}")
        minutes = round(self.since.total_seconds() / 60)
        say(
            f"Sending the scans of the last {minutes} min, then each new one as it happens. "
            "Ctrl+C stops."
        )
        say()
        now = self.clock.now()
        self.cutoff = now - self.since
        self.next_status = time.monotonic() + STATUS_EVERY
        self.next_report = time.monotonic() + REPORT_EVERY
        return self.run()

    def run(self) -> int:
        try:
            while not _STOP.is_set():
                if time.monotonic() >= self.deadline:
                    say(
                        f"{stamp()}  {self.hours:g} hours are up: stopping ({self.summary()}). "
                        "If the terminal is still sending old scans, start it again."
                    )
                    return 0
                self.poll()
                if self.caught_up():
                    return 0
                self.pause(self.backoff() if self.trouble else self.interval)
        except KeyboardInterrupt:
            say()
        say(f"{stamp()}  Stopped ({self.summary()}).")
        return 0

    def summary(self) -> str:
        return "1 scan sent" if self.sent == 1 else f"{human(self.sent)} scans sent"

    def pause(self, seconds: float) -> None:
        """Sleep in short steps, so Ctrl+C and `stop()` act at once on every system."""
        end = time.monotonic() + seconds
        while not _STOP.is_set():
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.25, left))

    def backoff(self) -> float:
        return min(self.interval * 2 ** min(self.failures, 6), MAX_BACKOFF)

    # Problems, said once

    def troubled(self, text: str) -> None:
        self.failures += 1
        if text != self.trouble:
            say(f"{stamp()}  {text}: trying again.")
        self.trouble = text

    def recovered(self) -> None:
        if self.trouble:
            say(f"{stamp()}  Working again.")
        self.trouble, self.failures = "", 0

    # Polling

    def poll(self) -> None:
        """One search, from a little before the newest scan sent (the terminal's clock may have
        been set back since: then from its now), and everything new in it sent, oldest first. A
        search cut short goes on from there next time."""
        try:
            now = self.clock.now()
            start = self.cutoff
            if self.newest is not None:
                start = (min(self.newest, now) - OVERLAP).astimezone(self.clock.zone)
            found = self.terminal.events(start, now + AHEAD)
            fresh = sorted((event for event in found if self.is_new(event)), key=serial_of)
            for event in fresh:
                if not self.send(event):
                    return
            self.recovered()
        except Stop:
            raise
        except Unreachable as problem:
            self.troubled(str(problem))
        except Refused as problem:
            self.troubled(f"The terminal answered {problem}")
        except Exception as problem:  # an answer nobody foresaw: keep going, say it once
            self.troubled(f"Something unexpected ({type(problem).__name__}: {problem})")

    def is_new(self, event: dict) -> bool:
        """Newer than every scan sent; before the first, nothing older than the start."""
        number = serial_of(event)
        if number is None:
            return False
        if self.last_serial is not None:
            return number > self.last_serial
        moment = parse_time(event.get("time"))
        return moment is None or self.clock.wall(moment) >= self.cutoff

    def send(self, event: dict) -> bool:
        """Send one event with its picture: True once the server has it (or turned it down for
        good), False when stopping. Raises Unreachable to try again later."""
        number = serial_of(event)
        picture = None
        if event.get("pictureURL"):
            try:
                picture = self.terminal.picture(event["pictureURL"])
            except Unreachable:
                tries = self.picture_tries.get(number, 0) + 1
                self.picture_tries[number] = tries
                if tries < PICTURE_TRIES:
                    raise
        result, waits = "sent", 0
        while True:
            body, kind = terminal_post(event, self.terminal, picture)
            status, wait = self.server.post(body, kind)
            if status == 429:
                # The server asks to slow down: wait as long as it says, then the same scan.
                waits += 1
                if waits > 5:
                    raise Unreachable("the server", "too many requests")
                self.pause(wait)
                if _STOP.is_set():
                    return False
                continue
            if status == 413 and picture:
                picture, result = None, "sent without its picture (too big)"
                continue
            if status != 200:
                result = f"not taken by the server (HTTP {status})"
            break
        if picture is None and event.get("pictureURL") and result == "sent":
            result = "sent without its picture"
        self.picture_tries.pop(number, None)
        self.last_serial = number
        moment = parse_time(event.get("time"))
        if moment is not None:
            moment = self.clock.wall(moment)
            self.newest = moment if self.newest is None else max(self.newest, moment)
        if is_scan(event):
            self.sent += 1
            when = moment.strftime("%H:%M:%S") if moment is not None else stamp()
            say(f"{when}  {who(event)[:40]:<28} {result}")
        return True

    # The terminal's own upload

    def caught_up(self) -> bool:
        """Every minute: how far the terminal's own upload has come (said every few minutes),
        and the terminal's clock read again. True once its old scans were coming during this run
        and have stopped (the server calls them done after 10 quiet minutes)."""
        if time.monotonic() < self.next_status:
            return False
        self.next_status = time.monotonic() + STATUS_EVERY
        try:
            reading = self.terminal.clock()
            if reading is not None:
                self.clock = TerminalClock(reading)
        except (Unreachable, Refused):
            pass
        try:
            history = self.server.status().get("history")
        except (Unreachable, Refused):
            return False
        if not isinstance(history, dict):
            return False
        if history.get("active"):
            self.history_seen = True
            if time.monotonic() >= self.next_report:
                self.next_report = time.monotonic() + REPORT_EVERY
                say(f"{stamp()}  {history_line(history)}")
            return False
        if not self.history_seen:
            return False
        say(
            f"{stamp()}  The terminal's own upload has caught up "
            f"({human(history.get('skipped'))} old scans skipped): its scans arrive live now. "
            f"Stopping ({self.summary()})."
        )
        return True


def describe(info: dict) -> str:
    model = info.get("model") or info.get("deviceName") or "Hikvision terminal"
    firmware = info.get("firmwareVersion")
    return f"{model}, firmware {firmware}" if firmware else model


def clock_warning(clock: TerminalClock) -> str:
    off = clock.off_by()
    if abs(off) <= CLOCK_TOLERANCE:
        return ""
    there = clock.now().strftime("%Y-%m-%d %H:%M")
    here = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"The terminal's clock says {there}, this computer's {here}. If the terminal's is wrong, "
        "set its date and time (Configuration › System › Time Settings, with NTP): otherwise its "
        "scans count at the wrong time, or are skipped as old."
    )


def downgrade_note(problem: str) -> str:
    return (
        f"HTTPS to the server doesn't work from this computer ({problem}): the scans go over "
        "plain HTTP, the way the terminal itself sends them."
    )


# --check -----------------------------------------------------------------------------------


def check(terminal: Terminal, server: Server) -> int:
    """Test the terminal's sign-in and the server's address, and say how each went."""
    say("Checking the terminal and the server...")
    working = True
    try:
        info = terminal.info()
        clock = TerminalClock(terminal.clock())
        now = clock.now()
        terminal.events(now - timedelta(minutes=1), now + AHEAD)
        say(
            f"  Terminal {terminal.address}: signed in as {terminal.user} ({describe(info)}); "
            "its scans can be read."
        )
        warning = clock_warning(clock)
        if warning:
            say(f"  {warning}")
    except Stop as problem:
        say(f"  Terminal {terminal.address}: {problem}")
        working = False
    except Unreachable as problem:
        say(
            f"  Terminal {terminal.address}: can't reach it ({problem.reason}). Is this computer "
            "on the terminal's network, and is that its address?"
        )
        working = False
    except Refused as problem:
        say(f"  Terminal {terminal.address}: it answered {problem}.")
        working = False
    try:
        answer = server.connect()
        say(f"  Server {server.host}: the terminal's address answers.")
        if server.downgraded:
            say(f"  {downgrade_note(server.downgraded)}")
        say(f"  {history_line(answer.get('history'))}")
    except Stop as problem:
        say(f"  Server {server.host}: {problem}")
        working = False
    except Unreachable as problem:
        say(f"  Server {server.host}: can't reach it ({problem.reason}).")
        working = False
    except Refused:
        say(f"  Server {server.host}: it doesn't answer like a terminal's address.")
        working = False
    if working:
        say("Both work: run it again without --check to send today's scans.")
    else:
        say("Fix what's above and check again.")
    return 0 if working else 1


# The command -------------------------------------------------------------------------------


def arguments() -> argparse.ArgumentParser:
    def positive(low: float, high: float):
        def read(text: str) -> float:
            try:
                value = float(text)
            except ValueError:
                raise argparse.ArgumentTypeError(f"{text!r} isn't a number") from None
            if not low <= value <= high:
                raise argparse.ArgumentTypeError(f"give {low:g} to {high:g}")
            return value

        return read

    parser = argparse.ArgumentParser(
        prog="catchup.py",
        description=(
            "Send a Face ID terminal's newest scans to the server while the terminal still "
            "uploads its old ones. Stops by itself once the terminal has caught up. The "
            "terminal's password comes from HIK_PASS, or is asked for."
        ),
    )
    parser.add_argument(
        "--terminal",
        required=True,
        metavar="ADDRESS",
        help="the terminal's address in its network, e.g. 192.168.1.250 (or host:port)",
    )
    parser.add_argument("--user", default="admin", help="the terminal's user (default: admin)")
    parser.add_argument(
        "--url",
        default="",
        help="the terminal's address on the server (filled in when downloaded from the dashboard)",
    )
    parser.add_argument(
        "--since",
        type=positive(0, 24 * 60),
        default=10.0,
        metavar="MINUTES",
        help="start with the scans of the last N minutes, never older (default: 10)",
    )
    parser.add_argument(
        "--interval",
        type=positive(0.5, 300),
        default=3.0,
        metavar="SECONDS",
        help="ask the terminal for new scans this often (default: 3)",
    )
    parser.add_argument(
        "--hours",
        type=positive(0.001, 72),
        default=12.0,
        help="stop after this long at the latest (default: 12)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only test the terminal's sign-in and the server's address, then exit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # A name the console can't show comes out as "?", never as a crash.
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    _STOP.clear()
    args = arguments().parse_args(argv)
    url = (args.url or DEVICE_URL).strip()
    if not url:
        say(
            "Give the terminal's address on the server with --url (Face ID › Terminals › the "
            "terminal › Setup), or download this helper from there: it comes with it filled in."
        )
        return 2
    try:
        server = Server(url)
        password = os.environ.get("HIK_PASS", "")
        if password.strip() in PLACEHOLDERS:
            try:
                password = getpass.getpass(f"Password of {args.user} on the terminal: ")
            except (EOFError, KeyboardInterrupt):
                say()
                return 1
        if not password:
            say("No password: set HIK_PASS, or type it when asked.")
            return 2
        terminal = Terminal(args.terminal, args.user, password)
        if args.check:
            return check(terminal, server)
        return CatchUp(
            terminal, server, since=args.since, interval=args.interval, hours=args.hours
        ).start()
    except Stop as problem:
        say(str(problem))
        return 1
    except (Unreachable, Refused) as problem:
        say(f"{problem}.")
        return 1
    except KeyboardInterrupt:
        say()
        return 1


if __name__ == "__main__":
    sys.exit(main())
