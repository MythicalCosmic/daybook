"""A Hikvision terminal's ISAPI as deploy/faceid/catchup.py uses it, served on 127.0.0.1 for the
catch-up tests: digest sign-in (refusals answered the way the DS-K1T341AMF answers them, with the
tries left), the device's info and clock, the access event search page by page, and each scan's
picture behind the link the terminal gives (its own LAN address, not the one used here).

    with FakeTerminal() as terminal:
        terminal.add(101, terminal.now(), number="12", name="Alisher Valiyev")
        terminal.address         # "127.0.0.1:<port>"
        terminal.searches        # every AcsEventCond asked for
        terminal.failed_logins   # sign-ins with a wrong password
"""

import hashlib
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import parse_http_list, parse_keqv_list

from apps.faceid.tests import samples

USER = "admin"
# Made up for the tests; no terminal anywhere has it.
PASSWORD = "test-only-not-a-terminal-password"
REALM = "DS-K1T341AMF"
# The terminal's own address: picture links name it, the helper fetches them from where it talks.
LAN_ADDRESS = "192.168.1.250"
TRIES = 5


def _md5(text: str) -> str:
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


class FakeTerminal:
    def __init__(self, *, offset_hours: int = 5, page: int = 2, clock_off=timedelta(0)):
        self.zone = timezone(timedelta(hours=offset_hours))
        self.offset_hours = offset_hours
        self.page = page
        self.clock_off = clock_off
        self.events: list[dict] = []
        self.pictures: dict[str, bytes] = {}
        self.searches: list[dict] = []
        self.picture_requests = 0
        self.failed_logins = 0
        self._nonces: set[str] = set()
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self._server.server_address[1]}"

    def now(self) -> datetime:
        """The terminal's clock: its zone, and as far off as it was set."""
        return (datetime.now(self.zone) + self.clock_off).replace(microsecond=0)

    def add(self, serial: int, at: datetime, *, number="", name="", minor=75, picture=True):
        """An access event as the AcsEvent search lists it (samples.k1t341amf's shape)."""
        at = at.astimezone(self.zone)
        row = {
            "major": 5,
            "minor": minor,
            "time": at.isoformat(timespec="seconds"),
            "cardType": 1,
            "name": name,
            "cardReaderNo": 1,
            "doorNo": 1,
            "employeeNoString": number,
            "type": 0,
            "serialNo": serial,
            "userType": "normal",
            "currentVerifyMode": "cardOrFaceOrFp",
            "mask": "no",
            "picturesNumber": 1 if picture else 0,
        }
        row = {key: value for key, value in row.items() if value != ""}
        if picture:
            name = f"{at:%d_%H%M%S}_{serial}_0.jpeg@WEB000000000014"
            path = f"/LOCALS/pic/acsLinkCap/{at:%Y%m}_00/{name}"
            self.pictures[path] = samples.jpeg(color=(serial % 255, 120, 140))
            row["pictureURL"] = f"http://{LAN_ADDRESS}{path}"
        with self._lock:
            self.events.append(row)
        return row

    # Sign-in

    def _challenge(self) -> str:
        nonce = secrets.token_hex(16)
        self._nonces.add(nonce)
        return f'Digest qop="auth", realm="{REALM}", nonce="{nonce}", stale="FALSE"'

    def _signed_in(self, method: str, path: str, header: str) -> bool | None:
        """True: a right answer to a challenge; False: a wrong one (counted); None: no answer."""
        if not header.startswith("Digest "):
            return None
        fields = parse_keqv_list(parse_http_list(header[len("Digest ") :]))
        secret = _md5(f"{USER}:{REALM}:{PASSWORD}")
        target = _md5(f"{method}:{fields.get('uri')}")
        expected = _md5(
            f"{secret}:{fields.get('nonce')}:{fields.get('nc')}:{fields.get('cnonce')}:auth:{target}"
        )
        right = (
            fields.get("username") == USER
            and fields.get("nonce") in self._nonces
            and fields.get("uri") == path
            and fields.get("response") == expected
        )
        if not right:
            self.failed_logins += 1
        return right

    def _refusal(self) -> bytes:
        left = max(0, TRIES - self.failed_logins)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n<userCheck><statusValue>401</statusValue>'
            "<statusString>Unauthorized</statusString><lockStatus>unlock</lockStatus>"
            f"<unlockTime>0</unlockTime><retryLoginTime>{left}</retryLoginTime></userCheck>"
        ).encode()

    # What it answers

    def _info(self) -> bytes:
        return (
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<DeviceInfo version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
            b"<deviceName>Access Controller</deviceName><model>DS-K1T341AMF</model>"
            b"<serialNumber>DS-K1T341AMF20220311V032300ENTEST0000</serialNumber>"
            b"<macAddress>e8:a0:ed:12:34:56</macAddress><firmwareVersion>V3.2.30</firmwareVersion>"
            b"</DeviceInfo>"
        )

    def _time(self) -> bytes:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Time version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">'
            f"<timeMode>NTP</timeMode><localTime>{self.now().isoformat()}</localTime>"
            f"<timeZone>CST-{self.offset_hours}:00:00</timeZone></Time>"
        ).encode()

    def _search(self, body: bytes) -> bytes:
        condition = json.loads(body)["AcsEventCond"]
        start = datetime.fromisoformat(condition["startTime"])
        end = datetime.fromisoformat(condition["endTime"])
        with self._lock:
            self.searches.append(condition)
            rows = sorted(
                (
                    row
                    for row in self.events
                    if start <= datetime.fromisoformat(row["time"]) <= end
                    and condition.get("major") in (0, row["major"])
                ),
                key=lambda row: row["serialNo"],
            )
        position = int(condition["searchResultPosition"])
        size = min(int(condition["maxResults"]), self.page)
        chunk = rows[position : position + size]
        found = {
            "searchID": condition["searchID"],
            "responseStatusStrg": "MORE"
            if position + size < len(rows)
            else ("OK" if chunk else "NO MATCH"),
            "numOfMatches": len(chunk),
            "totalMatches": len(rows),
        }
        if chunk:
            found["InfoList"] = chunk
        return json.dumps({"AcsEvent": found}).encode()

    def _handler(self):
        terminal = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def _route(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                signed = terminal._signed_in(
                    method, self.path, self.headers.get("Authorization", "")
                )
                if not signed:
                    return self._answer(401, terminal._refusal(), "application/xml", True)
                path = self.path.split("?", 1)[0]
                if method == "GET" and path == "/ISAPI/System/deviceInfo":
                    return self._answer(200, terminal._info(), "application/xml")
                if method == "GET" and path == "/ISAPI/System/time":
                    return self._answer(200, terminal._time(), "application/xml")
                if method == "POST" and path == "/ISAPI/AccessControl/AcsEvent":
                    return self._answer(200, terminal._search(body), "application/json")
                if method == "GET" and self.path in terminal.pictures:
                    terminal.picture_requests += 1
                    return self._answer(200, terminal.pictures[self.path], "image/jpeg")
                return self._answer(404, b'{"statusCode": 4, "statusString": "Invalid Operation"}')

            def _answer(self, status, body, kind="application/json", challenge=False):
                self.send_response(status)
                if challenge:
                    self.send_header("WWW-Authenticate", terminal._challenge())
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
