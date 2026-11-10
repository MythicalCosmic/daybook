import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from status import app, core, page

DAY = 86400
NOW = 1_800_000_000.0


# ---- flap rule


def test_single_failure_is_not_an_incident():
    st = core.CheckState(threshold=2)
    assert st.observe(0, False) is None
    assert st.observe(60, True) is None
    assert not st.down


def test_two_failures_open_incident_at_first_failure():
    st = core.CheckState(threshold=2)
    assert st.observe(0, True) is None
    assert st.observe(60, False) is None
    assert st.observe(120, False) == "down"
    assert st.incident_start == 60
    assert st.observe(180, False) is None  # no repeat alert
    assert st.observe(240, True) == "up"
    assert st.observe(300, True) is None


def test_alternating_failures_never_alert():
    st = core.CheckState(threshold=2)
    events = [st.observe(i * 60, i % 2 == 0) for i in range(20)]
    assert events == [None] * 20


# ---- uptime math


def test_uptime_full_and_none():
    assert core.uptime([], NOW - DAY, NOW, NOW - 10 * DAY) == 100.0
    assert core.uptime([], NOW - DAY, NOW, None) is None


def test_uptime_partial_and_clipped():
    inc = [(NOW - 3600, NOW - 3600 + 864)]  # 864 s = 1% of a day
    assert core.uptime(inc, NOW - DAY, NOW, NOW - 10 * DAY) == 99.0
    # incident that started before the window only counts its part inside
    inc = [(NOW - DAY - 1000, NOW - DAY + 864)]
    assert core.uptime(inc, NOW - DAY, NOW, NOW - 10 * DAY) == 99.0


def test_uptime_ongoing_incident_and_coverage():
    # monitoring started 1 hour ago, down for the last 30 min -> 50%, not 98%
    assert core.uptime([(NOW - 1800, None)], NOW - DAY, NOW, NOW - 3600) == 50.0


def test_uptimes_windows():
    u = core.uptimes([(NOW - 2 * DAY, NOW - 2 * DAY + 8640)], NOW, NOW - 100 * DAY)
    assert u["24h"] == 100.0
    assert u["7d"] == round(100 * (1 - 8640 / (7 * DAY)), 3)
    assert set(u) == {"24h", "7d", "30d", "90d"}


def test_daily_bars():
    start = NOW - 5 * DAY
    bars = core.daily_bars([(NOW - 2 * DAY, NOW - 2 * DAY + 600)], NOW, start, days=90)
    assert len(bars) == 90
    assert bars[0]["uptime"] is None  # before monitoring started
    assert sum(b["down_s"] for b in bars) == 600
    assert all(b["uptime"] is not None for b in bars[-5:])


def test_merge_and_levels():
    assert app._merge([(0, 10), (5, 20), (30, 40)]) == [(0, 20), (30, 40)]
    assert app._merge([(0, None), (5, 20)]) == [(0, None)]
    assert core.level(["up", "warn"]) == "warn"
    assert core.level(["up", "down", "warn"]) == "down"
    assert core.overall(["up", "up"]) == "operational"
    assert core.overall(["up", "down"]) == "partial"
    assert core.overall(["down", "down"]) == "major"
    assert core.overall(["warn", "up"]) == "degraded"
    assert core.duration_text(3725) == "1h 2m"


# ---- incidents end to end (fake checks, real SQLite, no network)


class FakeAlerter:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


CFG = {
    "interval": 60,
    "timeout": 10,
    "fail_threshold": 2,
    "tls_warn_days": 14,
    "slow_ms": 3000,
    "services": [
        {
            "id": "s",
            "name": "Svc",
            "checks": [
                {"id": "a", "name": "Health", "type": "http", "url": "https://x/"},
                {"id": "b", "name": "Dash", "type": "http", "url": "https://x/d"},
            ],
        }
    ],
}


def _run(tmp_path, pattern):
    store = app.Store(str(tmp_path / "s.db"))
    al = FakeAlerter()
    mon = app.Monitor(CFG, store, al)
    for i, ok_a in enumerate(pattern):
        mon.tick(
            NOW + i * 60,
            runner=lambda c, cfg, ok_a=ok_a: {
                "ok": ok_a if c["id"] == "a" else True,
                "level": "up" if (ok_a or c["id"] != "a") else "down",
                "ms": 100,
                "code": 200,
                "detail": "" if ok_a else "timeout",
            },
        )
    return mon, store, al


def test_incident_recorded_and_alerted(tmp_path):
    mon, store, al = _run(tmp_path, [True, False, False, False, True, True])
    rows = store.q("SELECT check_id, start, end FROM incidents")
    assert rows == [("a", NOW + 60, NOW + 240)]
    assert len(al.sent) == 2
    assert al.sent[0].startswith("ISHLAMAYAPTI: Svc - Health") and "DOWN" in al.sent[0]
    assert al.sent[1].startswith("TIKLANDI") and "3m" in al.sent[1] and "RECOVERED" in al.sent[1]
    snap = app.snapshot(mon, NOW + 300)
    assert snap["overall"] == "operational"
    assert snap["incidents"][0]["duration_s"] == 180
    assert snap["services"][0]["uptime"]["24h"] == 40.0  # 180 s down of 300 s covered
    html = page.render(snap, "uz") + page.render(snap, "en")
    assert "Holat · Status" in html and "Recent incidents" in html


def test_blip_not_recorded(tmp_path):
    _, store, al = _run(tmp_path, [True, False, True, False, True])
    assert store.q("SELECT * FROM incidents") == []
    assert al.sent == []


def test_restart_keeps_open_incident(tmp_path):
    mon, store, al = _run(tmp_path, [False, False])
    assert len(al.sent) == 1
    mon2 = app.Monitor(CFG, store, al)
    assert mon2.states["a"].down
    snap = app.snapshot(mon2, NOW + 120)
    assert snap["overall"] == "partial" or snap["services"][0]["level"] == "down"
    mon2.tick(
        NOW + 180,
        runner=lambda c, cfg: {"ok": True, "level": "up", "ms": 1, "code": 200, "detail": ""},
    )
    assert len(al.sent) == 2 and store.q("SELECT end FROM incidents") == [(NOW + 180,)]


def test_config_loads():
    cfg = app.load_config(str(Path(__file__).resolve().parents[1] / "config.json"))
    assert len(list(app.all_checks(cfg))) == 8
