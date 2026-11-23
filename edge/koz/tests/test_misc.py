"""The inference budget, secrets, settings and the local status page."""

import itertools
import json
import os
import sys
import urllib.request
from collections import Counter

import pytest

from koz_agent.agent import Agent, CameraConfig
from koz_agent.clock import FakeClock
from koz_agent.detectors import SimDetector
from koz_agent.scene import suggest_zones
from koz_agent.scheduler import InferenceScheduler
from koz_agent.secretstore import SecretStore
from koz_agent.settings import NvrSettings, Settings
from koz_agent.sources import make_sim_sources
from koz_agent.status import StatusServer

from .conftest import T0


def drive(scheduler, seconds, step=0.05, ready=lambda _k: True):
    picks = []
    t = 0.0
    while t < seconds:
        key = scheduler.next(t, ready)
        if key:
            picks.append((round(t, 2), key))
        t += step
    return picks


def test_each_camera_at_its_analysis_fps():
    scheduler = InferenceScheduler(max_per_s=6)
    scheduler.set_cameras({"a": 2, "b": 2})
    picks = drive(scheduler, 10)
    counts = Counter(k for _t, k in picks)
    assert 19 <= counts["a"] <= 21 and 19 <= counts["b"] <= 21


def test_the_budget_caps_all_cameras_and_shares_it_fairly():
    scheduler = InferenceScheduler(max_per_s=6)
    scheduler.set_cameras({k: 2 for k in "abcd"})  # 8 wanted, 6 allowed
    picks = drive(scheduler, 20)
    assert len(picks) <= 6 * 20 + 1
    times = [t for t, _k in picks]
    assert min(b - a for a, b in itertools.pairwise(times)) >= 1 / 6 - 1e-6
    counts = Counter(k for _t, k in picks)
    assert max(counts.values()) - min(counts.values()) <= 2


def test_a_camera_without_a_new_frame_does_not_block_the_others():
    scheduler = InferenceScheduler(max_per_s=6)
    scheduler.set_cameras({"a": 2, "b": 2})
    picks = drive(scheduler, 5, ready=lambda k: k == "b")
    assert {k for _t, k in picks} == {"b"} and len(picks) >= 9


def test_secrets_round_trip_and_stay_unreadable(tmp_path):
    store = SecretStore(tmp_path)
    store.set("token", "koz_supersecret")
    store.set("nvr:192.168.0.250:password", "p@ss")
    assert SecretStore(tmp_path).get("token") == "koz_supersecret"
    assert store.names() == ["nvr:192.168.0.250:password", "token"]
    raw = store.path.read_bytes()
    if sys.platform == "win32":
        assert b"supersecret" not in raw and b"p@ss" not in raw  # DPAPI
    else:
        assert os.stat(store.path).st_mode & 0o777 == 0o600
    store.delete("token")
    assert store.get("token") is None


def test_settings_round_trip(tmp_path):
    path = tmp_path / "agent.json"
    settings = Settings(server="https://daybook.example", nvrs=[NvrSettings(host="192.168.0.250")])
    settings.save(path)
    again = Settings.load(path)
    assert again.server == "https://daybook.example" and again.nvr("192.168.0.250").port == 80
    assert "password" not in path.read_text(encoding="utf-8")


@pytest.fixture
def status_page():
    clock = FakeClock(T0 + 30)
    defaults = {
        key: CameraConfig(name=s["name"], role=s["role"], enabled=True, zones=s["zones"])
        for key, s in suggest_zones().items()
    }
    agent = Agent(
        clock=clock,
        sources=make_sim_sources("demo", 1, clock, threaded=False, start=T0),
        detector_for=lambda _s: SimDetector(),
        defaults=defaults,
    )
    for _ in range(20):
        clock.advance(0.5)
        agent.tick()
    server = StatusServer(agent, port=0)
    port = server.start()
    yield f"http://127.0.0.1:{port}", agent
    server.stop()


def get(url, host=None):
    request = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def test_status_page_serves_the_page_the_numbers_and_pictures(status_page):
    base, _agent = status_page
    code, headers, body = get(base + "/")
    assert code == 200 and "Ko‘z".encode() in body and b"Kamera tahlili" in body
    assert b"cdn" not in body.lower() and b"https://" not in body
    code, _h, body = get(base + "/api/status")
    status = json.loads(body)
    assert code == 200 and status["server"]["state"] == "unpaired"
    counter = next(c for c in status["cameras"] if c["key"] == "sim:counter")
    assert counter["enabled"] and counter["people"] is not None and counter["fps"] > 0
    code, headers, body = get(base + "/frame/sim:counter.jpg")
    assert code == 200 and headers["Content-Type"] == "image/jpeg" and body[:2] == b"\xff\xd8"
    request = urllib.request.Request(base + "/mjpeg/sim:door")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["Content-Type"].startswith("multipart/x-mixed-replace")
        chunk = response.read(4096)
    assert chunk.startswith(b"--kozframe") and b"\xff\xd8" in chunk


def test_status_page_refuses_other_hosts_and_unknown_cameras(status_page):
    base, _agent = status_page
    assert get(base + "/api/status", host="evil.example")[0] == 403
    assert get(base + "/frame/nvr:9.jpg")[0] == 404
    assert get(base + "/mjpeg/nvr:9")[0] == 404
