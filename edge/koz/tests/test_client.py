"""The Daybook client (httpx.MockTransport) and its offline queue."""

import json
import random

import httpx
import pytest

from koz_agent.agent import Agent
from koz_agent.client import DaybookClient, DaybookError, OfflineError, RevokedError
from koz_agent.clock import FakeClock, iso
from koz_agent.detectors import SimDetector
from koz_agent.devserver import FakeDaybook, parse_multipart
from koz_agent.outbox import Outbox
from koz_agent.sources import make_sim_sources

from .conftest import T0

TOKEN = "koz_" + "a" * 40


def client_with(handler, **kwargs):
    clock = FakeClock(T0)
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request):
        request.read()
        seen.append(request)
        return handler(request)

    client = DaybookClient("https://daybook.test/", TOKEN, clock=clock,
                           transport=httpx.MockTransport(wrapped), rng=random.Random(3), **kwargs)
    return client, clock, seen


def test_token_header_and_paths():
    client, _clock, seen = client_with(lambda r: httpx.Response(200, json={"watch": ["nvr:3"]}))
    assert client.live({"at": "x"}) == {"watch": ["nvr:3"]}
    assert seen[0].url.path == "/api/v1/devices/koz/live/"
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert seen[0].headers["user-agent"].startswith("koz-agent/")
    client.pair("KOZ-7F3K-92QD", {"hostname": "KASSA-PC"})
    assert seen[1].url.path == "/api/v1/devices/koz/pair/" and "authorization" not in seen[1].headers
    assert json.loads(seen[1].content) == {"code": "KOZ-7F3K-92QD", "host": {"hostname": "KASSA-PC"}}
    client.frame("sim:counter", b"\xff\xd8jpeg", {"at": "t"})
    assert seen[2].url.path == "/api/v1/devices/koz/frames/sim:counter/"


def test_retries_5xx_with_exponential_backoff_and_jitter():
    replies = [httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"ok": 1})]
    client, clock, seen = client_with(lambda r: replies.pop(0))
    assert client.config() == {"ok": 1}
    assert len(seen) == 3
    waited = clock.time() - T0
    assert 0.25 + 0.5 <= waited < 0.75 + 1.5  # 0.5 s then 1 s, each ×0.5–1.5
    delays = [client.backoff(a) for a in range(8)]
    assert all(0.5 * min(8.0, 0.5 * 2**a) <= d < 1.5 * min(8.0, 0.5 * 2**a)
               for a, d in enumerate(delays))


def test_network_errors_become_offline_after_the_retries():
    def down(request):
        raise httpx.ConnectError("no route", request=request)

    client, _clock, seen = client_with(down)
    with pytest.raises(OfflineError):
        client.stats([])
    assert len(seen) == 3 and client.last_error.startswith("ConnectError")


def test_client_errors_are_not_retried():
    client, _clock, seen = client_with(
        lambda r: httpx.Response(422, json={"detail": "bad zones", "code": "invalid"}))
    with pytest.raises(DaybookError) as caught:
        client.cameras([])
    assert caught.value.status == 422 and caught.value.code == "invalid" and len(seen) == 1


def test_revoked_token_gets_one_try_every_10_minutes():
    accept = {"now": False}

    def handler(request):
        if accept["now"]:
            return httpx.Response(200, json={"config_version": "1"})
        return httpx.Response(401, json={"detail": "revoked", "code": "revoked"})

    client, clock, seen = client_with(handler)
    with pytest.raises(RevokedError):
        client.config()
    assert len(seen) == 1 and client.revoked
    for _ in range(5):
        clock.advance(100)
        with pytest.raises(RevokedError):
            client.live({})
    assert len(seen) == 1  # nothing went out within the 10 minutes
    clock.advance(101)
    with pytest.raises(RevokedError):
        client.config()
    assert len(seen) == 2  # one try after 10 minutes, refused again
    clock.advance(600)
    accept["now"] = True
    assert client.config() == {"config_version": "1"}
    assert not client.revoked and len(seen) == 3


