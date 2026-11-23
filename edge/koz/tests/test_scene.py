"""The generated scene: determinism, its boxes and zones, and the stories of the four scenes."""

import hashlib

import numpy as np
import pytest

from koz_agent.analysis import CameraAnalyzer
from koz_agent.scene import CAMERAS, SCENES, Scene, suggest_zones
from koz_agent.scene.world import World
from koz_agent.zones import ZoneSet, parse_zones

from .conftest import T0


def digest(image: np.ndarray) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def test_same_seed_same_pictures_and_boxes():
    a, b = Scene("demo", 7, T0), Scene("demo", 7, T0)
    for t in (0.0, 33.3, 61.0, 125.5):
        for key in CAMERAS:
            ia, ta = a.frame(key, T0 + t)
            ib, tb = b.frame(key, T0 + t)
            assert digest(ia) == digest(ib)
            assert [d.box for d in ta] == [d.box for d in tb]


def test_another_seed_brings_other_people():
    a, b = World("demo", 1), World("demo", 2)
    a.advance_to(150)
    b.advance_to(150)
    pos_a = sorted((round(x.x), round(x.y)) for x in a.actors.values() if x.kind == "customer")
    pos_b = sorted((round(x.x), round(x.y)) for x in b.actors.values() if x.kind == "customer")
    assert pos_a != pos_b


def test_pictures_are_960x540_with_boxes_inside():
    scene = Scene("rush", 3, T0)
    seen = 0
    for t in range(0, 200, 7):
        for key in CAMERAS:
            image, truth = scene.frame(key, T0 + t)
            assert image.shape == (540, 960, 3) and image.dtype == np.uint8
            for det in truth:
                x1, y1, x2, y2 = det.box
                assert 0 <= x1 < x2 <= 960 and 0 <= y1 < y2 <= 540
                seen += 1
    assert seen > 50


def test_suggested_zones_are_valid_and_fit_the_roles():
    zones = suggest_zones()
    assert set(zones) == set(CAMERAS)
    assert zones["sim:counter"]["role"] == "counter" and zones["sim:door"]["role"] == "entrance"
    for item in zones.values():
        assert parse_zones(item["zones"], strict=True)
    kinds = {z["kind"] for z in zones["sim:counter"]["zones"]}
    assert {"queue", "staff", "mask"} <= kinds
    assert [z["kind"] for z in zones["sim:door"]["zones"]][:1] == ["line"]


def test_true_boxes_land_in_the_right_zones():
    """Pharmacists' feet fall in the staff zone, customers' in the queue zone."""
    scene = Scene("demo", 1, T0)
    zones = ZoneSet.from_json(suggest_zones()["sim:counter"]["zones"])
    for t in range(2, 470, 9):
        _image, truth = scene.frame("sim:counter", T0 + t)
        actors = scene.world.in_view("counter")
        staff = sum(1 for a in actors if a.kind == "staff")
        waiting = sum(1 for a in actors if a.kind == "customer" and a.y >= 340 and 20 <= a.x <= 940)
        result = CameraAnalyzer(zones).process(truth, T0 + t, 960, 540)
        assert result.staff == staff, t
        assert result.queue == waiting, t


def queue_and_staff(scene: str, seed: int, until: float, step: float = 1.0):
    world = World(scene, seed)
    rows = []
    t = 0.0
    while t <= until:
        world.advance_to(t)
        c = world.counts()
        rows.append((t, c["queue"], c["staff_present"]))
        t += step
    return rows


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_demo_is_calm_then_a_rush_then_a_break(seed):
    rows = queue_and_staff("demo", seed, 480)
    rush = [q for t, q, _s in rows if 120 <= t <= 200]
    assert 5 <= max(rush) <= 8
    alone = [s for t, _q, s in rows if 60 <= t <= 195]
    assert set(alone) == {1}  # one pharmacist through the rush
    nobody = [(q, s) for t, q, s in rows if 330 <= t <= 445]
    assert all(s == 0 for _q, s in nobody) and max(q for q, _s in nobody) >= 1
    assert max(s for t, _q, s in rows if 205 <= t <= 285) == 2  # Kassa 2 opens after the rush
    back = [s for t, _q, s in rows if t >= 460]
    assert back[-1] == 1  # the pharmacist is back before the loop starts over
    assert World("demo", seed).script.loop_s == 480


@pytest.mark.parametrize("seed", [1, 2])
def test_rush_queue_grows_to_5_or_6(seed):
    rows = queue_and_staff("rush", seed, 360)
    assert 5 <= max(q for _t, q, _s in rows) <= 7
    assert max(q for t, q, _s in rows if t >= 300) <= 3  # and eases


def test_break_one_pharmacist_away_2_to_3_minutes():
    rows = queue_and_staff("break", 1, 330, step=0.5)
    away = [t for t, _q, s in rows if s == 0]
    assert away and 120 <= away[-1] - away[0] <= 180
    assert max(s for _t, _q, s in rows) == 1
    assert max(q for t, q, _s in rows if away[0] <= t <= away[-1]) >= 2


def test_calm_stays_calm():
    rows = queue_and_staff("calm", 1, 300)
    assert max(q for _t, q, _s in rows) <= 3


def test_every_scene_renders():
    for name in SCENES:
        scene = Scene(name, 1, T0)
        for key in CAMERAS:
            image, _truth = scene.frame(key, T0 + 45)
            assert image.std() > 10  # a real picture, not a blank


def test_door_shows_people_coming_and_going():
    world = World("demo", 1)
    entering = leaving = 0
    for t in range(0, 300):
        world.advance_to(t)
        for actor in world.in_view("door"):
            if actor.state == "door_in":
                entering += 1
            elif actor.state == "door_out":
                leaving += 1
    assert entering > 10 and leaving > 10
