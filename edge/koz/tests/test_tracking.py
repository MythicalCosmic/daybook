"""The tracker, line crossings and waits in queue zones."""

from koz_agent.analysis import CameraAnalyzer
from koz_agent.frames import Detection
from koz_agent.tracker import Tracker
from koz_agent.zones import ZoneSet

W, H = 960, 540


def person(cx, foot_y, h=120, w=50):
    return Detection((cx - w / 2, foot_y - h, cx + w / 2, foot_y))


def test_ids_stay_stable_while_people_walk():
    tracker = Tracker()
    ids_a, ids_b = set(), set()
    for i in range(20):
        t = i * 0.5
        # A walks right 40 px per frame, B walks left; they pass each other at i = 10
        a = person(100 + 40 * i, 400)
        b = person(900 - 40 * i, 300)
        tracks = tracker.update([a, b], t)
        by_foot = {(round((tr.box[0] + tr.box[2]) / 2), round(tr.box[3])): tr.id for tr in tracks}
        ids_a.add(by_foot[(100 + 40 * i, 400)])
        ids_b.add(by_foot[(900 - 40 * i, 300)])
    assert len(ids_a) == 1 and len(ids_b) == 1 and ids_a != ids_b


def test_fast_walker_keeps_id_by_centroid_and_prediction():
    tracker = Tracker()
    ids = set()
    for i in range(8):
        # 70 px per frame: boxes 50 px wide never overlap, the centroid stage matches them
        tracks = tracker.update([person(100 + 70 * i, 400)], i * 0.5)
        ids.add(tracks[0].id)
    assert ids == {1}


def test_track_survives_a_short_miss_and_is_dropped_later():
    tracker = Tracker(max_age_s=2.0)
    tracker.update([person(400, 400)], 0.0)
    assert tracker.update([], 0.5) == []
    tracks = tracker.update([person(405, 400)], 1.0)
    assert [tr.id for tr in tracks] == [1]
    tracker.update([], 1.5)
    tracker.update([], 3.6)
    assert tracker.tracks == {}
    assert tracker.update([person(405, 400)], 4.0)[0].id == 2


LINE = [{"id": "l1", "kind": "line", "points": [[0.2, 0.5], [0.8, 0.5]], "in": "right"}]


def walk(analyzer, xs_ys, start=0.0, step=0.5):
    results = []
    for i, (x, y) in enumerate(xs_ys):
        results.append(analyzer.process([person(x * W, y * H)], start + i * step, W, H))
    return results


def test_crossing_into_the_in_side_counts_entered_then_exited():
    analyzer = CameraAnalyzer(ZoneSet.from_json(LINE))
    down = [(0.5, y) for y in (0.30, 0.38, 0.46, 0.54, 0.62, 0.70)]
    results = walk(analyzer, down)
    assert sum(r.entered for r in results) == 1  # below a left-to-right line is "right" → inside
    assert sum(r.exited for r in results) == 0
    back = walk(analyzer, list(reversed(down)), start=10.0)
    assert sum(r.exited for r in back) == 1 and sum(r.entered for r in back) == 0


def test_in_left_flips_the_direction():
    zones = [dict(LINE[0], **{"in": "left"})]
    analyzer = CameraAnalyzer(ZoneSet.from_json(zones))
    results = walk(analyzer, [(0.5, y) for y in (0.3, 0.4, 0.6, 0.7)])
    assert sum(r.exited for r in results) == 1 and sum(r.entered for r in results) == 0


def test_jitter_on_the_line_does_not_count():
    analyzer = CameraAnalyzer(ZoneSet.from_json(LINE))
    jitter = [(0.5, 0.44)] + [(0.5, 0.5 + d) for d in (0.004, -0.004, 0.005, -0.003, 0.002)]
    results = walk(analyzer, jitter)
    assert sum(r.entered + r.exited for r in results) == 0


def test_walking_round_the_end_of_the_line_does_not_count():
    analyzer = CameraAnalyzer(ZoneSet.from_json(LINE))
    path = [(0.92, 0.3), (0.95, 0.45), (0.95, 0.55), (0.92, 0.7)]  # beyond x = 0.8
    results = walk(analyzer, path)
    assert sum(r.entered + r.exited for r in results) == 0


def test_people_in_masks_are_ignored():
    zones = ZoneSet.from_json(
        [{"id": "m1", "kind": "mask", "points": [[0, 0], [0.3, 0], [0.3, 1], [0, 1]]}]
    )
    result = CameraAnalyzer(zones).process([person(100, 400), person(600, 400)], 0.0, W, H)
    assert result.people_count == 1


QUEUE = [
    {"id": "q1", "kind": "queue", "points": [[0, 0.6], [1, 0.6], [1, 1], [0, 1]]},
    {"id": "s1", "kind": "staff", "points": [[0, 0.2], [1, 0.2], [1, 0.5], [0, 0.5]]},
]


def test_waits_grow_in_the_queue_and_reset_after_leaving():
    analyzer = CameraAnalyzer(ZoneSet.from_json(QUEUE), queue_grace_s=3.0)
    r = None
    for i in range(61):  # 30 s standing in the queue
        r = analyzer.process([person(300, 450), person(600, 250)], i * 0.5, W, H)
    assert r.queue == 1 and r.staff == 1 and r.wait_s == 30
    customer = next(p for p in r.people if p.in_queue)
    staff = next(p for p in r.people if p.in_staff)
    assert customer.role == "customer" and customer.zone == "q1"
    assert staff.role == "staff" and staff.wait_s is None and staff.zone == "s1"
    meta = customer.to_meta()
    assert meta["wait_s"] == 30 and len(meta["box"]) == 4 and meta["role"] == "customer"
    assert "wait_s" not in staff.to_meta()
    # a 1 s step out of the zone (it starts at y = 324 px) keeps the wait; 5 s away resets it
    for t, y in ((30.5, 400), (31.0, 350), (31.5, 310), (32.0, 310), (32.5, 350), (33.0, 400)):
        r = analyzer.process([person(300, y)], t, W, H)
    assert r.wait_s == 33 and r.people[0].track == 1
    for i, y in enumerate([350, 310] + [310] * 10 + [350, 400]):
        r = analyzer.process([person(300, y)], 33.5 + i * 0.5, W, H)
    assert r.people[0].track == 1 and r.queue == 1 and r.wait_s == 0


def test_longest_wait_is_reported():
    analyzer = CameraAnalyzer(ZoneSet.from_json(QUEUE))
    r = None
    for i in range(41):
        t = i * 0.5
        people = [person(200, 450)] + ([person(500, 450)] if t >= 10 else [])
        r = analyzer.process(people, t, W, H)
    assert r.queue == 2 and r.wait_s == 20
    assert sorted(p.wait_s for p in r.people) == [10, 20]
