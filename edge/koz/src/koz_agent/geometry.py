"""Plane geometry for zones and tracks. Points are ``(x, y)`` with y pointing down (image
coordinates); boxes are ``(x1, y1, x2, y2)`` unless a name says ``xywh``.

The side of a directed line A→B is named as people see the picture (docs/KOZ.md §4): walking from
A to B, ``left`` is your left hand. Image y grows downwards, so ``left`` is where the cross product
(B − A) × (P − A) is **negative** and ``right`` where it is positive: for a line drawn from left to
right, ``left`` is the side above it. The dashboard's zone editor uses the same rule.
"""

from __future__ import annotations

from collections.abc import Sequence

Point = tuple[float, float]
Box = tuple[float, float, float, float]


def foot_point(box: Box) -> Point:
    """The bottom centre of a box: where a standing person touches the floor."""
    x1, _y1, x2, y2 = box
    return ((x1 + x2) / 2.0, y2)


def centre(box: Box) -> Point:
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def area(box: Box) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def iou(a: Box, b: Box) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def xyxy_to_xywh(box: Box) -> Box:
    x1, y1, x2, y2 = box
    return (x1, y1, x2 - x1, y2 - y1)


def normalize_box(box: Box, w: int, h: int) -> Box:
    x1, y1, x2, y2 = box
    return (x1 / w, y1 / h, x2 / w, y2 / h)


def clip_box(box: Box, w: float, h: float) -> Box:
    x1, y1, x2, y2 = box
    return (min(max(x1, 0.0), w), min(max(y1, 0.0), h), min(max(x2, 0.0), w), min(max(y2, 0.0), h))


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    """Even-odd ray casting. Points exactly on the bottom or right edge count as outside, on the
    top or left edge as inside, so neighbouring zones never both claim a point."""
    x, y = p
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = xi + (y - yi) * (xj - xi) / (yj - yi)
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def cross(a: Point, b: Point, p: Point) -> float:
    """(B − A) × (P − A) in image coordinates."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def side_of_line(p: Point, a: Point, b: Point, margin: float = 0.0) -> int:
    """The sign of the cross product: +1 (``right``), −1 (``left``) or 0 when within ``margin``
    (a distance) of the line."""
    length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    if length == 0:
        return 0
    distance = cross(a, b, p) / length
    if distance > margin:
        return 1
    if distance < -margin:
        return -1
    return 0


def side_sign(name: str) -> int:
    """The :func:`side_of_line` sign of a named side: ``left`` → −1, ``right`` → +1."""
    return -1 if name == "left" else 1


def segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool:
    """True when segment p1–p2 touches or crosses segment q1–q2."""

    def orient(a: Point, b: Point, c: Point) -> int:
        value = cross(a, b, c)
        if abs(value) < 1e-12:
            return 0
        return 1 if value > 0 else -1

    def on_segment(a: Point, b: Point, c: Point) -> bool:
        return min(a[0], b[0]) - 1e-12 <= c[0] <= max(a[0], b[0]) + 1e-12 and (
            min(a[1], b[1]) - 1e-12 <= c[1] <= max(a[1], b[1]) + 1e-12
        )

    o1, o2 = orient(p1, p2, q1), orient(p1, p2, q2)
    o3, o4 = orient(q1, q2, p1), orient(q1, q2, p2)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and on_segment(p1, p2, q1):
        return True
    if o2 == 0 and on_segment(p1, p2, q2):
        return True
    if o3 == 0 and on_segment(q1, q2, p1):
        return True
    return o4 == 0 and on_segment(q1, q2, p2)


def extend_segment(a: Point, b: Point, by: float) -> tuple[Point, Point]:
    """Lengthen a segment by ``by`` (a distance) at both ends."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return a, b
    ux, uy = dx / length * by, dy / length * by
    return (a[0] - ux, a[1] - uy), (b[0] + ux, b[1] + uy)
