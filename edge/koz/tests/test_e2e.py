"""The whole agent: two sim cameras on the demo scene against a fake Daybook, for 10 minutes of
scene time on a fake clock (contract §5)."""

import itertools
import random
from collections import defaultdict

import pytest

from koz_agent.agent import Agent
from koz_agent.client import DaybookClient
from koz_agent.clock import FakeClock, iso, parse_iso
from koz_agent.detectors import SimDetector
from koz_agent.devserver import FakeDaybook
from koz_agent.outbox import Outbox
from koz_agent.recorder import Recorder
from koz_agent.scene import suggest_zones
from koz_agent.sources import make_sim_sources

from .conftest import T0, encoder_or_none

MINUTES = 10
STEP = 0.1
WATCH = (T0 + 120, T0 + 150)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    clock = FakeClock(T0)
    fake = FakeDaybook(clock)
    fake.codes = {"KOZ-7F3K-92QD"}
    transport = fake.transport()

    pairing = DaybookClient("https://daybook.test", clock=clock, transport=transport)
    reply = pairing.pair(
        "KOZ-7F3K-92QD", {"hostname": "KASSA-PC", "os": "Windows 11", "version": "0.1.0"}
    )
    client = DaybookClient(
        "https://daybook.test",
        reply["token"],
        clock=clock,
        transport=transport,
        rng=random.Random(5),
    )
    ffmpeg, encoder = encoder_or_none()
    recorder = Recorder(tmp / "recordings", clock, ffmpeg=ffmpeg, encoder=encoder, fps=2.0)
    agent = Agent(
        clock=clock,
        sources=make_sim_sources("demo", 1, clock, threaded=False, start=T0),
        detector_for=lambda _source: SimDetector(),
        client=client,
        outbox=Outbox(tmp / "outbox.sqlite3"),
        recorder=recorder,
        config_cache=tmp / "config.json",
        encoder=encoder,
    )
    fake.watch = lambda t: {"sim:counter"} if WATCH[0] <= t < WATCH[1] else set()

    configured_at = clip_id = snapshot_asked_at = None
    for _ in range(int(MINUTES * 60 / STEP)):
        clock.advance(STEP)
        now = clock.time()
        if configured_at is None and fake.cameras:
            # the owner sets the cameras up in the dashboard after they appear
            for key, suggestion in suggest_zones().items():
                fake.set_camera(
                    key, role=suggestion["role"], zones=suggestion["zones"], enabled=True
                )
            configured_at = now
        if snapshot_asked_at is None and now >= T0 + 300:
            fake.request_snapshot("sim:door")
            snapshot_asked_at = now
        if clip_id is None and now >= T0 + 400:
            clip_id = fake.request_clip("sim:counter", now - 40, now - 20)
        agent.tick()
        agent.record_tick()
        agent.net_tick()
        agent.clip_tick()
    # let the last minute close and go out
    clock.advance(2.0)
    agent.housekeeping(clock.time())
    agent._next["stats"] = 0.0
    agent.net_tick()
    recorder.close()
    return {
        "fake": fake,
        "agent": agent,
        "clip_id": clip_id,
        "encoder": encoder,
        "configured_at": configured_at,
        "snapshot_asked_at": snapshot_asked_at,
    }


def test_pairing_and_setup(run):
    fake = run["fake"]
    assert fake.hosts == [{"hostname": "KASSA-PC", "os": "Windows 11", "version": "0.1.0"}]
    assert set(fake.cameras) == {"sim:counter", "sim:door"}
    door = fake.cameras["sim:door"]
    assert door["source"] == "sim" and door["w"] == 960 and door["h"] == 540 and door["online"]
    assert run["configured_at"] - T0 < 1.0
    # every call but pair carried the token; none was refused
    assert all(status < 400 for _m, _p, status in fake.requests)


def test_live_every_five_seconds(run):
    lives = [live for live in run["fake"].lives if live["at"] <= T0 + MINUTES * 60]
    assert 115 <= len(lives) <= 121
    gaps = [b["at"] - a["at"] for a, b in itertools.pairwise(lives)]
    assert min(gaps) >= 4.9 and max(gaps) <= 5.3
    last = lives[-1]["payload"]
    assert last["agent"]["version"] == "0.1.0" and isinstance(last["agent"]["cpu"], int)
    counter = next(c for c in last["cameras"] if c["key"] == "sim:counter")
    assert counter["online"] and counter["fps"] == pytest.approx(2.0, abs=0.2)
    assert set(counter) == {"key", "online", "fps", "people", "queue", "staff", "wait_s", "error"}


