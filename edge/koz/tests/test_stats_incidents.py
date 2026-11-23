"""Minute aggregation (§5.7) and the incident hysteresis (§5.8)."""

from itertools import count

from koz_agent.analysis import Crossing, FrameResult, Person
from koz_agent.incidents import IncidentEngine
from koz_agent.rules import Rules
from koz_agent.stats import MinuteAggregator

T0 = 1_795_438_800.0  # 13:00:00Z


def frame(t, people=0, queue=0, staff=0, wait=0, entered=0, exited=0):
    persons = []
    for i in range(people):
        in_queue = i < queue
        in_staff = queue <= i < queue + staff
        persons.append(
            Person(
                track=i + 1,
                box=(0.1, 0.1, 0.2, 0.5),
                foot=(0.15, 0.5),
                role="staff" if in_staff else "customer",
                zone=None,
                in_queue=in_queue,
                in_staff=in_staff,
                wait_s=float(wait) if in_queue else None,
            )
        )
    crossings = [Crossing(1, "l1", "entered")] * entered + [Crossing(2, "l1", "exited")] * exited
    return FrameResult(t=t, w=960, h=540, people=persons, crossings=crossings)


def test_minute_rows():
    agg = MinuteAggregator("sim:counter")
    for i in range(240):  # two minutes at 2 fps
        t = T0 + i * 0.5
        first = i < 120
        agg.add(
            frame(
                t,
                people=3 if first else 1,
                queue=2 if first else 0,
                staff=1 if first else 0,
                wait=40 if first else 0,
                entered=1 if i == 5 else 0,
                exited=1 if i == 130 else 0,
            )
        )
    assert agg.close_until(T0 + 60.5) == []  # still within the grace second
    rows = agg.close_until(T0 + 61.0)
    assert rows == [
        {
            "key": "sim:counter",
            "minute": "2026-11-23T13:00:00Z",
            "frames": 120,
            "people_avg": 3.0,
            "people_max": 3,
            "entered": 1,
            "exited": 0,
            "queue_avg": 2.0,
            "queue_max": 2,
            "wait_max_s": 40,
            "staff_seconds": 60,
        }
    ]
    rows = agg.close_until(T0 + 200)
    assert len(rows) == 1 and rows[0]["minute"] == "2026-11-23T13:01:00Z"
    assert rows[0]["exited"] == 1 and rows[0]["staff_seconds"] == 0 and rows[0]["people_avg"] == 1.0


def test_staff_seconds_split_at_the_minute_and_capped_over_gaps():
    agg = MinuteAggregator("k", hold_cap_s=3.0)
    agg.add(frame(T0 + 50, people=1, staff=1))
    agg.add(frame(T0 + 52, people=1, staff=1))
    agg.add(frame(T0 + 58, people=1, staff=1))  # gap of 6 s: only 3 s held
    agg.add(frame(T0 + 61, people=1, staff=0))  # 58→61 splits: 2 s here, 1 s next minute
    agg.add(frame(T0 + 70, people=0))
    first, second = agg.close_until(T0 + 125)
    assert first["staff_seconds"] == 2 + 3 + 2  # 50→52, 52→55, 58→60
    assert second["staff_seconds"] == 1
    assert first["frames"] == 3 and second["frames"] == 2


def test_minutes_without_frames_are_not_reported():
    agg = MinuteAggregator("k")
    agg.add(frame(T0 + 59.5, people=1, staff=1))
    rows = agg.close_until(T0 + 300)
    assert [r["minute"] for r in rows] == ["2026-11-23T13:00:00Z"]


def ids():
    c = count(1)
    return lambda: f"id-{next(c)}"


def engine(**rules):
    eng = IncidentEngine("sim:counter", new_id=ids())
    eng.configure(Rules.from_dict(rules), is_counter=True, has_queue=True, has_staff=True, at=T0)
    return eng


def run(eng, start, seconds, **state):
    events = []
    for i in range(int(seconds * 2)):
        events += eng.step(start + i * 0.5, state["queue"], state["wait"], state["staff"])
    return events


