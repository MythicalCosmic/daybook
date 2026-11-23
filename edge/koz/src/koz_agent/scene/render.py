"""Drawing the two cameras' pictures of the world, and the exact box of every figure."""

from __future__ import annotations

import math
import random
import threading
import time

import cv2
import numpy as np

from ..draw import (
    blend_region,
    circle,
    ellipse,
    hexc,
    mix,
    pill,
    poly,
    polyline,
    rounded_rect,
    shade,
    text,
)
from ..frames import Detection
from ..geometry import Box
from .art import draw_person
from .world import (
    COUNTER_TOP,
    H,
    MAX_SLOTS,
    TILL_X,
    W,
    World,
    counter_scale,
    door_scale,
    slot_pos,
)

WALL = hexc("#EEF3F0")
PASTELS = (
    "#A8DCC8", "#A9CCEB", "#F6C6A8", "#C9B8E8", "#F3E2A0", "#F2A9A9", "#8FD0CB", "#BFD8B0",
    "#F7F7F2", "#FFD7B5", "#B8E0F0", "#E6C8DC", "#D4E8B8",
)
ACCENTS = ("#2E9C8A", "#3C7DC4", "#E07A5F", "#7A5CC4", "#D4A72C", "#D9534F", "#2FA36B")
GREEN = hexc("#2FA36B")

COUNTER_X1, COUNTER_X2 = -12, 972
LAYER_TOP, LAYER_BOTTOM = 196, 346


def _vignette(img: np.ndarray, strength: float = 0.10) -> np.ndarray:
    h, w = img.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((xs - w / 2) / (w / 2)) ** 2 + ((ys - h / 2) / (h / 2)) ** 2
    factor = 1.0 - strength * np.clip(d - 0.35, 0, None) / 1.65
    return np.clip(img.astype(np.float32) * factor[..., None], 0, 255).astype(np.uint8)


def _gradient(img, x1, y1, x2, y2, top, bottom) -> None:
    for y in range(y1, y2):
        t = (y - y1) / max(1, y2 - y1 - 1)
        img[y, x1:x2] = mix(top, bottom, t)


def _item(img, rng: random.Random, x: float, bottom: float, w: float, h: float) -> None:
    kind = rng.random()
    color = hexc(rng.choice(PASTELS))
    accent = hexc(rng.choice(ACCENTS))
    if kind < 0.72:
        rounded_rect(img, x, bottom - h, x + w, bottom, 1.5, color)
        rounded_rect(img, x, bottom - h, x + w, bottom - h + max(2, h * 0.12), 0, shade(color, 1.35))
        rounded_rect(img, x + w - max(2, w * 0.18), bottom - h, x + w, bottom, 0, shade(color, 0.9))
        if w >= 15 and rng.random() < 0.6:
            rounded_rect(img, x + 2, bottom - h * 0.58, x + w - max(3, w * 0.22), bottom - h * 0.3,
                         1, (252, 252, 250))
            if rng.random() < 0.5:
                cx, cyy, a = x + w * 0.38, bottom - h * 0.44, max(1.5, h * 0.06)
                rounded_rect(img, cx - a, cyy - a / 2.4, cx + a, cyy + a / 2.4, 0, accent)
                rounded_rect(img, cx - a / 2.4, cyy - a, cx + a / 2.4, cyy + a, 0, accent)
        rounded_rect(img, x, bottom - 3, x + w - max(2, w * 0.18), bottom, 0, accent)
    elif kind < 0.9:
        body = hexc(rng.choice(("#C98B4B", "#F4F4F0", "#E9EEF2", "#B5653A")))
        cap = accent if rng.random() < 0.6 else (245, 245, 245)
        rounded_rect(img, x, bottom - h * 0.78, x + w, bottom, w * 0.3, body)
        rounded_rect(img, x + w * 0.28, bottom - h * 0.9, x + w * 0.72, bottom - h * 0.76, 0,
                     shade(body, 0.92))
        rounded_rect(img, x + w * 0.22, bottom - h, x + w * 0.78, bottom - h * 0.88, 1.5, cap)
        rounded_rect(img, x + 1, bottom - h * 0.55, x + w - 1, bottom - h * 0.28, 0, (250, 250, 250))
        rounded_rect(img, x + w * 0.15, bottom - h * 0.72, x + w * 0.3, bottom - h * 0.12, 0,
                     shade(body, 1.25))
    else:
        rounded_rect(img, x, bottom - h * 0.6, x + w, bottom, 3, color)
        rounded_rect(img, x - 1, bottom - h * 0.72, x + w + 1, bottom - h * 0.56, 2, accent)
        rounded_rect(img, x + 2, bottom - h * 0.42, x + w - 2, bottom - h * 0.2, 0, (250, 250, 250))


