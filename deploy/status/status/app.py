"""Daybook status: checks, SQLite storage, Telegram alerts and the status page. Python stdlib only."""

from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import core, page

log = logging.getLogger("status")
UA = "daybook-status/1.0"


# ---------------------------------------------------------------- config


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("interval", 60)
    cfg.setdefault("timeout", 10)
    cfg.setdefault("fail_threshold", 2)
    cfg.setdefault("tls_warn_days", 14)
    cfg.setdefault("slow_ms", 3000)
    seen = set()
    for svc in cfg["services"]:
        for c in svc["checks"]:
            c.setdefault("type", "http")
            if c["id"] in seen:
                raise ValueError(f"duplicate check id {c['id']}")
            seen.add(c["id"])
    return cfg


def all_checks(cfg):
    for svc in cfg["services"]:
        for c in svc["checks"]:
            yield svc, c


# ---------------------------------------------------------------- checks


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def run_http(c: dict, timeout: float, slow_ms: int) -> dict:
    expect = c.get("expect_status", 200)
    req = urllib.request.Request(c["url"], headers={"User-Agent": UA, "Accept": "*/*"})
    opener = (
        urllib.request.build_opener(_NoRedirect)
        if not c.get("follow_redirects", False)
        else urllib.request.build_opener()
    )
    t0 = time.monotonic()
    body, code = b"", None
    try:
        with opener.open(req, timeout=timeout) as r:
            code = r.status
            body = r.read(65536)
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            body = e.read(65536)
        except Exception:
            body = b""
    except Exception as e:  # DNS, refused, timeout, TLS
        return {"ok": False, "level": "down", "ms": None, "code": None, "detail": _err(e)}
    ms = int((time.monotonic() - t0) * 1000)
    res = {"ok": True, "level": "up", "ms": ms, "code": code, "detail": ""}
    if code != expect:
        res.update(ok=False, level="down", detail=f"HTTP {code}, expected {expect}")
        return res
    if c.get("expect_json"):
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            res.update(ok=False, level="down", detail="response is not JSON")
            return res
        for k, v in c["expect_json"].items():
            if str(data.get(k)) != str(v):
                res.update(ok=False, level="down", detail=f"{k}={data.get(k)!r}, expected {v!r}")
                return res
        vf = c.get("version_field")
        if vf and data.get(vf) is not None:
            res["version"] = str(data.get(vf))
    if ms > c.get("slow_ms", slow_ms):
        res.update(level="warn", detail=f"slow: {ms} ms")
    return res


def run_tls(c: dict, timeout: float, warn_days: int) -> dict:
    host, port = c["host"], int(c.get("port", 443))
    t0 = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                cert = s.getpeercert()
    except Exception as e:
        return {"ok": False, "level": "down", "ms": None, "code": None, "detail": _err(e)}
    ms = int((time.monotonic() - t0) * 1000)
    exp = ssl.cert_time_to_seconds(cert["notAfter"])
    days = (exp - time.time()) / 86400
    warn = c.get("warn_days", warn_days)
    res = {
        "ok": True,
        "level": "up",
        "ms": ms,
        "code": None,
        "days_left": round(days, 1),
        "detail": f"{int(days)} days left",
    }
    if days < warn:
        res["level"] = "warn"
    return res


def _err(e: Exception) -> str:
    if isinstance(e, urllib.error.URLError) and e.reason is not None:
        e = e.reason if isinstance(e.reason, Exception) else Exception(str(e.reason))
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    return f"{type(e).__name__}: {e}"[:200]


def run_check(c: dict, cfg: dict) -> dict:
    if c["type"] == "tls":
        return run_tls(c, cfg["timeout"], cfg["tls_warn_days"])
    return run_http(c, cfg["timeout"], cfg["slow_ms"])


# ---------------------------------------------------------------- storage

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
  check_id TEXT NOT NULL, ts REAL NOT NULL, ok INTEGER NOT NULL, level TEXT NOT NULL,
  ms INTEGER, code INTEGER, detail TEXT, extra TEXT);
CREATE INDEX IF NOT EXISTS samples_check_ts ON samples(check_id, ts);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY, check_id TEXT NOT NULL, start REAL NOT NULL, end REAL, detail TEXT);
CREATE INDEX IF NOT EXISTS incidents_check ON incidents(check_id, start);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    def add_sample(self, cid, ts, r):
        extra = {k: r[k] for k in ("version", "days_left") if k in r}
        self.x(
            "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?)",
            (cid, ts, int(r["ok"]), r["level"], r["ms"], r["code"], r["detail"], json.dumps(extra)),
        )

    def open_incident(self, cid, start, detail):
        return self.x(
            "INSERT INTO incidents(check_id,start,detail) VALUES (?,?,?)", (cid, start, detail)
        )

    def close_incident(self, cid, end):
        self.x("UPDATE incidents SET end=? WHERE check_id=? AND end IS NULL", (end, cid))

    def open_incidents(self):
        return {
            r[0]: r[1] for r in self.q("SELECT check_id, start FROM incidents WHERE end IS NULL")
        }

    def prune(self, now):
        self.x("DELETE FROM samples WHERE ts < ?", (now - 95 * 86400,))