def test_queue_starts_after_5_s_and_ends_after_clear():
    eng = engine(queue_people=3, queue_wait_s=120, clear_after_s=15)
    assert run(eng, T0, 4.5, queue=3, wait=130, staff=1) == []
    events = run(eng, T0 + 4.5, 2, queue=4, wait=131, staff=1)
    assert [e["phase"] for e in events] == ["start"]
    start = events[0]
    assert start["kind"] == "queue" and start["at"] == start["started_at"]
    assert start["queue"] == 4 and start["peak_queue"] == 4 and start["wait_s"] == 131
    assert set(start) == {"event_id", "incident_id", "kind", "phase", "key", "at", "started_at",
                          "queue", "wait_s", "staff", "peak_queue", "peak_wait_s"}
    # a dip shorter than clear_after_s does not end it
    assert run(eng, T0 + 10, 10, queue=2, wait=140, staff=1) == []
    events = run(eng, T0 + 20, 20, queue=6, wait=200, staff=1)
    assert events == []
    events = run(eng, T0 + 40, 16, queue=1, wait=30, staff=1)
    assert [e["phase"] for e in events] == ["end"]
    end = events[0]
    assert end["incident_id"] == start["incident_id"] and end["peak_queue"] == 6
    assert end["peak_wait_s"] == 200 and end["started_at"] == start["started_at"]


def test_queue_needs_5_s_in_a_row():
    eng = engine()
    events = []
    for i in range(40):
        active = i % 8 < 7  # interrupted every 4 s
        events += eng.step(T0 + i * 0.5, 4 if active else 1, 150, 1)
    assert events == []


def test_updates_at_most_once_a_minute():
    eng = engine()
    events = run(eng, T0, 200, queue=4, wait=150, staff=1)
    phases = [e["phase"] for e in events]
    assert phases == ["start", "update", "update", "update"]
    times = [e["at"] for e in events]
    assert len(set(times)) == 4


def test_unattended_starts_after_unattended_s_and_ends_with_staff():
    eng = engine(unattended_s=90, clear_after_s=15)
    assert run(eng, T0, 89, queue=1, wait=60, staff=0) == []
    events = run(eng, T0 + 89, 2, queue=1, wait=150, staff=0)
    assert [(e["kind"], e["phase"]) for e in events] == [("unattended", "start")]
    events = run(eng, T0 + 91, 16, queue=2, wait=170, staff=1)
    assert [(e["kind"], e["phase"]) for e in events] == [("unattended", "end")]


def test_unattended_ends_when_nobody_waits():
    eng = engine(unattended_s=30)
    run(eng, T0, 31, queue=1, wait=10, staff=0)
    events = run(eng, T0 + 31, 20, queue=0, wait=0, staff=0)
    assert [e["phase"] for e in events] == ["end"]


def test_only_counter_cameras_with_zones_raise_alerts():
    eng = IncidentEngine("sim:door")
    eng.configure(Rules(), is_counter=False, has_queue=True, has_staff=True, at=T0)
    assert run(eng, T0, 200, queue=5, wait=300, staff=0) == []
    eng = IncidentEngine("k")
    eng.configure(Rules(), is_counter=True, has_queue=True, has_staff=False, at=T0)
    events = run(eng, T0, 200, queue=5, wait=300, staff=0)
    assert {e["kind"] for e in events} == {"queue"}


def test_losing_the_zone_or_the_camera_ends_open_incidents():
    eng = engine()
    run(eng, T0, 10, queue=4, wait=150, staff=1)
    events = eng.configure(Rules(), is_counter=False, has_queue=True, has_staff=True, at=T0 + 10)
    assert [e["phase"] for e in events] == ["end"]
    eng = engine()
    run(eng, T0, 10, queue=4, wait=150, staff=1)
    assert eng.check_stale(T0 + 30) == []
    assert [e["phase"] for e in eng.check_stale(T0 + 80)] == ["end"]