def _shelves(img, rng, x1, x2, y_top, y_bottom, rows, bays) -> None:
    rounded_rect(img, x1, y_top, x2, y_bottom, 0, hexc("#E1E9E5"))
    board = (252, 252, 252)
    under = hexc("#C9D4CF")
    bay_w = (x2 - x1) / bays
    row_h = (y_bottom - y_top) / rows
    for row in range(rows):
        top = y_top + row * row_h + 7
        bottom = y_top + (row + 1) * row_h
        for bay in range(bays):
            bx1 = x1 + bay * bay_w + 7
            bx2 = x1 + (bay + 1) * bay_w - 6
            x = bx1
            while x < bx2 - 10:
                w = rng.uniform(13, 28)
                if x + w > bx2:
                    w = bx2 - x
                    if w < 10:
                        break
                h = rng.uniform(0.55, 0.92) * (bottom - top - 3)
                _item(img, rng, x, bottom, w, h)
                x += w + rng.uniform(1.5, 3.5)
        rounded_rect(img, x1 - 3, bottom, x2 + 3, bottom + 5, 0, board)
        rounded_rect(img, x1 - 3, bottom + 5, x2 + 3, bottom + 7, 0, under)
    rounded_rect(img, x1 - 5, y_top - 6, x2 + 5, y_top + 2, 1, board)
    rounded_rect(img, x1 - 5, y_top + 2, x2 + 5, y_top + 4, 0, under)
    for bay in range(bays + 1):
        x = x1 + bay * bay_w
        rounded_rect(img, x - 3, y_top, x + 3, y_bottom + 5, 0, board)
        rounded_rect(img, x + 3, y_top + 4, x + 4, y_bottom + 5, 0, under)


def _sign(img, cx: float, y: float, label: str = "DORIXONA", dark: bool = False) -> None:
    from ..draw import text_size

    tw, _ = text_size(label, 17, 700)
    w = tw + 56
    x1, x2 = cx - w / 2, cx + w / 2
    if dark:
        rounded_rect(img, x1, y, x2, y + 28, 8, GREEN)
        fg, cross = (255, 255, 255), (255, 255, 255)
    else:
        rounded_rect(img, x1 + 2, y + 3, x2 + 2, y + 31, 9, hexc("#D3DCD8"))
        rounded_rect(img, x1, y, x2, y + 28, 9, (255, 255, 255))
        fg, cross = hexc("#1F7A4F"), GREEN
    ccx, ccy, a = x1 + 20, y + 14, 8
    rounded_rect(img, ccx - a, ccy - a / 2.6, ccx + a, ccy + a / 2.6, 1, cross)
    rounded_rect(img, ccx - a / 2.6, ccy - a, ccx + a / 2.6, ccy + a, 1, cross)
    text(img, label, (x1 + 36, y + 21), fg, 17, 700)


def _floor_grid(img, y_top, y_bottom, base, line, vp=(480, -700)) -> None:
    img[y_top:y_bottom, :] = base
    k = 0
    while True:
        y = y_top + 16 * k + 1.5 * k * k
        if y >= y_bottom:
            break
        cv2.line(img, (0, round(y)), (W, round(y)), line, 1, cv2.LINE_AA)
        k += 1
    for i in range(-8, 17):
        xb = -480 + 120 * i
        # the point where the line from (xb, H) to the vanishing point meets y_top
        t = (H - y_top) / (H - vp[1])
        xt = xb + (vp[0] - xb) * t
        cv2.line(img, (round(xt), y_top), (round(xb), y_bottom), line, 1, cv2.LINE_AA)


def _footprints(img, x: float, y: float, s: float, color) -> None:
    for side in (-1, 1):
        ellipse(img, (x + side * 7 * s, y - 2 * s), (4.2 * s, 7.5 * s), color, angle=side * 8)


# --- the counter camera --------------------------------------------------------------------