# ---------------------------------------------------------------- alerts


class Alerter:
    def __init__(self, token: str | None, chat_ids: list[str]):
        self.token, self.chat_ids = token, chat_ids

    def send(self, text: str):
        if not self.token or not self.chat_ids:
            log.warning("alert (no Telegram configured): %s", text.replace("\n", " | "))
            return
        for chat in self.chat_ids:
            try:
                data = urllib.parse.urlencode(
                    {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}
                ).encode()
                urllib.request.urlopen(
                    f"https://api.telegram.org/bot{self.token}/sendMessage", data=data, timeout=10
                ).read()
            except Exception as e:  # never let an alert failure stop monitoring
                log.error("telegram send to %s failed: %s", chat, _err(e))


def down_text(svc: str, check: str, detail: str, url: str = "") -> str:
    return (
        f"ISHLAMAYAPTI: {svc} - {check}\nSabab: {detail}\n\n"
        f"DOWN: {svc} - {check}\nReason: {detail}" + (f"\n{url}" if url else "")
    )


def up_text(svc: str, check: str, seconds: float) -> str:
    d = core.duration_text(seconds)
    return (
        f"TIKLANDI: {svc} - {check}\nIshlamagan vaqt: {d}\n\n"
        f"RECOVERED: {svc} - {check}\nDowntime: {d}"
    )


# ---------------------------------------------------------------- monitor loop


