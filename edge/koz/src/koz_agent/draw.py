"""Drawing helpers on top of OpenCV: colours, anti-aliased shapes, translucent fills and text.

Text uses OpenCV 5's built-in sans font (anti-aliased, Latin and Cyrillic, weights 100–900); on an
older OpenCV it falls back to the Hershey font so nothing breaks.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

import cv2
import numpy as np

AA = cv2.LINE_AA
BGR = tuple[int, int, int]


@lru_cache(maxsize=256)
def hexc(value: str) -> BGR:
    """``#RRGGBB`` → a BGR tuple."""
    v = value.lstrip("#")
    return (int(v[4:6], 16), int(v[2:4], 16), int(v[0:2], 16))


def mix(a: BGR, b: BGR, t: float) -> BGR:
    """``a`` moved towards ``b`` by ``t`` (0..1)."""
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def shade(c: BGR, f: float) -> BGR:
    """Darker for f < 1, lighter towards white for f > 1."""
    if f <= 1:
        return (round(c[0] * f), round(c[1] * f), round(c[2] * f))
    return mix(c, (255, 255, 255), min(1.0, f - 1.0))


def ipt(p: Sequence[float]) -> tuple[int, int]:
    return (round(p[0]), round(p[1]))


def poly(img: np.ndarray, points: Sequence[Sequence[float]], color: BGR) -> None:
    pts = np.array([ipt(p) for p in points], np.int32)
    cv2.fillPoly(img, [pts], color, AA)


def polyline(
    img: np.ndarray, points: Sequence[Sequence[float]], color: BGR, thickness: int = 1, closed=True
) -> None:
    pts = np.array([ipt(p) for p in points], np.int32)
    cv2.polylines(img, [pts], closed, color, thickness, AA)


def circle(img: np.ndarray, c: Sequence[float], r: float, color: BGR, thickness: int = -1) -> None:
    cv2.circle(img, ipt(c), max(1, round(r)), color, thickness, AA)


def ellipse(
    img: np.ndarray,
    c: Sequence[float],
    axes: Sequence[float],
    color: BGR,
    angle: float = 0,
    start: float = 0,
    end: float = 360,
    thickness: int = -1,
) -> None:
    cv2.ellipse(
        img, ipt(c), (max(1, round(axes[0])), max(1, round(axes[1]))), angle, start, end, color,
        thickness, AA,
    )


def capsule(
    img: np.ndarray, a: Sequence[float], b: Sequence[float], width: float, color: BGR
) -> None:
    cv2.line(img, ipt(a), ipt(b), color, max(1, round(width)), AA)
    circle(img, a, width / 2, color)
    circle(img, b, width / 2, color)


def rounded_rect(
    img: np.ndarray,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    color: BGR,
    thickness: int = -1,
) -> None:
    x1, y1, x2, y2 = round(x1), round(y1), round(x2), round(y2)
    r = int(max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2)))
    if thickness < 0:
        if r <= 0:
            cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
            return
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        for cx, cy in ((x1 + r, y1 + r), (x2 - r, y1 + r), (x1 + r, y2 - r), (x2 - r, y2 - r)):
            cv2.circle(img, (cx, cy), r, color, -1, AA)
        return
    if r <= 0:
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness, AA)
        return
    t = thickness
    cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, t, AA)
    cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, t, AA)
    cv2.line(img, (x1, y1 + r), (x1, y2 - r), color, t, AA)
    cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, t, AA)
    cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180, 0, 90, color, t, AA)
    cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270, 0, 90, color, t, AA)
    cv2.ellipse(img, (x2 - r, y2 - r), (r, r), 0, 0, 90, color, t, AA)
    cv2.ellipse(img, (x1 + r, y2 - r), (r, r), 90, 0, 90, color, t, AA)


