"""A fake Daybook for tests and demos: the device API of contract §5, in memory.

``FakeDaybook.transport()`` plugs it into the agent's httpx client (``httpx.MockTransport``);
``koz-agent devserver`` serves it on ``http://127.0.0.1:8780`` so a box can pair and run against
it without the real backend. It also plays the owner: set up cameras, watch them, ask for clips.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import httpx

from .clock import Clock, SystemClock, iso, parse_iso
from .rules import Rules

PREFIX = "/api/v1/devices/koz/"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def parse_multipart(content_type: str, body: bytes) -> dict[str, tuple[str | None, bytes]]:
    match = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not match:
        return {}
    boundary = b"--" + match.group(1).encode()
    fields: dict[str, tuple[str | None, bytes]] = {}
    for part in body.split(boundary)[1:]:
        if part.startswith(b"--"):
            break
        part = part[2:] if part.startswith(b"\r\n") else part
        head, _, data = part.partition(b"\r\n\r\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name = re.search(rb'name="([^"]*)"', head)
        if not name:
            continue
        filename = re.search(rb'filename="([^"]*)"', head)
        fields[name.group(1).decode()] = (filename.group(1).decode() if filename else None, data)
    return fields


class FakeDaybook:
    def __init__(self, clock: Clock | None = None, *, auto_setup: bool = False) -> None:
        self.clock = clock or SystemClock()
        self.auto_setup = auto_setup
        self.lock = threading.RLock()
        self.codes: set[str] = set()
        self.tokens: set[str] = set()
        self.agent = {"id": 4, "name": "Asosiy qutisi", "branch": {"id": 1, "name": "Asosiy"},
                      "timezone": "Asia/Tashkent"}
        self.company = {"id": 1, "name": "Demo dorixona"}
        self.rules = asdict(Rules())
        self.cameras: dict[str, dict] = {}
        self.snapshot_requested: set[str] = set()
        self.job_snapshots: set[str] = set()
        self.clips: dict[int, dict] = {}
        self.snapshots: list[dict] = []
        self.lives: list[dict] = []
        self.frames: list[dict] = []
        self.stats: dict[tuple[str, str], dict] = {}
        self.stat_calls = 0
        self.events: list[dict] = []
        self.event_ids: set[str] = set()
        self.alerts: dict[str, dict] = {}
        self.requests: list[tuple[str, str, int]] = []
        self.hosts: list[dict] = []
        self.watch: Callable[[float], set[str]] = lambda _t: set()
        self.fail_next = 0  # answer the next N calls with 503
        self.down = False  # the network is gone: the transport raises ConnectError
        self._ids = 10

    # --- the owner's side ---------------------------------------------------------------

    def new_code(self) -> str:
        raw = "".join(secrets.choice(CROCKFORD) for _ in range(8))
        code = f"KOZ-{raw[:4]}-{raw[4:]}"
        with self.lock:
            self.codes = {code}
        return code

    def revoke(self) -> None:
        with self.lock:
            self.tokens.clear()

    def set_camera(self, key: str, **fields) -> None:
        with self.lock:
            camera = self.cameras[key]
            if "name" in fields:
                camera["renamed"] = True
            camera.update(fields)

    def set_rules(self, **rules) -> None:
        with self.lock:
            self.rules = asdict(Rules.from_dict({**self.rules, **rules}))

    def request_snapshot(self, key: str) -> None:
        with self.lock:
            self.job_snapshots.add(key)

    def request_clip(self, key: str, start: float, end: float) -> int:
        with self.lock:
            self._ids += 1
            self.clips[self._ids] = {"id": self._ids, "key": key, "start": iso(start),
                                     "end": iso(end), "state": "pending"}
            return self._ids

    def config_version(self) -> str:
        with self.lock:
            data = {"rules": self.rules, "agent": self.agent,
                    "cameras": self._config_cameras(), "snap": sorted(self.snapshot_requested)}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:6]

    def _config_cameras(self) -> list[dict]:
        fields = ("id", "key", "name", "role", "enabled", "zones", "register_id")
        return [{k: c.get(k) for k in fields} for c in self.cameras.values()]

    # --- the device API -------------------------------------------------------------------

    def handle(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, dict | None]:
        with self.lock:
            status, reply = self._handle(method, path, {k.lower(): v for k, v in headers.items()},
                                         body)
            self.requests.append((method, path, status))
            return status, reply

    def _handle(self, method: str, path: str, headers: dict, body: bytes):
        if not path.startswith(PREFIX):
            return 404, {"detail": "not found", "code": "not_found"}
        route = unquote(path[len(PREFIX):])
        if self.fail_next > 0:
            self.fail_next -= 1
            return 503, {"detail": "try again", "code": "unavailable"}
        if route == "pair/" and method == "POST":
            data = json.loads(body or b"{}")
            if data.get("code") not in self.codes:
                return 400, {"detail": "unknown, used or expired code", "code": "bad_code"}
            self.codes.discard(data["code"])
            token = "koz_" + secrets.token_urlsafe(30)[:40]
            self.tokens = {token}
            self.hosts.append(data.get("host") or {})
            agent = {"id": self.agent["id"], "name": self.agent["name"], "company": self.company,
                     "branch": self.agent["branch"]}
            return 200, {"token": token, "agent": agent, "server_time": iso(self.clock.time())}
        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self.tokens:
            return 401, {"detail": "this box is not paired or was removed", "code": "revoked"}
        now = self.clock.time()
        content_type = headers.get("content-type", "")

        if route == "config/" and method == "GET":
            return 200, {"config_version": self.config_version(), "agent": self.agent,
                         "rules": {k: v for k, v in self.rules.items()},
                         "cameras": self._config_cameras(),
                         "snapshot_requested": sorted(self.snapshot_requested)}
        if route == "cameras/" and method == "POST":
            items = json.loads(body).get("cameras") or []
            seen = set()
            for item in items:
                key = item["key"]
                seen.add(key)
                camera = self.cameras.get(key)
                if camera is None:
                    self._ids += 1
                    camera = self.cameras[key] = {
                        "id": self._ids, "key": key, "name": item.get("name") or key,
                        "role": "other", "enabled": False, "zones": [], "register_id": None,
                        "renamed": False,
                    }
                    if self.auto_setup:
                        self._auto(camera)
                camera.update({k: item.get(k) for k in ("source", "channel", "w", "h", "online")})
                if not camera.get("renamed") and item.get("name"):
                    camera["name"] = item["name"]
            for key, camera in self.cameras.items():
                if key not in seen:
                    camera["online"] = False
            return 200, {"cameras": [{"key": k, "id": self.cameras[k]["id"]} for k in sorted(seen)]}
        match = re.fullmatch(r"cameras/([a-z0-9:_-]+)/snapshot/", route)
        if match and method == "POST":
            key = match.group(1)
            if key not in self.cameras:
                return 404, {"detail": "unknown camera", "code": "not_found"}
            image = parse_multipart(content_type, body).get("image", (None, b""))[1]
            if not image.startswith(b"\xff\xd8") or len(image) > 1_500_000:
                return 422, {"detail": "a JPEG up to 1.5 MB", "code": "bad_image"}
            self.snapshots.append({"key": key, "at": now, "size": len(image), "image": image})
            self.snapshot_requested.discard(key)
            self.job_snapshots.discard(key)
            return 204, None
        if route == "live/" and method == "POST":
            data = json.loads(body)
            self.lives.append({"at": now, "payload": data})
            pending = sum(1 for c in self.clips.values() if c["state"] == "pending")
            return 200, {"config_version": self.config_version(),
                         "watch": sorted(k for k in self.watch(now) if k in self.cameras),
                         "jobs": pending + len(self.job_snapshots),
                         "server_time": iso(now)}
        match = re.fullmatch(r"frames/([a-z0-9:_-]+)/", route)
        if match and method == "POST":
            fields = parse_multipart(content_type, body)
            image = fields.get("image", (None, b""))[1]
            meta = json.loads(fields.get("meta", (None, b"{}"))[1] or b"{}")
            if not image.startswith(b"\xff\xd8") or len(image) > 400_000:
                return 422, {"detail": "a JPEG up to 400 KB", "code": "bad_image"}
            self.frames.append({"key": match.group(1), "at": now, "meta": meta,
                                "size": len(image)})
            return 204, None
        if route == "stats/" and method == "POST":
            self.stat_calls += 1
            minutes = json.loads(body).get("minutes") or []
            if len(minutes) > 2000:
                return 413, {"detail": "at most 2,000 rows", "code": "too_many"}
            stored, skipped = 0, []
            for row in minutes:
                too_old = now - parse_iso(row["minute"]) > 7 * 86400
                if row.get("key") not in self.cameras or too_old:
                    skipped.append({"key": row.get("key"), "minute": row.get("minute")})
                    continue
                self.stats[(row["key"], row["minute"])] = row
                stored += 1
            return 200, {"stored": stored, "skipped": skipped}
        if route == "events/" and method == "POST":
            fields = parse_multipart(content_type, body)
            event = json.loads(fields.get("event", (None, b"{}"))[1])
            image = fields.get("image", (None, b""))[1]
            if event["event_id"] in self.event_ids:
                alert = self.alerts.get(event["incident_id"])
                return 200, {"alert_id": alert["id"] if alert else None,
                             "state": alert["state"] if alert else None}
            self.event_ids.add(event["event_id"])
            self.events.append({**event, "image": image or None, "received_at": now})
            alert = self.alerts.get(event["incident_id"])
            if event["phase"] == "start":
                self._ids += 1
                alert = self.alerts[event["incident_id"]] = {"id": self._ids, "state": "open",
                                                             "kind": event["kind"]}
            elif alert is None:
                return 200, {"alert_id": None}
            if event["phase"] == "end":
                alert["state"] = "resolved"
            return 200, {"alert_id": alert["id"], "state": alert["state"]}
        if route == "jobs/" and method == "GET":
            clips = []
            for clip in self.clips.values():
                if clip["state"] == "pending":
                    clip["state"] = "fetching"
                    clips.append({k: clip[k] for k in ("id", "key", "start", "end")})
            snapshots = sorted(self.job_snapshots)
            return 200, {"clips": clips, "snapshots": snapshots}
        match = re.fullmatch(r"clips/(\d+)/", route)
        if match and method == "POST":
            clip = self.clips.get(int(match.group(1)))
            if clip is None:
                return 404, {"detail": "unknown clip", "code": "not_found"}
            if content_type.startswith("application/json"):
                data = json.loads(body)
                clip.update(state="failed", failed=data.get("failed"), detail=data.get("detail"))
                return 204, None
            fields = parse_multipart(content_type, body)
            video = fields.get("video", (None, b""))[1]
            if len(video) > 40 * 1024 * 1024:
                return 413, {"detail": "an MP4 up to 40 MB", "code": "too_big"}
            clip.update(state="ready", video=video, poster=fields.get("poster", (None, b""))[1],
                        meta=json.loads(fields.get("meta", (None, b"{}"))[1] or b"{}"))
            return 204, None
        return 404, {"detail": "not found", "code": "not_found"}

    def _auto(self, camera: dict) -> None:
        from .scene import suggest_zones

        suggestion = suggest_zones().get(camera["key"])
        if suggestion:
            camera.update(role=suggestion["role"], zones=suggestion["zones"], enabled=True)

    # --- plumbing -------------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if self.down:
                raise httpx.ConnectError("the network is down", request=request)
            status, reply = self.handle(request.method, request.url.path, dict(request.headers),
                                        request.read())
            if reply is None:
                return httpx.Response(status)
            return httpx.Response(status, json=reply)

        return httpx.MockTransport(handler)

    def serve(self, host: str = "127.0.0.1", port: int = 8780) -> ThreadingHTTPServer:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _do(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, reply = fake.handle(self.command, urlsplit(self.path).path,
                                            dict(self.headers), body)
                payload = b"" if reply is None else json.dumps(reply).encode()
                self.send_response(status)
                if reply is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _do

            def log_message(self, *_args) -> None:
                return

        server = ThreadingHTTPServer((host, port), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, name="devserver", daemon=True).start()
        return server