def _counter_background() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = random.Random(7)
    img = np.empty((H, W, 3), np.uint8)
    _gradient(img, 0, 0, W, 208, hexc("#E3EBE7"), hexc("#F2F6F3"))
    _sign(img, 380, 7)
    _shelves(img, rng, 24, 730, 46, 200, 3, 5)
    # the door to the back room, with its little window and handle
    rounded_rect(img, 748, 50, 832, 208, 3, hexc("#C7D1CC"))
    rounded_rect(img, 754, 56, 826, 208, 2, hexc("#DFE7E3"))
    rounded_rect(img, 772, 70, 808, 104, 6, hexc("#BFD5DF"))
    poly(img, [(776, 100), (790, 74), (796, 74), (782, 100)], hexc("#D5E6EE"))
    rounded_rect(img, 812, 132, 818, 154, 2, hexc("#8C9AA3"))
    rounded_rect(img, 760, 30, 820, 46, 4, hexc("#D7E9E2"))
    text(img, "XODIMLAR", (790, 42), hexc("#41806C"), 10, 600, align="center")
    # a poster: be healthy
    rounded_rect(img, 851, 128, 925, 196, 8, hexc("#E4F3EC"))
    circle(img, (888, 150), 11, hexc("#7CC6A0"))
    poly(img, [(882, 156), (888, 140), (894, 156)], hexc("#E4F3EC"))
    text(img, "Sog‘lom", (888, 176), hexc("#2F7A57"), 11, 700, align="center")
    text(img, "bo‘ling!", (888, 189), hexc("#2F7A57"), 11, 700, align="center")
    # staff floor behind the counter
    img[200:246, :] = hexc("#D6DFE4")
    for x in range(-40, W, 64):
        cv2.line(img, (x, 200), (x + 10, 246), hexc("#CCD6DC"), 1, cv2.LINE_AA)
    # the customers' floor, with footprint stickers where people wait
    _floor_grid(img, 338, H, hexc("#F3ECE2"), hexc("#E7DDCF"))
    sticker = hexc("#A7D9CC")
    for till in (0, 1):
        for i in range(1, MAX_SLOTS):
            x, y = slot_pos(till, i)
            _footprints(img, x, y - 4, counter_scale(y), sticker)
    img = _vignette(img, 0.09)

    layer = np.zeros_like(img)
    mask = np.zeros((H, W), np.uint8)

    def both(fn, *args, **kwargs):
        """Draw on the counter layer and mark the same pixels in its mask."""
        fn(layer, *args, **kwargs)
        marks = np.zeros((H, W, 3), np.uint8)
        fn(marks, *args, **kwargs)
        mask[marks.any(axis=2)] = 255

    # counter top, front panel and kick plate
    top = [(COUNTER_X1, COUNTER_TOP), (COUNTER_X2, COUNTER_TOP), (COUNTER_X2, 266),
           (COUNTER_X1, 266)]
    both(poly, top, hexc("#EFE3D3"))
    both(rounded_rect, COUNTER_X1, 262, COUNTER_X2, 268, 0, hexc("#FAF4EC"))
    both(rounded_rect, COUNTER_X1, 268, COUNTER_X2, 338, 0, hexc("#82C9B9"))
    for x in range(COUNTER_X1 + 18, COUNTER_X2, 26):
        cv2.line(layer, (x, 274), (x, 334), hexc("#76BDAD"), 2, cv2.LINE_AA)
    both(rounded_rect, COUNTER_X1, 268, COUNTER_X2, 273, 0, hexc("#70B4A5"))
    both(rounded_rect, COUNTER_X1, 338, COUNTER_X2, 346, 0, hexc("#4D6B64"))
    # the cross logo in the middle and the till numbers
    rounded_rect(layer, 448, 284, 512, 324, 12, (255, 255, 255))
    rounded_rect(layer, 470, 298, 490, 310, 1, GREEN)
    rounded_rect(layer, 474, 294, 486, 314, 1, GREEN)
    for i, x in enumerate(TILL_X):
        rounded_rect(layer, x - 34, 294, x + 34, 314, 10, (255, 255, 255))
        text(layer, f"KASSA {i + 1}", (x, 309), hexc("#2B8A78"), 12, 700, align="center")
    # what stands on the counter
    for i, x in enumerate(TILL_X):
        mx = x + 58 if i == 0 else x - 58
        both(rounded_rect, mx - 25, 206, mx + 25, 238, 4, hexc("#56606B"))
        both(rounded_rect, mx - 5, 236, mx + 5, 246, 0, hexc("#6B7580"))
        both(rounded_rect, mx - 15, 244, mx + 15, 250, 2, hexc("#6B7580"))
        circle(layer, (mx, 222), 3, hexc("#7C8792"))
        tx = x - 56 if i == 0 else x + 56
        both(rounded_rect, tx - 11, 226, tx + 11, 254, 4, hexc("#3B4249"))
        rounded_rect(layer, tx - 7, 230, tx + 7, 240, 2, hexc("#9FD8F5"))
        for k in range(3):
            rounded_rect(layer, tx - 7 + k * 5, 244, tx - 4 + k * 5, 247, 0, hexc("#A8B0B8"))
    # a little stand of vitamins between the tills, sanitizer and a plant
    both(rounded_rect, 452, 214, 508, 250, 3, hexc("#FFFFFF"))
    stand_rng = random.Random(11)
    for row, y in enumerate((232, 248)):
        x = 457
        while x < 500:
            w = stand_rng.uniform(8, 13)
            color = hexc(stand_rng.choice(PASTELS[:8]))
            rounded_rect(layer, x, y - 14, x + w, y, 1, color)
            rounded_rect(layer, x, y - 14, x + w, y - 12, 0, shade(color, 1.3))
            x += w + 2
        rounded_rect(layer, 452, y, 508, y + 2, 0, hexc("#DDE3E6"))
    both(rounded_rect, 858, 222, 872, 252, 4, hexc("#E9F1F7"))
    both(rounded_rect, 861, 214, 869, 223, 1, hexc("#3C7DC4"))
    both(rounded_rect, 896, 232, 930, 254, 6, hexc("#C9785D"))
    for angle, dx in ((-35, -8), (0, 0), (35, 8), (-60, -12), (60, 12)):
        both(ellipse, (913 + dx, 220), (6, 15), hexc("#5E9E6E" if dx % 16 else "#78B485"), angle)
    return img, layer, mask