def test_uploads_are_multipart():
    client, _clock, seen = client_with(lambda r: httpx.Response(204))

    def fields(request):
        return parse_multipart(request.headers["content-type"], request.content)

    client.snapshot("nvr:3", b"\xff\xd8snap")
    assert fields(seen[-1])["image"] == ("snapshot.jpg", b"\xff\xd8snap")
    client.frame("nvr:3", b"\xff\xd8f", {"w": 960})
    part = fields(seen[-1])
    assert part["image"][1] == b"\xff\xd8f" and json.loads(part["meta"][1]) == {"w": 960}
    client.event({"event_id": "e1", "phase": "update"})
    part = fields(seen[-1])
    assert json.loads(part["event"][1])["event_id"] == "e1" and "image" not in part
    client.event({"event_id": "e2", "phase": "start"}, b"\xff\xd8photo")
    assert fields(seen[-1])["image"][1] == b"\xff\xd8photo"
    client.clip(55, b"\x00\x00\x00\x18ftypmp42", b"\xff\xd8poster", {"duration_s": 20.0})
    part = fields(seen[-1])
    assert set(part) == {"meta", "video", "poster"} and seen[-1].url.path.endswith("/clips/55/")
    client.clip_failed(56, "not_recorded", "no recording")
    assert json.loads(seen[-1].content) == {"failed": "not_recorded", "detail": "no recording"}


def test_outbox_survives_a_restart(tmp_path):
    path = tmp_path / "outbox.sqlite3"
    box = Outbox(path)
    box.put_stats([{"key": "k", "minute": iso(T0 + 60 * i)} for i in range(3)], created=T0)
    box.put_event({"event_id": "a", "phase": "start"}, b"\xff\xd8img", created=T0)
    box.put_event({"event_id": "b", "phase": "end"}, None, created=T0 + 5)
    box.close()
    box = Outbox(path)
    assert box.count("stats") == 3 and box.count("event") == 2
    events = box.peek("event", 10)
    assert [e[1]["event_id"] for e in events] == ["a", "b"]
    assert events[0][2] == b"\xff\xd8img" and events[1][2] is None
    box.delete([events[0][0]])
    assert [e[1]["event_id"] for e in box.peek("event", 10)] == ["b"]


def test_outbox_batches_and_forgets_after_7_days(tmp_path):
    box = Outbox(tmp_path / "o.sqlite3")
    box.put_stats([{"i": i} for i in range(2500)], created=T0)
    batch = box.peek("stats", 2000)
    assert len(batch) == 2000 and batch[0][1] == {"i": 0} and batch[-1][1] == {"i": 1999}
    box.put_event({"event_id": "new"}, None, created=T0 + 6 * 86400)
    assert box.purge(T0 + 7 * 86400 + 1) == 2500
    assert box.count() == 1


def test_agent_keeps_stats_and_events_while_offline(tmp_path):
    """Daybook goes away for 3 minutes; nothing is lost and it all arrives later, in order."""
    clock = FakeClock(T0)
    fake = FakeDaybook(clock, auto_setup=True)
    fake.tokens = {TOKEN}
    client = DaybookClient("https://daybook.test", TOKEN, clock=clock, transport=fake.transport(),
                           rng=random.Random(1))
    agent = Agent(clock=clock, sources=make_sim_sources("break", 2, clock, threaded=False, start=T0),
                  detector_for=lambda _s: SimDetector(), client=client,
                  outbox=Outbox(tmp_path / "outbox.sqlite3"))
    states = set()
    for i in range(int(420 / 0.1)):
        clock.advance(0.1)
        now = clock.time()
        fake.down = T0 + 60 <= now < T0 + 240
        agent.tick()
        agent.net_tick()
        states.add(agent.net_state)
        if fake.down and now > T0 + 230:
            assert agent.outbox.count("stats") >= 2 * 2  # two cameras, minutes 1–2 at least
    clock.advance(2)
    agent.housekeeping(clock.time())
    agent._next["stats"] = 0
    agent.net_tick()
    assert {"ok", "offline"} <= states
    for key in ("sim:counter", "sim:door"):
        minutes = sorted(m for k, m in fake.stats if k == key)
        assert minutes == [iso(T0 + 60 * i) for i in range(7)]
    assert agent.outbox.count() == 0
    phases = [(e["kind"], e["phase"]) for e in fake.events]
    assert ("unattended", "start") in phases and ("unattended", "end") in phases
    starts = [e for e in fake.events if e["phase"] == "start"]
    assert all(e["image"] for e in starts if e["kind"] == "unattended")
