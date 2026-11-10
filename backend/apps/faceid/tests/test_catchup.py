"""The catch-up helper (deploy/faceid/catchup.py) end to end: a fake ISAPI terminal on 127.0.0.1
(fake_terminal.py), the real server under Django's live_server, and the script itself, imported
from its path and run as the installer runs it."""

import ast
import importlib.util
import json
import threading
import time
from datetime import datetime, timedelta
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from apps.faceid.models import FaceDevice, FaceEvent, FaceLink
from apps.faceid.tests import fake_terminal, samples
from apps.faceid.tests.fake_terminal import FakeTerminal

SCRIPT = Path(settings.BASE_DIR).parent / "deploy" / "faceid" / "catchup.py"
PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def load():
    spec = importlib.util.spec_from_file_location("faceid_catchup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def catchup(monkeypatch):
    """The script, fresh, asking the server every 0.3 s and saying the history each time; the
    terminal's password in HIK_PASS, and no proxy between it and 127.0.0.1."""
    module = load()
    module.STATUS_EVERY, module.REPORT_EVERY = 0.3, 0.0
    monkeypatch.setenv("HIK_PASS", fake_terminal.PASSWORD)
    for name in PROXIES:
        monkeypatch.delenv(name, raising=False)
    yield module
    module.stop()


@pytest.fixture
def terminal():
    with FakeTerminal() as fake:
        yield fake


def wait_for(condition, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError("waited in vain")


def run_in_background(module, *args):
    result = []
    thread = threading.Thread(target=lambda: result.append(module.main(list(args))), daemon=True)
    thread.start()
    return thread, result


def serials(device) -> set[int]:
    return set(FaceEvent.objects.filter(device=device).values_list("serial_no", flat=True))


@pytest.mark.django_db(transaction=True)
def test_todays_scans_reach_the_server_while_the_terminal_uploads_its_history(
    staff, chilonzor, catchup, terminal, live_server, capsys
):
    """A terminal added three hours ago is still uploading 2023: the helper sends the scans of
    the last 10 minutes and each new one at once, with their snapshots, never anything older;
    the terminal's own upload reaching them adds nothing; once its history goes quiet the helper
    stops by itself."""
    company = chilonzor.company
    device = FaceDevice.objects.create(company=company, branch=chilonzor, name="Kirish")
    FaceDevice.objects.filter(pk=device.pk).update(
        created_at=timezone.now() - timedelta(hours=3),
        history_skipped=12040,
        history_until=datetime.fromisoformat("2023-03-02T09:15:00+05:00"),
        history_seen_at=timezone.now(),
    )
    for number, person in (("12", staff.ali), ("13", staff.vali)):
        FaceLink.objects.create(company=company, employee_no=number, membership=person)
    now = terminal.now()
    terminal.add(100, now - timedelta(minutes=60), number="12", name="Alisher Valiyev")
    first = terminal.add(101, now - timedelta(minutes=5), number="12", name="Alisher Valiyev")
    terminal.add(102, now - timedelta(minutes=4), minor=76)  # a face the terminal didn't know
    terminal.add(103, now - timedelta(minutes=3), minor=21, picture=False)  # the door opened
    address = f"{live_server.url}/api/v1/devices/hik/{device.token}/"

    thread, result = run_in_background(
        catchup, "--terminal", terminal.address, "--url", address, "--interval", "0.5"
    )
    wait_for(lambda: {101, 102, 103} <= serials(device))
    terminal.add(104, terminal.now(), number="13", name="Vali Karimov")  # scanned just now
    wait_for(lambda: 104 in serials(device))
    device.refresh_from_db()
    # The helper's posts carry the terminal's address and MAC, like the terminal's own.
    assert device.ip == "127.0.0.1" and device.mac == "e8:a0:ed:12:34:56"

    # The terminal's own upload gets to scan 101: the server has it already.
    push = samples.k1t341amf(number="12", name="Alisher Valiyev", serial=101, at=first["time"])
    content_type, body = samples.multipart(push, part="event_log", picture=samples.jpeg())
    own = Client().post(
        f"/api/v1/devices/hik/{device.token}/", data=body, content_type=content_type
    )
    assert own.status_code == 200
    assert FaceEvent.objects.filter(device=device, serial_no=101).count() == 1

    # Ten quiet minutes since the last old scan: the terminal has caught up.
    FaceDevice.objects.filter(pk=device.pk).update(
        history_seen_at=timezone.now() - timedelta(minutes=11)
    )
    thread.join(timeout=20)
    assert not thread.is_alive() and result == [0]

    assert serials(device) == {101, 102, 103, 104}  # never 100: an hour before the start
    events = {event.serial_no: event for event in FaceEvent.objects.filter(device=device)}
    assert events[101].membership == staff.ali and events[101].photo
    assert events[102].kind == "stranger" and events[102].photo
    assert events[103].kind == "other" and not events[103].photo
    assert events[104].membership == staff.vali and events[104].photo
    # Timed by the terminal's clock, whenever it arrived.
    assert events[104].event_at == datetime.fromisoformat(terminal.events[-1]["time"])
    device.refresh_from_db()
    assert device.history_skipped == 12040  # the helper's scans are no history

    # Paged searches, in the terminal's own offset, ending well past midnight.
    assert any(search["searchResultPosition"] > 0 for search in terminal.searches)
    assert all(search["startTime"].endswith("+05:00") for search in terminal.searches)
    span = datetime.fromisoformat(terminal.searches[-1]["endTime"]) - terminal.now()
    assert span > timedelta(hours=20)
    assert terminal.failed_logins == 0 and terminal.picture_requests == 3

    out = capsys.readouterr().out
    assert "Signed in to the terminal as admin (DS-K1T341AMF, firmware V3.2.30)" in out
    assert "still sending old scans: 12 040 skipped so far, up to 2023-03-02 09:15" in out
    sent = [row for row in out.splitlines() if row.rstrip().endswith("  sent")]
    assert len(sent) == 3  # one line per scan; the door opening goes without one
    for line, who in zip(sent, ("Alisher Valiyev", "unknown face", "Vali Karimov"), strict=True):
        assert who in line
    assert "The terminal's own upload has caught up" in out and "3 scans sent" in out
    assert device.token not in out  # the code stays off the screen
    assert fake_terminal.PASSWORD not in out


@pytest.mark.django_db(transaction=True)
def test_a_wrong_server_address_stops_with_a_clear_word(catchup, terminal, live_server, capsys):
    """The terminal's code changed (a new one was made): the server answers 404, and the helper
    says what to do instead of trying forever."""
    address = f"{live_server.url}/api/v1/devices/hik/{'x' * 24}/"
    assert catchup.main(["--terminal", terminal.address, "--url", address]) == 1
    assert "doesn't know this terminal's address (404)" in capsys.readouterr().out
    assert terminal.searches == []  # nothing was read off the terminal


def test_a_wrong_password_costs_one_failed_sign_in(catchup, terminal, monkeypatch, capsys):
    """A few wrong sign-ins in a row lock a terminal for half an hour: the helper tries once,
    says how many tries are left, and stops."""
    monkeypatch.setenv("HIK_PASS", "a-wrong-one")
    address = "http://127.0.0.1:9/api/v1/devices/hik/abcdefghijklmnopqrstuvwx/"
    assert catchup.main(["--terminal", terminal.address, "--url", address]) == 1
    assert terminal.failed_logins == 1
    out = capsys.readouterr().out
    assert "refused the user 'admin' with this password (4 tries left" in out
    assert "a-wrong-one" not in out


def test_check_tests_both_connections_and_sends_nothing(catchup, terminal, capsys, monkeypatch):
    """--check signs in to the terminal, reads its events once, asks the server's address, and
    says how each went."""
    seen = []

    class Server(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.command)
            answer = {"statusCode": 200, "statusString": "OK", "subStatusCode": "ok"}
            answer["history"] = {"active": True, "skipped": 5, "until": "2024-01-31T18:00:00+05:00"}
            body = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        address = f"http://127.0.0.1:{server.server_address[1]}/api/v1/devices/hik/{'a' * 24}/"
        terminal.add(7, terminal.now(), number="12", name="Alisher Valiyev")
        assert catchup.main(["--terminal", terminal.address, "--url", address, "--check"]) == 0
    finally:
        server.shutdown()
        server.server_close()
    out = capsys.readouterr().out
    assert "signed in as admin (DS-K1T341AMF, firmware V3.2.30); its scans can be read" in out
    assert "still sending old scans: 5 skipped so far, up to 2024-01-31 18:00" in out
    assert "Both work" in out and "Alisher" not in out
    assert seen == ["GET"] and len(terminal.searches) == 1


def test_the_server_asking_to_slow_down_is_waited_for(catchup, monkeypatch):
    """429: the same scan again after Retry-After."""
    answers, waited = [(429, "1"), (200, None)], []

    class Server(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            status, retry = answers.pop(0)
            self.send_response(status)
            if retry:
                self.send_header("Retry-After", retry)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    for name in PROXIES:
        monkeypatch.delenv(name, raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        address = f"http://127.0.0.1:{server.server_address[1]}/api/v1/devices/hik/{'a' * 24}/"
        run = catchup.CatchUp(
            catchup.Terminal("127.0.0.1:9", "admin", "x"),
            catchup.Server(address),
            since=10,
            interval=3,
            hours=1,
        )
        monkeypatch.setattr(run, "pause", waited.append)
        event = {"serialNo": 5, "major": 5, "minor": 75, "time": "2026-11-10T09:41:07+05:00"}
        assert run.send(event | {"name": "Vali"}) is True
    finally:
        server.shutdown()
        server.server_close()
    assert waited == [1.0] and answers == [] and run.last_serial == 5


def test_the_terminals_own_clock_and_offset_set_the_search(catchup):
    """A terminal on its factory zone (+08:00) with a clock two days behind: searches ask in its
    terms, so they find what it stamps, and the clock is worth a word."""
    with FakeTerminal(offset_hours=8, clock_off=-timedelta(days=2)) as fake:
        reading = catchup.Terminal(fake.address, "admin", fake_terminal.PASSWORD).clock()
        clock = catchup.TerminalClock(reading)
        assert clock.now().utcoffset() == timedelta(hours=8)
        assert abs(clock.now() - fake.now()) < timedelta(seconds=3)
        assert "clock says" in catchup.clock_warning(clock)
    assert catchup.posix_offset("CST-5:00:00").utcoffset(None) == timedelta(hours=5)
    assert catchup.posix_offset("EST+5").utcoffset(None) == -timedelta(hours=5)
    assert catchup.parse_time("2026-11-10T09:41:07.123+0500").isoformat() == (
        "2026-11-10T09:41:07+05:00"
    )
    assert catchup.parse_time("2026-11-10T04:41:07Z").utcoffset() == timedelta(0)
    # Without a reading, this computer's clock.
    assert catchup.clock_warning(catchup.TerminalClock()) == ""


def test_the_script_runs_on_any_laptop():
    """Python 3.9 and the standard library only, and the address line the download fills in."""
    text = SCRIPT.read_text()
    tree = ast.parse(text, feature_version=(3, 9))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module)])
        if alias.name
    }
    assert imported <= {
        "__future__", "argparse", "base64", "contextlib", "datetime", "getpass", "hashlib",
        "http", "ipaddress", "json", "os", "re", "ssl", "sys", "threading", "time", "urllib",
        "uuid",
    }  # fmt: skip
    assert text.count('\nDEVICE_URL = ""\n') == 1
    assert "HIK_PASS" in text and "print(password" not in text