# --- the door camera -----------------------------------------------------------------------

DOOR_X1, DOOR_X2, DOOR_Y1, DOOR_Y2 = 336, 624, 52, 238
PANEL_W = 104


def _door_background() -> np.ndarray:
    rng = random.Random(9)
    img = np.empty((H, W, 3), np.uint8)
    _gradient(img, 0, 0, W, 240, hexc("#ECE8E1"), hexc("#F5F2ED"))
    # outside, through the glass: sky, a building across the street, pavement and a tree
    _gradient(img, DOOR_X1, DOOR_Y1, DOOR_X2, 170, hexc("#D7E8F4"), hexc("#EEF4F7"))
    rounded_rect(img, 352, 96, 470, 168, 0, hexc("#E9DCCB"))
    for wx in range(362, 462, 26):
        rounded_rect(img, wx, 108, wx + 14, 126, 1, hexc("#C9D8E2"))
        rounded_rect(img, wx, 136, wx + 14, 154, 1, hexc("#C9D8E2"))
    img[168:DOOR_Y2, DOOR_X1:DOOR_X2] = hexc("#D3D7DA")
    cv2.line(img, (DOOR_X1, 182), (DOOR_X2, 182), hexc("#C2C7CB"), 2, cv2.LINE_AA)
    rounded_rect(img, 556, 120, 562, 176, 0, hexc("#8C7B6A"))
    for dx, dy, rr in ((-18, -6, 20), (14, -10, 22), (0, -26, 22), (-4, 4, 18)):
        circle(img, (559 + dx, 112 + dy), rr, hexc("#9CC79A" if dx < 0 else "#88BB8A"))
    # the frame of the entrance, with fixed glass at the sides
    frame = hexc("#BCC5CB")
    rounded_rect(img, DOOR_X1 - 10, DOOR_Y1 - 18, DOOR_X2 + 10, DOOR_Y1, 2, frame)
    rounded_rect(img, DOOR_X1 - 10, DOOR_Y1 - 18, DOOR_X1, DOOR_Y2, 0, frame)
    rounded_rect(img, DOOR_X2, DOOR_Y1 - 18, DOOR_X2 + 10, DOOR_Y2, 0, frame)
    rounded_rect(img, DOOR_X1 - 10, DOOR_Y1 - 18, DOOR_X2 + 10, DOOR_Y1 - 15, 0, hexc("#D3DADF"))
    rounded_rect(img, DOOR_X1, DOOR_Y1 - 3, DOOR_X2, DOOR_Y1, 0, hexc("#A9B3BA"))
    _sign(img, 480, 3, dark=True)
    def tint(layer, _ox, _oy):
        layer[:] = hexc("#BFD9E8")

    for x1 in (DOOR_X1, DOOR_X2 - 40):
        blend_region(img, x1, DOOR_Y1, x1 + 40, DOOR_Y2, tint, 0.35)
        edge = x1 + 40 if x1 == DOOR_X1 else x1
        cv2.line(img, (edge, DOOR_Y1), (edge, DOOR_Y2), hexc("#9AA5AD"), 3, cv2.LINE_AA)
    # shelves on the front wall, each side of the door
    _shelves(img, rng, 24, 300, 64, 226, 3, 2)
    _shelves(img, rng, 660, 936, 64, 226, 3, 2)
    # the floor, the welcome mat and the shop's things
    _floor_grid(img, 238, H, hexc("#E5E9EB"), hexc("#D9DEE1"), vp=(480, -520))
    poly(img, [(372, 244), (588, 244), (612, 318), (348, 318)], hexc("#4C535B"))
    polyline(img, [(380, 250), (580, 250), (600, 312), (360, 312)], hexc("#666E77"), 2)
    text(img, "XUSH KELIBSIZ", (480, 290), hexc("#C9CED4"), 15, 700, align="center")
    # baskets by the door
    for i in range(3):
        y = 286 - i * 7
        rounded_rect(img, 650, y - 22, 702, y, 4, hexc("#D9534F" if i % 2 == 0 else "#C9473F"))
        rounded_rect(img, 656, y - 18, 696, y - 6, 2, shade(hexc("#D9534F"), 0.82))
    # a promotion stand with vitamins
    rounded_rect(img, 772, 330, 924, 352, 6, hexc("#2FA36B"))
    text(img, "VITAMINLAR", (848, 346), (255, 255, 255), 13, 700, align="center")
    rounded_rect(img, 776, 352, 920, 470, 4, hexc("#FFFFFF"))
    for row in range(3):
        bottom = 388 + row * 38
        x = 782
        while x < 905:
            w = rng.uniform(14, 22)
            h = rng.uniform(20, 30)
            _item(img, rng, x, bottom, min(w, 912 - x), h)
            x += w + 3
        rounded_rect(img, 776, bottom, 920, bottom + 4, 0, hexc("#DDE3E6"))
    rounded_rect(img, 776, 470, 920, 478, 0, hexc("#C9D2D6"))
    # a plant in the corner
    rounded_rect(img, 46, 470, 112, 540, 8, hexc("#C8775A"))
    rounded_rect(img, 40, 464, 118, 478, 5, hexc("#B5664B"))
    for angle, dx, dy in ((-40, -18, -26), (-10, -6, -40), (20, 8, -42), (45, 20, -28),
                          (-70, -26, -8), (70, 28, -10)):
        ellipse(img, (79 + dx, 452 + dy), (9, 28), hexc("#5E9E6E" if dx < 0 else "#78B485"), angle)
    return _vignette(img, 0.09)


