import pytest

from koz_agent.geometry import (
    extend_segment,
    foot_point,
    iou,
    point_in_polygon,
    segments_intersect,
    side_of_line,
    side_sign,
)
from koz_agent.zones import ZoneError, ZoneSet, parse_zone, parse_zones

SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


def test_foot_point_is_the_bottom_centre():
    assert foot_point((10, 20, 30, 80)) == (20, 80)


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)


def test_point_in_polygon_square_and_concave():
    assert point_in_polygon((0.5, 0.5), SQUARE)
    assert not point_in_polygon((1.5, 0.5), SQUARE)
    # top and left edges are inside, bottom and right outside: neighbours never share a point
    assert point_in_polygon((0.0, 0.5), SQUARE)
    assert point_in_polygon((0.5, 0.0), SQUARE)
    assert not point_in_polygon((1.0, 0.5), SQUARE)
    assert not point_in_polygon((0.5, 1.0), SQUARE)
    u_shape = [(0, 0), (3, 0), (3, 3), (2, 3), (2, 1), (1, 1), (1, 3), (0, 3)]
    assert point_in_polygon((0.5, 2.5), u_shape)
    assert not point_in_polygon((1.5, 2.5), u_shape)  # inside the notch
    assert point_in_polygon((2.5, 2.5), u_shape)


def test_side_of_line_in_image_coordinates():
    a, b = (0.1, 0.6), (0.9, 0.6)  # drawn left to right
    below, above = (0.5, 0.8), (0.5, 0.4)
    assert side_of_line(below, a, b) == 1  # a positive cross product (y down)
    assert side_of_line(above, a, b) == -1
    assert side_of_line((0.5, 0.601), a, b, margin=0.01) == 0
    # walking A→B on the screen, your left hand points up: "left" is above this line
    assert side_sign("left") == side_of_line(above, a, b)
    assert side_sign("right") == side_of_line(below, a, b)
    # reversing the line swaps the sides
    assert side_of_line(below, b, a) == -1


def test_segments_intersect():
    assert segments_intersect((0, 0), (2, 2), (0, 2), (2, 0))
    assert not segments_intersect((0, 0), (1, 1), (2, 0), (3, 1))
    assert segments_intersect((0, 0), (2, 0), (1, 0), (1, 5))  # touching
    assert not segments_intersect((5, -1), (5, 1), (0, 0), (2, 0))  # beyond the end
    ea, eb = extend_segment((0, 0), (2, 0), 1.0)
    assert ea == (-1.0, 0.0) and eb == (3.0, 0.0)


def test_zone_validation_follows_the_contract():
    line = parse_zone(
        {"id": "l1", "kind": "line", "points": [[0.1, 0.6], [0.9, 0.62]], "in": "left"}
    )
    assert line.inside == "left"
    with pytest.raises(ZoneError):
        parse_zone({"id": "L1", "kind": "queue", "points": SQUARE})  # upper case id
    with pytest.raises(ZoneError):
        parse_zone({"id": "q1", "kind": "queue", "points": [[0, 0], [1, 0]]})  # 2 points
    with pytest.raises(ZoneError):
        parse_zone({"id": "q1", "kind": "queue", "points": [[0, 0], [1.2, 0], [1, 1]]})
    with pytest.raises(ZoneError):
        parse_zone({"id": "l1", "kind": "line", "points": [[0, 0], [1, 1]], "in": "up"})
    with pytest.raises(ZoneError):
        parse_zone({"id": "x", "kind": "door", "points": SQUARE})
    many = [{"id": f"f{i}", "kind": "floor", "points": SQUARE} for i in range(10)]
    assert len(parse_zones(many)) == 8
    dupes = [{"id": "q1", "kind": "queue", "points": SQUARE}] * 2
    assert len(parse_zones(dupes)) == 1
    with pytest.raises(ZoneError):
        parse_zones(dupes, strict=True)


def test_zone_set_lookups():
    zs = ZoneSet.from_json(
        [
            {"id": "q1", "kind": "queue", "points": [[0, 0.5], [1, 0.5], [1, 1], [0, 1]]},
            {"id": "s1", "kind": "staff", "points": [[0, 0], [1, 0], [1, 0.5], [0, 0.5]]},
            {"id": "f1", "kind": "floor", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]},
            {"id": "m1", "kind": "mask", "points": [[0.9, 0.9], [1, 0.9], [1, 1], [0.9, 1]]},
        ]
    )
    assert zs.zone_of((0.5, 0.7)) == "q1"
    assert zs.zone_of((0.5, 0.2)) == "s1"
    assert zs.staff_zone((0.5, 0.2)) == "s1" and zs.queue_zone((0.5, 0.2)) is None
    assert zs.in_mask((0.95, 0.95)) and not zs.in_mask((0.5, 0.5))
    assert zs.has_queue and zs.has_staff
    assert ZoneSet.from_json(zs.to_json()).to_json() == zs.to_json()