def test_a_missing_address_or_password_is_explained(catchup, monkeypatch, capsys):
    assert catchup.main(["--terminal", "192.0.2.1"]) == 2
    assert "--url" in capsys.readouterr().out
    assert catchup.main(["--terminal", "192.0.2.1", "--url", "https://x.example/"]) == 1
    assert "isn't a terminal's address on the server" in capsys.readouterr().out
    # "HIK_PASS=…" as the dashboard shows it: the helper asks instead.
    monkeypatch.setenv("HIK_PASS", "…")
    asked = []
    monkeypatch.setattr(catchup.getpass, "getpass", lambda prompt: asked.append(prompt) or "")
    address = "https://x.example/api/v1/devices/hik/abcdefghijklmnopqrstuvwx/"
    assert catchup.main(["--terminal", "192.0.2.1", "--url", address]) == 2
    assert asked == ["Password of admin on the terminal: "]


def test_a_refusal_says_when_the_terminal_has_locked_its_sign_in(catchup):
    body = b"<userCheck><lockStatus>lock</lockStatus><unlockTime>1740</unlockTime></userCheck>"
    assert "try again in about 29 min" in catchup.refused_sign_in("admin", body)
    headers = Message()
    headers["WWW-Authenticate"] = 'Basic realm="x"'
    headers["WWW-Authenticate"] = 'Digest realm="r", nonce="n", qop="auth"'
    assert catchup.read_challenge(headers) == {
        "scheme": "digest", "realm": "r", "nonce": "n", "qop": "auth",
    }  # fmt: skip