def test_minute_stats_each_minute(run):
    stats = run["fake"].stats
    for key in ("sim:counter", "sim:door"):
        minutes = sorted(m for k, m in stats if k == key)
        assert minutes == [iso(T0 + 60 * i) for i in range(MINUTES)], key
    row = stats[("sim:counter", iso(T0 + 240))]
    assert set(row) == {
        "key",
        "minute",
        "frames",
        "people_avg",
        "people_max",
        "entered",
        "exited",
        "queue_avg",
        "queue_max",
        "wait_max_s",
        "staff_seconds",
    }
    assert 110 <= row["frames"] <= 121  # 2 fps
    assert 0 <= row["staff_seconds"] <= 60
    # the rush: the queue reaches 5–6 people, the longest wait passes two minutes
    rush = [stats[("sim:counter", iso(T0 + 60 * i))] for i in (2, 3)]
    assert max(r["queue_max"] for r in rush) >= 5
    assert max(r["wait_max_s"] for r in rush) >= 120
    # the break: minutes with customers and nobody at the counter
    breaks = [stats[("sim:counter", iso(T0 + 60 * i))] for i in (6, 7)]
    assert min(r["staff_seconds"] for r in breaks) == 0
    assert all(r["queue_max"] >= 1 for r in breaks)


def test_entries_come_from_the_door(run):
    stats = run["fake"].stats
    entered = sum(r["entered"] for (k, _m), r in stats.items() if k == "sim:door")
    exited = sum(r["exited"] for (k, _m), r in stats.items() if k == "sim:door")
    assert entered >= 12 and exited >= 8
    assert sum(r["entered"] for (k, _m), r in stats.items() if k == "sim:counter") == 0


def _incidents(events):
    by = defaultdict(list)
    for e in events:
        by[(e["kind"], e["incident_id"])].append(e)
    return by


def test_queue_incident_start_update_end_with_a_photo(run):
    incidents = _incidents(run["fake"].events)
    queue = [v for (kind, _i), v in incidents.items() if kind == "queue"]
    complete = [
        v
        for v in queue
        if [e["phase"] for e in v][:1] == ["start"]
        and "update" in [e["phase"] for e in v]
        and v[-1]["phase"] == "end"
    ]
    assert complete, [[e["phase"] for e in v] for v in queue]
    first = complete[0]
    start, end = first[0], first[-1]
    assert start["image"] and start["image"][:2] == b"\xff\xd8"
    assert all(e["image"] is None for e in first[1:])
    assert start["queue"] >= 3 and start["wait_s"] >= 120
    assert end["peak_queue"] >= start["queue"] and end["peak_wait_s"] >= 120
    assert len({e["event_id"] for e in first}) == len(first)
    updates = [parse_iso(e["at"]) for e in first if e["phase"] == "update"]
    assert all(b - a >= 60 for a, b in itertools.pairwise(updates))
    # Daybook saw it open and then resolved
    alert = run["fake"].alerts[start["incident_id"]]
    assert alert["state"] == "resolved"


def test_unattended_incident(run):
    incidents = _incidents(run["fake"].events)
    unattended = [v for (kind, _i), v in incidents.items() if kind == "unattended"]
    assert unattended
    phases = [e["phase"] for e in unattended[0]]
    assert phases[0] == "start" and phases[-1] == "end"
    start = unattended[0][0]
    assert start["staff"] == 0 and start["queue"] >= 1 and start["image"]
    started = parse_iso(start["at"])
    assert T0 + 320 + 90 <= started <= T0 + 470  # the only pharmacist left at 5:20


def test_frames_only_while_watched(run):
    frames = run["fake"].frames
    assert frames and {f["key"] for f in frames} == {"sim:counter"}
    times = [f["at"] for f in frames]
    assert min(times) >= WATCH[0] and max(times) <= WATCH[1] + 5.5  # the next live report
    assert 40 <= len(frames) <= 2 * (WATCH[1] - WATCH[0] + 6)  # at most live_fps (2) a second
    meta = frames[len(frames) // 2]["meta"]
    assert meta["w"] == 960 and meta["h"] == 540 and meta["people"]
    person = meta["people"][0]
    assert set(person) >= {"track", "box", "role", "zone"} and len(person["box"]) == 4
    assert all(f["size"] <= 400_000 for f in frames)


def test_snapshots_at_start_and_on_request(run):
    fake = run["fake"]
    first = {s["key"]: s["at"] for s in reversed(fake.snapshots)}
    assert set(first) == {"sim:counter", "sim:door"} and max(first.values()) - T0 < 20
    asked = run["snapshot_asked_at"]
    door_later = [s["at"] for s in fake.snapshots if s["key"] == "sim:door" and s["at"] >= asked]
    assert door_later and door_later[0] - asked < 12
    assert all(s["image"][:2] == b"\xff\xd8" for s in fake.snapshots)


def test_clip_job_answered_from_the_recorder(run):
    if not run["encoder"]:
        pytest.skip("no H.264 encoder on this machine")
    clip = run["fake"].clips[run["clip_id"]]
    assert clip["state"] == "ready", clip.get("failed")
    assert clip["meta"]["source"] == "recorder"
    assert clip["meta"]["duration_s"] == pytest.approx(20.0, abs=1.0)
    assert clip["meta"]["w"] == 960 and clip["meta"]["h"] == 540
    video = clip["video"]
    assert video[4:8] == b"ftyp" and 0 < video.find(b"moov") < video.find(b"mdat")  # faststart
    assert clip["poster"][:2] == b"\xff\xd8"


def test_nothing_left_behind(run):
    agent = run["agent"]
    assert agent.outbox.count() == 0
    assert agent.net_state == "ok"
    assert agent.counters["events_sent"] == len(run["fake"].events)
