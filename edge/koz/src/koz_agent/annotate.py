"""Pictures that leave the agent, and the local preview.

- ``apply_masks``: mask zones are blacked out in everything sent (snapshots, live frames, alert
  photos, recordings).
- ``blur_heads``: with ``privacy_blur``, the top of every person's box is blurred on photos.
- ``alert_photo``: the annotated JPEG sent with an incident's ``start``: zones, boxes, the waiting
  times and a banner.
- ``preview``: the same drawing for the local status page.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from .analysis import FrameResult, Person
from .draw import blend_region, hexc, pill, polyline, rounded_rect, text, translucent_poly
from .zones import ZoneSet

ZONE_COLORS = {
    "queue": hexc("#F59E0B"),
    "staff": hexc("#14B8A6"),
    "line": hexc("#3B82F6"),
    "floor": hexc("#8B5CF6"),
}
CUSTOMER = hexc("#F59E0B")
CUSTOMER_IDLE = hexc("#94A3B8")
STAFF = hexc("#14B8A6")
INK = hexc("#0F172A")

WORDS = {
    "uz": {"staff": "Farmatsevt", "queue": "Navbat", "longest": "eng uzog‘i",
           "at_counter": "Kassada", "nobody": "Kassada hech kim yo‘q", "waiting": "kutmoqda",
           "people": "kishi"},
    "ru": {"staff": "Фармацевт", "queue": "Очередь", "longest": "дольше всех",
           "at_counter": "На кассе", "nobody": "На кассе никого", "waiting": "ждут",
           "people": "чел."},
    "en": {"staff": "Pharmacist", "queue": "Queue", "longest": "longest wait",
           "at_counter": "At the counter", "nobody": "Nobody at the counter", "waiting": "waiting",
           "people": "people"},
}


def mmss(seconds: float | int) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _px(points, w: int, h: int) -> list[tuple[float, float]]:
    return [(x * w, y * h) for x, y in points]


def apply_masks(image: np.ndarray, zones: ZoneSet) -> np.ndarray:
    """A copy with every mask zone filled black (the original is untouched)."""
    if not zones.masks:
        return image
    out = image.copy()
    h, w = out.shape[:2]
    for zone in zones.masks:
        pts = np.array([[round(x), round(y)] for x, y in _px(zone.points, w, h)], np.int32)
        cv2.fillPoly(out, [pts], (0, 0, 0))
    return out


def blur_heads(image: np.ndarray, people: list[Person]) -> None:
    """Blur the head of every person in place (the top 24 % of the box, 80 % of its width)."""
    h, w = image.shape[:2]
    for p in people:
        x1, y1, x2, y2 = p.box[0] * w, p.box[1] * h, p.box[2] * w, p.box[3] * h
        bw, bh = x2 - x1, y2 - y1
        hx1, hx2 = int(max(0, x1 + bw * 0.1)), int(min(w, x2 - bw * 0.1))
        hy1, hy2 = int(max(0, y1 - bh * 0.02)), int(min(h, y1 + bh * 0.24))
        if hx2 - hx1 < 3 or hy2 - hy1 < 3:
            continue
        region = image[hy1:hy2, hx1:hx2]
        small = cv2.resize(region, (max(1, region.shape[1] // 8), max(1, region.shape[0] // 8)),
                           interpolation=cv2.INTER_AREA)
        blurred = cv2.resize(small, (region.shape[1], region.shape[0]),
                             interpolation=cv2.INTER_LINEAR)
        image[hy1:hy2, hx1:hx2] = cv2.GaussianBlur(blurred, (0, 0), 3)


def draw_zones(image: np.ndarray, zones: ZoneSet, *, labels: bool = True) -> None:
    h, w = image.shape[:2]
    for zone in zones.all:
        if zone.kind == "mask":
            continue
        color = ZONE_COLORS[zone.kind]
        pts = _px(zone.points, w, h)
        if zone.kind == "line":
            (ax, ay), (bx, by) = pts
            cv2.line(image, (round(ax), round(ay)), (round(bx), round(by)), (255, 255, 255), 6,
                     cv2.LINE_AA)
            cv2.line(image, (round(ax), round(ay)), (round(bx), round(by)), color, 3, cv2.LINE_AA)
            dx, dy = bx - ax, by - ay
            length = max(1.0, (dx * dx + dy * dy) ** 0.5)
            # the in side: "left" is the positive cross product in image coordinates
            nx, ny = (-dy / length, dx / length) if zone.inside == "left" else (dy / length,
                                                                                 -dx / length)
            mx, my = (ax + bx) / 2, (ay + by) / 2
            tip = (mx + nx * 34, my + ny * 34)
            cv2.arrowedLine(image, (round(mx), round(my)), (round(tip[0]), round(tip[1])),
                            (255, 255, 255), 6, cv2.LINE_AA, tipLength=0.4)
            cv2.arrowedLine(image, (round(mx), round(my)), (round(tip[0]), round(tip[1])), color,
                            3, cv2.LINE_AA, tipLength=0.4)
            if labels:
                pill(image, zone.id, (min(ax, bx) + 4, (ay + by) / 2 - 30), (255, 255, 255),
                     color, size=11, weight=700, alpha=0.9)
            continue
        alpha = 0.10 if zone.kind == "floor" else 0.16
        translucent_poly(image, pts, color, alpha)
        polyline(image, pts, color, 2)
        if labels and zone.kind != "floor":
            top = min(pts, key=lambda p: (p[1], p[0]))
            pill(image, zone.id, (top[0] + 6, top[1] + 6), (255, 255, 255), color, size=11,
                 weight=700, alpha=0.9)


def _box(image, x1, y1, x2, y2, color, thickness=2) -> None:
    r = max(4, min(12, int((x2 - x1) * 0.12)))
    rounded_rect(image, x1 - 1, y1 - 1, x2 + 1, y2 + 1, r + 1, (255, 255, 255), thickness + 2)
    rounded_rect(image, x1, y1, x2, y2, r, color, thickness)


def draw_people(image: np.ndarray, people: list[Person], lang: str = "uz", *,
                shift_s: float = 0.0) -> None:
    """Boxes in role colours with a label; ``shift_s`` moves each box along its velocity (so a
    preview drawn on a newer picture keeps up with walking people)."""
    words = WORDS.get(lang, WORDS["uz"])
    h, w = image.shape[:2]
    for p in sorted(people, key=lambda p: p.box[3]):
        dx, dy = p.vx * shift_s, p.vy * shift_s
        x1, y1 = (p.box[0] + dx) * w, (p.box[1] + dy) * h
        x2, y2 = (p.box[2] + dx) * w, (p.box[3] + dy) * h
        if p.in_staff:
            color, label = STAFF, words["staff"]
        elif p.in_queue:
            color, label = CUSTOMER, mmss(p.wait_s or 0)
        else:
            color, label = CUSTOMER_IDLE, None
        _box(image, x1, y1, x2, y2, color)
        if label:
            pill(image, label, (x1, max(2, y1 - 24)), (255, 255, 255), color, size=12, weight=700)


def _banner(image: np.ndarray, line: str, sub: str, color, t: float) -> None:
    w = image.shape[1]
    blend_region(image, 0, 0, w, 54,
                 lambda layer, ox, oy: rounded_rect(layer, 0, 0, w, 54, 0, INK), 0.72)
    rounded_rect(image, 14, 14, 40, 40, 13, color)
    text(image, line, (52, 26), (255, 255, 255), 17, 700)
    text(image, sub, (52, 45), hexc("#CBD5E1"), 13, 500)
    stamp = time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(t))
    text(image, stamp, (w - 14, 32), hexc("#E2E8F0"), 13, 600, align="right")


def alert_photo(image: np.ndarray, result: FrameResult, zones: ZoneSet, *, kind: str,
                privacy_blur: bool, lang: str = "uz") -> bytes:
    words = WORDS.get(lang, WORDS["uz"])
    out = apply_masks(image, zones).copy()
    if privacy_blur:
        blur_heads(out, result.people)
    draw_zones(out, zones, labels=False)
    draw_people(out, result.people, lang)
    if kind == "unattended":
        line = f"{words['nobody']} · {result.queue} {words['waiting']}"
        color = hexc("#EF4444")
    else:
        line = f"{words['queue']}: {result.queue} {words['people']} · {words['longest']} " \
               f"{mmss(result.wait_s)}"
        color = hexc("#F59E0B")
    sub = f"{words['at_counter']}: {result.staff}"
    _banner(out, line, sub, color, result.t)
    return encode_jpeg(out, max_bytes=1_500_000, max_width=1280, quality=86)


def preview(image: np.ndarray, result: FrameResult | None, zones: ZoneSet, *,
            privacy_blur: bool, lang: str = "uz", shift_s: float = 0.0) -> np.ndarray:
    out = apply_masks(image, zones).copy()
    if result is not None and privacy_blur:
        blur_heads(out, result.people)
    draw_zones(out, zones)
    if result is not None:
        draw_people(out, result.people, lang, shift_s=shift_s)
    return out


def encode_jpeg(image: np.ndarray, *, max_bytes: int, max_width: int, quality: int = 82) -> bytes:
    """JPEG no wider than ``max_width`` and no bigger than ``max_bytes`` (lowering the quality,
    then the size, until it fits)."""
    h, w = image.shape[:2]
    if w > max_width:
        image = cv2.resize(image, (max_width, round(h * max_width / w)), interpolation=cv2.INTER_AREA)
    q = quality
    while True:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, q])
        data = buf.tobytes() if ok else b""
        if len(data) <= max_bytes or (q <= 40 and image.shape[1] <= 320):
            return data
        if q > 40:
            q -= 10
        else:
            image = cv2.resize(image, (image.shape[1] * 3 // 4, image.shape[0] * 3 // 4),
                               interpolation=cv2.INTER_AREA)