class Monitor:
    def __init__(self, cfg, store: Store, alerter: Alerter):
        self.cfg, self.store, self.alerter = cfg, store, alerter
        self.states: dict[str, core.CheckState] = {}
        self.last: dict[str, dict] = {}
        opened = store.open_incidents()
        for _, c in all_checks(cfg):
            st = core.CheckState(threshold=cfg["fail_threshold"])
            if c["id"] in opened:  # survive restarts without a duplicate alert
                st.down, st.incident_start = True, opened[c["id"]]
                st.fails = cfg["fail_threshold"]
            self.states[c["id"]] = st

    def tick(self, now: float | None = None, runner=run_check):
        now = now or time.time()
        jobs = list(all_checks(self.cfg))
        results = {}

        def work(c):
            try:
                results[c["id"]] = runner(c, self.cfg)
            except Exception as e:
                results[c["id"]] = {
                    "ok": False,
                    "level": "down",
                    "ms": None,
                    "code": None,
                    "detail": _err(e),
                }

        threads = [threading.Thread(target=work, args=(c,)) for _, c in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for svc, c in jobs:
            r = results[c["id"]]
            self.store.add_sample(c["id"], now, r)
            self.last[c["id"]] = {**r, "ts": now}
            st = self.states[c["id"]]
            ev = st.observe(now, r["ok"])
            if ev == "down":
                self.store.open_incident(c["id"], st.incident_start, r["detail"])
                log.warning("DOWN %s: %s", c["id"], r["detail"])
                self.alerter.send(down_text(svc["name"], c["name"], r["detail"], c.get("url", "")))
            elif ev == "up":
                self.store.close_incident(c["id"], now)
                log.warning("UP %s after %s", c["id"], core.duration_text(now - st.incident_start))
                self.alerter.send(up_text(svc["name"], c["name"], now - st.incident_start))
            elif not r["ok"]:
                log.info("fail %s (%d): %s", c["id"], st.fails, r["detail"])

    def run_forever(self):
        n = 0
        while True:
            t0 = time.time()
            try:
                self.tick(t0)
                if n % 60 == 0:
                    self.store.prune(t0)
            except Exception:
                log.exception("tick failed")
            n += 1
            time.sleep(max(1.0, self.cfg["interval"] - (time.time() - t0)))


# ---------------------------------------------------------------- snapshot (page + JSON)


def check_level(st: core.CheckState, last: dict | None) -> str:
    if st.down:
        return "down"
    if last is None:
        return "unknown"
    if not last["ok"] or last["level"] == "warn":
        return "warn"
    return "up"


def snapshot(mon: Monitor, now: float | None = None) -> dict:
    now = now or time.time()
    tz = int(float(os.environ.get("STATUS_TZ_OFFSET_HOURS", "5")) * 3600)
    store = mon.store
    services, all_incidents = [], []
    for svc in mon.cfg["services"]:
        checks, svc_incidents, coverages = [], [], []
        for c in svc["checks"]:
            cid = c["id"]
            cov = store.q("SELECT MIN(ts) FROM samples WHERE check_id=?", (cid,))[0][0]
            inc = store.q(
                "SELECT start, end, detail FROM incidents WHERE check_id=? AND (end IS NULL OR end > ?)"
                " ORDER BY start",
                (cid, now - 90 * 86400),
            )
            spans = [(s, e) for s, e, _ in inc]
            avg = store.q(
                "SELECT AVG(ms) FROM samples WHERE check_id=? AND ts>? AND ms IS NOT NULL",
                (cid, now - 86400),
            )[0][0]
            last = mon.last.get(cid)
            if last is None:
                row = store.q(
                    "SELECT ts, ok, level, ms, code, detail, extra FROM samples WHERE check_id=?"
                    " ORDER BY ts DESC LIMIT 1",
                    (cid,),
                )
                if row:
                    ts, ok, lv, ms, code, detail, extra = row[0]
                    last = {
                        "ts": ts,
                        "ok": bool(ok),
                        "level": lv,
                        "ms": ms,
                        "code": code,
                        "detail": detail,
                        **json.loads(extra or "{}"),
                    }
            lv = check_level(mon.states[cid], last)
            checks.append(
                {
                    "id": cid,
                    "name": c["name"],
                    "type": c["type"],
                    "target": c.get("url") or c.get("host"),
                    "level": lv,
                    "last": last,
                    "avg_ms_24h": round(avg) if avg else None,
                    "uptime": core.uptimes(spans, now, cov),
                }
            )
            coverages.append(cov)
            for s, e, d in inc:
                rec = {
                    "service": svc["name"],
                    "check": c["name"],
                    "check_id": cid,
                    "start": s,
                    "end": e,
                    "duration_s": round((e or now) - s),
                    "detail": d,
                }
                svc_incidents.append((s, e))
                all_incidents.append(rec)
        cov = min([x for x in coverages if x is not None], default=None)
        merged = _merge(svc_incidents)
        version = next(
            (
                ch["last"].get("version")
                for ch in checks
                if ch["last"] and ch["last"].get("version")
            ),
            None,
        )
        known = [ch["level"] for ch in checks if ch["level"] != "unknown"]
        services.append(
            {
                "id": svc["id"],
                "name": svc["name"],
                "url": svc.get("url"),
                "version": version,
                "level": core.level(known) if known else "unknown",
                "uptime": core.uptimes(merged, now, cov),
                "days": core.daily_bars(merged, now, cov, 90, tz),
                "checks": checks,
            }
        )
    all_incidents.sort(key=lambda r: r["start"], reverse=True)
    return {
        "generated_at": now,
        "generated_at_iso": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds"),
        "interval_s": mon.cfg["interval"],
        "tz_offset_s": tz,
        "overall": core.overall(s["level"] for s in services if s["level"] != "unknown"),
        "services": services,
        "incidents": all_incidents[:50],
    }


def _merge(spans):
    """Union of overlapping incident spans, so a service is not counted down twice."""
    out = []
    for s, e in sorted(spans, key=lambda x: x[0]):
        if out and (out[-1][1] is None or s <= out[-1][1]):
            if out[-1][1] is not None:
                out[-1][1] = None if e is None else max(out[-1][1], e)
        else:
            out.append([s, e])
    return [tuple(x) for x in out]


# ---------------------------------------------------------------- web


def make_handler(mon: Monitor):
    cache = {"t": 0.0, "snap": None}
    lock = threading.Lock()

    def get_snap():
        with lock:
            if time.time() - cache["t"] > 5 or cache["snap"] is None:
                cache["snap"], cache["t"] = snapshot(mon), time.time()
            return cache["snap"]

    class H(BaseHTTPRequestHandler):
        server_version = "daybook-status"
        sys_version = ""

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, code, ctype, body: bytes, cache_s=15):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", f"public, max-age={cache_s}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path in ("/api/status.json", "/api/status"):
                body = json.dumps(get_snap(), ensure_ascii=False).encode()
                self._send(200, "application/json; charset=utf-8", body)
            elif u.path == "/healthz":
                self._send(200, "text/plain", b"ok", 0)
            elif u.path in ("/", "/index.html"):
                lang = "en" if "lang=en" in (u.query or "") else "uz"
                self._send(200, "text/html; charset=utf-8", page.render(get_snap(), lang).encode())
            else:
                self._send(404, "text/plain", b"not found")

    return H


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s"
    )
    cfg = load_config(os.environ.get("STATUS_CONFIG", "/app/config.json"))
    store = Store(os.environ.get("STATUS_DB", "/data/status.sqlite3"))
    chats = [x.strip() for x in os.environ.get("STATUS_CHAT_IDS", "").split(",") if x.strip()]
    alerter = Alerter(os.environ.get("STATUS_BOT_TOKEN") or None, chats)
    mon = Monitor(cfg, store, alerter)
    threading.Thread(target=mon.run_forever, daemon=True, name="monitor").start()
    port = int(os.environ.get("PORT", "8080"))
    log.info(
        "status page on :%d, %d checks, telegram %s",
        port,
        sum(1 for _ in all_checks(cfg)),
        "on" if alerter.token and chats else "off (log only)",
    )
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(mon)).serve_forever()


if __name__ == "__main__":
    main()