def _door_panels(img: np.ndarray, opened: float) -> None:
    shift = (PANEL_W - 12) * opened
    centre = (DOOR_X1 + DOOR_X2) / 2
    for side in (-1, 1):
        if side < 0:
            x1, x2 = centre - PANEL_W - shift, centre - shift
        else:
            x1, x2 = centre + shift, centre + PANEL_W + shift
        x1, x2 = max(x1, DOOR_X1 + 2), min(x2, DOOR_X2 - 2)
        if x2 - x1 < 4:
            continue

        def glass(layer, ox, oy, x1=x1, x2=x2):
            layer[:] = hexc("#C6DEEB")
            poly(layer, [(x1 - ox + 18, 0), (x1 - ox + 34, 0), (x1 - ox + 4, DOOR_Y2 - oy),
                         (x1 - ox - 12, DOOR_Y2 - oy)], hexc("#F4FAFD"))

        blend_region(img, x1, DOOR_Y1, x2, DOOR_Y2, glass, 0.38)
        polyline(img, [(x1, DOOR_Y1), (x2, DOOR_Y1), (x2, DOOR_Y2), (x1, DOOR_Y2)],
                 hexc("#97A3AB"), 3)
        hx = x2 - 12 if side < 0 else x1 + 12
        rounded_rect(img, hx - 2, 120, hx + 2, 176, 2, hexc("#7E8A93"))


# --- composition ---------------------------------------------------------------------------