def blend_region(img: np.ndarray, x1: int, y1: int, x2: int, y2: int, draw, alpha: float) -> None:
    """Draw with ``draw(canvas, ox, oy)`` on a copy of a region and blend it back at ``alpha``.

    ``draw`` receives the region and its origin, so it can draw in frame coordinates by
    subtracting ``ox, oy``.
    """
    h, w = img.shape[:2]
    x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    layer = roi.copy()
    draw(layer, x1, y1)
    cv2.addWeighted(layer, alpha, roi, 1.0 - alpha, 0, dst=roi)


def translucent_poly(
    img: np.ndarray, points: Sequence[Sequence[float]], color: BGR, alpha: float
) -> None:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1, y1, x2, y2 = int(min(xs)) - 2, int(min(ys)) - 2, int(max(xs)) + 3, int(max(ys)) + 3

    def draw(layer, ox, oy):
        poly(layer, [(x - ox, y - oy) for x, y in points], color)

    blend_region(img, x1, y1, x2, y2, draw, alpha)


def shadow_ellipse(img: np.ndarray, c: Sequence[float], axes: Sequence[float], strength=0.22):
    x1, y1 = c[0] - axes[0] - 2, c[1] - axes[1] - 2
    x2, y2 = c[0] + axes[0] + 3, c[1] + axes[1] + 3

    def draw(layer, ox, oy):
        ellipse(layer, (c[0] - ox, c[1] - oy), axes, (40, 40, 40))

    blend_region(img, x1, y1, x2, y2, draw, strength)


# --- text -------------------------------------------------------------------------------------

_HAS_FONTFACE = hasattr(cv2, "FontFace")


@lru_cache(maxsize=4)
def _font(name: str = "sans"):
    return cv2.FontFace(name)


def text_size(text: str, size: float, weight: int = 400) -> tuple[int, int]:
    """Width and cap height of ``text`` at ``size`` pixels."""
    if _HAS_FONTFACE:
        try:
            _x, _y, w, h = cv2.getTextSize((4096, 512), text, (0, 0), _font(), int(size), weight)
            return int(w), int(h)
        except cv2.error:
            pass
    scale = size / 30.0
    thickness = 2 if weight >= 600 else 1
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    return int(w), int(h)


def text(
    img: np.ndarray,
    value: str,
    org: Sequence[float],
    color: BGR,
    size: float = 16,
    weight: int = 400,
    align: str = "left",
) -> int:
    """Draw ``value`` with its baseline at ``org`` (aligned left, centre or right of ``org``).
    Returns the width drawn."""
    w, _h = text_size(value, size, weight)
    x = org[0]
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    if _HAS_FONTFACE:
        try:
            cv2.putText(img, value, ipt((x, org[1])), color, _font(), int(size), weight)
            return w
        except cv2.error:
            pass
    scale = size / 30.0
    thickness = 2 if weight >= 600 else 1
    ascii_value = value.encode("ascii", "replace").decode()
    cv2.putText(img, ascii_value, ipt((x, org[1])), cv2.FONT_HERSHEY_SIMPLEX, scale, color,
                thickness, AA)
    return w


def pill(
    img: np.ndarray,
    value: str,
    org: Sequence[float],
    fg: BGR,
    bg: BGR,
    size: float = 14,
    weight: int = 600,
    pad: tuple[float, float] = (7, 5),
    alpha: float = 1.0,
) -> tuple[int, int, int, int]:
    """A rounded label whose top-left corner is ``org``. Returns its box."""
    w, h = text_size(value, size, weight)
    x1, y1 = org
    x2, y2 = x1 + w + 2 * pad[0], y1 + h + 2 * pad[1]
    if alpha >= 1.0:
        rounded_rect(img, x1, y1, x2, y2, (y2 - y1) / 2, bg)
    else:
        blend_region(
            img, x1 - 1, y1 - 1, x2 + 2, y2 + 2,
            lambda layer, ox, oy: rounded_rect(layer, x1 - ox, y1 - oy, x2 - ox, y2 - oy,
                                               (y2 - y1) / 2, bg),
            alpha,
        )
    text(img, value, (x1 + pad[0], y1 + pad[1] + h), fg, size, weight)
    return round(x1), round(y1), round(x2), round(y2)