def _osd(img: np.ndarray, label: str, t_wall: float) -> None:
    stamp = time.strftime("%d.%m.%Y  %H:%M:%S", time.localtime(t_wall))
    value = f"{label}   {stamp}"
    pill(img, value, (12, 10), (255, 255, 255), (30, 34, 38), size=13, weight=600, alpha=0.55)


def _clock(img: np.ndarray, t_wall: float) -> None:
    lt = time.localtime(t_wall)
    cx, cy, r = 888, 92, 25
    circle(img, (cx + 1, cy + 2), r + 3, hexc("#D5DDD9"))
    circle(img, (cx, cy), r + 3, hexc("#B9C3C8"))
    circle(img, (cx, cy), r, (255, 255, 255))
    for i in range(12):
        a = i / 12 * 2 * math.pi
        inner = r - (5 if i % 3 == 0 else 3)
        cv2.line(img, (round(cx + math.sin(a) * inner), round(cy - math.cos(a) * inner)),
                 (round(cx + math.sin(a) * (r - 1)), round(cy - math.cos(a) * (r - 1))),
                 hexc("#8E9AA2"), 1, cv2.LINE_AA)
    minutes = lt.tm_min + lt.tm_sec / 60
    hours = (lt.tm_hour % 12) + minutes / 60
    for value, length, width in ((hours / 12, r * 0.55, 3), (minutes / 60, r * 0.8, 2)):
        a = value * 2 * math.pi
        cv2.line(img, (cx, cy), (round(cx + math.sin(a) * length), round(cy - math.cos(a) * length)),
                 hexc("#3C464E"), width, cv2.LINE_AA)
    circle(img, (cx, cy), 2.5, hexc("#E07A5F"))


def _visible(box: Box, *, occlude_from: float | None = None) -> Box | None:
    x1, y1, x2, y2 = box
    full_w, full_h = x2 - x1, y2 - y1
    if occlude_from is not None and y2 > occlude_from:
        y2 = occlude_from
    cx1, cy1, cx2, cy2 = max(0.0, x1), max(0.0, y1), min(float(W), x2), min(float(H), y2)
    if cx2 - cx1 < max(8.0, 0.35 * full_w) or cy2 - cy1 < max(8.0, 0.25 * full_h):
        return None
    return (cx1, cy1, cx2, cy2)


class Renderer:
    """Draws frames of a ``World``. Backgrounds are built once per process."""

    _lock = threading.Lock()
    _cache: dict[str, tuple] = {}

    def _assets(self, view: str):
        with self._lock:
            if view not in self._cache:
                if view == "counter":
                    self._cache[view] = _counter_background()
                else:
                    self._cache[view] = (_door_background(),)
            return self._cache[view]

    def render(self, world: World, view: str, t_wall: float, label: str):
        if view == "counter":
            return self._counter(world, t_wall, label)
        if view == "door":
            return self._door(world, t_wall, label)
        raise ValueError(f"unknown view {view!r}")

    def _counter(self, world: World, t_wall: float, label: str):
        bg, layer, mask = self._assets("counter")
        img = bg.copy()
        _clock(img, t_wall)
        truth: list[Detection] = []
        actors = world.in_view("counter")
        for actor in actors:
            if actor.kind != "staff":
                continue
            box = draw_person(img, actor, counter_scale(actor.y))
            behind = actor.y > COUNTER_TOP and COUNTER_X1 <= actor.x <= COUNTER_X2
            visible = _visible(box, occlude_from=COUNTER_TOP + 2 if behind else None)
            if visible:
                truth.append(Detection(visible, 1.0))
        rows = slice(LAYER_TOP, LAYER_BOTTOM)
        region = img[rows]
        np.copyto(region, layer[rows], where=mask[rows, :, None].astype(bool))
        for actor in actors:
            if actor.kind == "staff":
                continue
            box = draw_person(img, actor, counter_scale(actor.y))
            visible = _visible(box)
            if visible:
                truth.append(Detection(visible, 1.0))
        _osd(img, label, t_wall)
        return img, truth

    def _door(self, world: World, t_wall: float, label: str):
        (bg,) = self._assets("door")
        img = bg.copy()
        _door_panels(img, world.door_open)
        truth: list[Detection] = []
        for actor in world.in_view("door"):
            box = draw_person(img, actor, door_scale(actor.y))
            visible = _visible(box)
            if visible:
                truth.append(Detection(visible, 1.0))
        _osd(img, label, t_wall)
        return img, truth
