"""The demo's pictures (docs/KOZ.md §9): flat illustrations of a pharmacy drawn with Pillow, never
photos and never real people. Four scenes, one per camera role: the counter (shelves of
medicines behind the pharmacists, the customers queueing in front, seen from behind), the
entrance, the sales floor and the storeroom. Figures are stylised shapes without faces.

    render(scene, people, size=…, annotate=False, …) -> Image
    snapshot(scene, seed) / alert_photo(…) / live_frame(…) -> JPEG bytes (and boxes)

Masks are blacked out on everything, as a box would do; an alert photo also carries what the box
draws on it: the zones, a box around each person and the queue's waiting times.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "core" / "pdf_assets" / "fonts"
SCALE = 2  # drawn at twice the size, then shrunk: smooth edges

WALL_TOP, WALL_BOTTOM = (241, 244, 247), (226, 232, 238)
SHELF, SHELF_EDGE = (206, 214, 223), (178, 189, 200)
BOXES = [
    (59, 169, 156),
    (242, 139, 102),
    (91, 141, 239),
    (232, 192, 125),
    (160, 140, 216),
    (244, 245, 248),
    (94, 186, 125),
    (236, 112, 140),
]
GREEN = (38, 166, 101)
COUNTER_TOP, COUNTER_EDGE = (248, 250, 252), (205, 214, 223)
COUNTER_FRONT, STRIPE = (45, 72, 92), (56, 178, 163)
FLOOR, FLOOR_LINE = (229, 233, 237), (215, 221, 227)
SKIN = [(241, 203, 170), (226, 176, 140), (200, 144, 106), (166, 114, 80)]
HAIR = [(44, 36, 33), (78, 55, 42), (118, 85, 58), (30, 30, 34), (96, 96, 104)]
COATS = [
    (88, 122, 230),
    (226, 118, 86),
    (70, 160, 130),
    (146, 96, 176),
    (58, 80, 102),
    (214, 170, 60),
    (182, 72, 96),
    (96, 130, 150),
]
SCARVES = [(196, 80, 110), (90, 120, 190), (210, 160, 70), (120, 160, 120)]
TROUSERS = [(52, 58, 72), (70, 78, 96), (40, 44, 52), (96, 84, 72)]
QUEUE_COLOR, STAFF_COLOR = (255, 152, 0), (0, 188, 170)

# The zones of each scene, as the demo's cameras keep them (docs/KOZ.md §4).
ZONES = {
    "counter": [
        {
            "id": "q1",
            "kind": "queue",
            "points": [[0.10, 0.63], [0.68, 0.63], [0.78, 0.98], [0.04, 0.98]],
        },
        {
            "id": "s1",
            "kind": "staff",
            "points": [[0.08, 0.28], [0.92, 0.28], [0.92, 0.53], [0.08, 0.53]],
        },
    ],
    "entrance": [
        {"id": "l1", "kind": "line", "points": [[0.24, 0.82], [0.76, 0.82]], "in": "right"},
        {
            "id": "f1",
            "kind": "floor",
            "points": [[0.05, 0.66], [0.95, 0.66], [1.0, 1.0], [0.0, 1.0]],
        },
    ],
    "floor": [
        {
            "id": "f1",
            "kind": "floor",
            "points": [[0.18, 0.62], [0.82, 0.62], [1.0, 1.0], [0.0, 1.0]],
        },
        {
            "id": "m1",
            "kind": "mask",
            "points": [[0.80, 0.06], [0.97, 0.06], [0.97, 0.34], [0.80, 0.34]],
        },
    ],
    "storeroom": [
        {
            "id": "f1",
            "kind": "floor",
            "points": [[0.20, 0.64], [0.80, 0.64], [0.92, 1.0], [0.08, 1.0]],
        },
    ],
}


@dataclass
class Person:
    """A figure on a scene: its foot point (normalized), customer or staff, how it looks."""

    x: float
    y: float
    role: str = "customer"
    look: int = 0
    wait_s: int | None = None
    zone: str | None = None
    track: int = 0


def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(
            str(FONTS / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")), size
        )
    except OSError:
        return ImageFont.load_default()


def _px(points, width: int, height: int) -> list[tuple[float, float]]:
    return [(x * width, y * height) for x, y in points]


# Backgrounds -------------------------------------------------------------------------------


def _wall(draw, width, height, bottom: float) -> None:
    rows = int(height * bottom)
    for row in range(rows):
        t = row / max(rows - 1, 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(WALL_TOP, WALL_BOTTOM, strict=True))
        draw.line([(0, row), (width, row)], fill=color)


def _floor(draw, width, height, top: float) -> None:
    y0 = int(height * top)
    draw.rectangle([0, y0, width, height], fill=FLOOR)
    for step in range(1, 7):
        y = y0 + (height - y0) * (step / 7) ** 1.3
        draw.line([(0, y), (width, y)], fill=FLOOR_LINE, width=SCALE)
    for step in range(-6, 7):
        x_far = width / 2 + step * width * 0.09
        x_near = width / 2 + step * width * 0.19
        draw.line([(x_far, y0), (x_near, height)], fill=FLOOR_LINE, width=SCALE)


def _shelf_unit(draw, rng, box, rows: int = 3, palette=BOXES, wide: bool = False) -> None:
    """Shelves full of medicine boxes inside `box` (pixels)."""
    left, top, right, bottom = box
    draw.rounded_rectangle(
        box, radius=6 * SCALE, fill=(232, 237, 242), outline=SHELF_EDGE, width=SCALE
    )
    step = (bottom - top) / rows
    for row in range(rows):
        board = top + step * (row + 1)
        x = left + 10 * SCALE
        while x < right - 18 * SCALE:
            width = rng.randint(44, 82) * SCALE if wide else rng.randint(14, 30) * SCALE
            height = int(step * rng.uniform(0.5, 0.8))
            if x + width > right - 8 * SCALE:
                break
            color = rng.choice(palette)
            draw.rounded_rectangle(
                [x, board - height - 3 * SCALE, x + width, board - 3 * SCALE],
                radius=3 * SCALE,
                fill=color,
            )
            if color == (244, 245, 248):  # a white box with a green cross
                cx, cy = x + width / 2, board - height / 2 - 3 * SCALE
                arm = max(width * 0.18, 3 * SCALE)
                draw.rectangle([cx - arm, cy - arm / 3, cx + arm, cy + arm / 3], fill=GREEN)
                draw.rectangle([cx - arm / 3, cy - arm, cx + arm / 3, cy + arm], fill=GREEN)
            else:
                draw.rectangle(
                    [
                        x + 3 * SCALE,
                        board - height * 0.6,
                        x + width - 3 * SCALE,
                        board - height * 0.6 + 3 * SCALE,
                    ],
                    fill=(255, 255, 255),
                )
            x += width + rng.randint(3, 8) * SCALE
        draw.rectangle([left, board - 3 * SCALE, right, board + 2 * SCALE], fill=SHELF_EDGE)


def _cross_sign(draw, cx, cy, size) -> None:
    draw.rounded_rectangle(
        [cx - size, cy - size, cx + size, cy + size],
        radius=size * 0.28,
        fill=(255, 255, 255),
        outline=(214, 222, 230),
        width=SCALE,
    )
    arm, thick = size * 0.62, size * 0.22
    draw.rounded_rectangle(
        [cx - arm, cy - thick, cx + arm, cy + thick], radius=thick * 0.4, fill=GREEN
    )
    draw.rounded_rectangle(
        [cx - thick, cy - arm, cx + thick, cy + arm], radius=thick * 0.4, fill=GREEN
    )


def _counter_scene(width, height, rng) -> Image.Image:
    image = Image.new("RGB", (width, height), FLOOR)
    draw = ImageDraw.Draw(image)
    _wall(draw, width, height, 0.62)
    _shelf_unit(draw, rng, [width * 0.04, height * 0.05, width * 0.64, height * 0.44], rows=3)
    _shelf_unit(draw, rng, [width * 0.70, height * 0.24, width * 0.96, height * 0.44], rows=1)
    _cross_sign(draw, width * 0.83, height * 0.12, height * 0.07)
    _floor(draw, width, height, 0.62)
    # The counter: its top, the front panel and a stripe.
    top, front, base = height * 0.505, height * 0.555, height * 0.70
    draw.rectangle([width * 0.03, front, width * 0.97, base], fill=COUNTER_FRONT)
    draw.rectangle([width * 0.03, height * 0.60, width * 0.97, height * 0.615], fill=STRIPE)
    draw.rounded_rectangle(
        [width * 0.02, top, width * 0.98, front],
        radius=4 * SCALE,
        fill=COUNTER_TOP,
        outline=COUNTER_EDGE,
        width=SCALE,
    )
    return image


def _counter_things(draw, width, height) -> None:
    """What stands on the counter, drawn over the pharmacists."""
    top = height * 0.505
    # The till's screen and the card terminal.
    draw.rounded_rectangle(
        [width * 0.27, top - height * 0.11, width * 0.37, top - height * 0.02],
        radius=4 * SCALE,
        fill=(38, 50, 56),
    )
    draw.rounded_rectangle(
        [width * 0.28, top - height * 0.10, width * 0.36, top - height * 0.035],
        radius=3 * SCALE,
        fill=(120, 190, 230),
    )
    draw.rectangle([width * 0.315, top - height * 0.02, width * 0.325, top], fill=(38, 50, 56))
    draw.rounded_rectangle(
        [width * 0.44, top - height * 0.05, width * 0.48, top], radius=4 * SCALE, fill=(52, 64, 72)
    )
    draw.rectangle(
        [width * 0.448, top - height * 0.044, width * 0.472, top - height * 0.027],
        fill=(160, 220, 200),
    )
    # A basket of small boxes.
    for index, color in enumerate(BOXES[:5]):
        x = width * (0.62 + index * 0.02)
        draw.rounded_rectangle(
            [x, top - height * 0.035, x + width * 0.017, top], radius=2 * SCALE, fill=color
        )


def _entrance_scene(width, height, rng) -> Image.Image:
    image = Image.new("RGB", (width, height), FLOOR)
    draw = ImageDraw.Draw(image)
    _wall(draw, width, height, 0.66)
    door = [width * 0.33, height * 0.12, width * 0.67, height * 0.66]
    draw.rounded_rectangle(door, radius=6 * SCALE, fill=(150, 166, 182))
    glass = [door[0] + 10 * SCALE, door[1] + 10 * SCALE, door[2] - 10 * SCALE, door[3]]
    draw.rectangle(glass, fill=(196, 222, 236))
    middle = (glass[0] + glass[2]) / 2
    draw.rectangle(
        [middle - 3 * SCALE, glass[1], middle + 3 * SCALE, glass[3]], fill=(150, 166, 182)
    )
    for offset in (0.1, 0.55):  # light on the glass
        x = glass[0] + (glass[2] - glass[0]) * offset
        draw.polygon(
            [
                (x, glass[3]),
                (x + 40 * SCALE, glass[1]),
                (x + 70 * SCALE, glass[1]),
                (x + 30 * SCALE, glass[3]),
            ],
            fill=(214, 234, 244),
        )
    _cross_sign(draw, width * 0.5, height * 0.06, height * 0.045)
    _shelf_unit(draw, rng, [width * 0.03, height * 0.20, width * 0.27, height * 0.64], rows=4)
    _shelf_unit(draw, rng, [width * 0.73, height * 0.20, width * 0.97, height * 0.64], rows=4)
    _floor(draw, width, height, 0.66)
    draw.rounded_rectangle(
        [width * 0.36, height * 0.70, width * 0.64, height * 0.80],
        radius=6 * SCALE,
        fill=(96, 110, 124),
    )
    return image


def _floor_scene(width, height, rng) -> Image.Image:
    image = Image.new("RGB", (width, height), FLOOR)
    draw = ImageDraw.Draw(image)
    _wall(draw, width, height, 0.62)
    draw.rectangle([width * 0.80, height * 0.06, width * 0.97, height * 0.34], fill=(200, 226, 240))
    _shelf_unit(draw, rng, [width * 0.03, height * 0.10, width * 0.30, height * 0.60], rows=4)
    _shelf_unit(draw, rng, [width * 0.34, height * 0.18, width * 0.66, height * 0.60], rows=3)
    _floor(draw, width, height, 0.62)
    # A low display table in the middle.
    draw.rounded_rectangle(
        [width * 0.40, height * 0.70, width * 0.60, height * 0.80],
        radius=6 * SCALE,
        fill=(250, 251, 252),
        outline=COUNTER_EDGE,
        width=SCALE,
    )
    for index in range(5):
        x = width * (0.415 + index * 0.034)
        draw.rounded_rectangle(
            [x, height * 0.665, x + width * 0.026, height * 0.70],
            radius=2 * SCALE,
            fill=BOXES[index + 1],
        )
    return image


def _storeroom_scene(width, height, rng) -> Image.Image:
    image = Image.new("RGB", (width, height), FLOOR)
    draw = ImageDraw.Draw(image)
    _wall(draw, width, height, 0.64)
    cardboard = [(196, 160, 116), (210, 178, 132), (182, 146, 104)]
    _shelf_unit(
        draw,
        rng,
        [width * 0.03, height * 0.06, width * 0.40, height * 0.62],
        rows=4,
        palette=cardboard,
        wide=True,
    )
    _shelf_unit(
        draw,
        rng,
        [width * 0.44, height * 0.06, width * 0.72, height * 0.62],
        rows=4,
        palette=cardboard,
        wide=True,
    )
    # The fridge for +2..+8 °C medicines.
    fridge = [width * 0.76, height * 0.08, width * 0.96, height * 0.64]
    draw.rounded_rectangle(
        fridge, radius=8 * SCALE, fill=(246, 248, 250), outline=(196, 206, 216), width=2 * SCALE
    )
    draw.rounded_rectangle(
        [
            fridge[0] + 14 * SCALE,
            fridge[1] + 16 * SCALE,
            fridge[2] - 14 * SCALE,
            fridge[3] - 60 * SCALE,
        ],
        radius=6 * SCALE,
        fill=(214, 236, 248),
    )
    draw.text(
        (fridge[0] + 22 * SCALE, fridge[3] - 48 * SCALE),
        "+2…+8 °C",
        fill=(60, 110, 150),
        font=_font(15 * SCALE, True),
    )
    _floor(draw, width, height, 0.64)
    return image


SCENES = {
    "counter": _counter_scene,
    "entrance": _entrance_scene,
    "floor": _floor_scene,
    "storeroom": _storeroom_scene,
}


@lru_cache(maxsize=16)
def background(scene: str, width: int, height: int, seed: int = 0) -> Image.Image:
    """The scene without people, at twice `width` by `height` (shrunk at the end)."""
    draw = SCENES.get(scene, _floor_scene)
    return draw(width * SCALE, height * SCALE, random.Random(f"{scene}:{seed}"))


# People ------------------------------------------------------------------------------------


def _height(person: Person, scene: str) -> float:
    """How tall a figure looks (share of the frame height): nearer is bigger."""
    if person.role == "staff" and scene == "counter":
        return 0.27
    near = max(min((person.y - 0.6) / 0.4, 1.0), 0.0)
    return 0.34 + 0.26 * near


def _darker(color, by: int = 22):
    return tuple(max(channel - by, 0) for channel in color)


def _head(draw, cx, cy, radius, look: int, *, facing: bool) -> None:
    """A head without a face: from the front skin under a cap of hair, from behind all hair;
    every third figure wears a headscarf."""
    skin, hair = SKIN[(look // 3) % len(SKIN)], HAIR[(look * 7) % len(HAIR)]
    if look % 3 == 1:
        scarf = SCARVES[look % len(SCARVES)]
        draw.ellipse(
            [cx - radius * 1.18, cy - radius * 1.2, cx + radius * 1.18, cy + radius * 1.25],
            fill=scarf,
        )
        if facing:
            draw.ellipse(
                [cx - radius * 0.72, cy - radius * 0.72, cx + radius * 0.72, cy + radius * 0.9],
                fill=skin,
            )
        return
    if facing:
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=skin)
        draw.chord(
            [cx - radius * 1.04, cy - radius * 1.1, cx + radius * 1.04, cy + radius * 0.5],
            180,
            360,
            fill=hair,
        )
    else:
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=hair)


def _staff(draw, person: Person, width, height) -> None:
    """A pharmacist behind the counter in a white coat, seen down to the counter top."""
    tall = _height(person, "counter") * height
    cx, base = person.x * width, person.y * height
    radius = tall * 0.15
    neck = base - tall + radius * 2
    shoulders = tall * 0.23
    draw.rounded_rectangle(
        [cx - shoulders, neck + tall * 0.02, cx + shoulders, base + 6 * SCALE],
        radius=shoulders * 0.45,
        fill=(251, 252, 253),
        outline=(214, 222, 230),
        width=SCALE,
    )
    draw.polygon(
        [
            (cx - shoulders * 0.38, neck + tall * 0.02),
            (cx + shoulders * 0.38, neck + tall * 0.02),
            (cx, neck + tall * 0.24),
        ],
        fill=STRIPE,
    )
    draw.rounded_rectangle(
        [cx + shoulders * 0.3, neck + tall * 0.3, cx + shoulders * 0.72, neck + tall * 0.36],
        radius=2 * SCALE,
        fill=(56, 178, 163),
    )
    draw.rectangle(
        [cx - radius * 0.35, neck - radius * 0.3, cx + radius * 0.35, neck + tall * 0.04],
        fill=SKIN[(person.look // 3) % len(SKIN)],
    )
    _head(draw, cx, base - tall + radius, radius, person.look, facing=True)


def _customer(draw, person: Person, width, height, scene: str) -> None:
    """A customer: from behind at the counter, facing the camera elsewhere."""
    look = person.look
    tall = _height(person, scene) * height
    cx, foot = person.x * width, person.y * height
    radius = tall * 0.105
    shoulders = tall * 0.17
    neck = foot - tall + radius * 2
    hip = neck + tall * 0.40
    coat, trousers = COATS[(look * 5 + 1) % len(COATS)], TROUSERS[(look // 2) % len(TROUSERS)]
    for side in (-1, 1):
        x = cx + side * shoulders * 0.36
        draw.rounded_rectangle(
            [x - shoulders * 0.23, hip - tall * 0.04, x + shoulders * 0.23, foot - tall * 0.015],
            radius=shoulders * 0.16,
            fill=trousers,
        )
        draw.rounded_rectangle(
            [x - shoulders * 0.3, foot - tall * 0.04, x + shoulders * 0.3, foot + tall * 0.005],
            radius=shoulders * 0.14,
            fill=(40, 40, 46),
        )
    for side in (-1, 1):
        x = cx + side * (shoulders * 0.98)
        draw.rounded_rectangle(
            [x - tall * 0.04, neck + tall * 0.05, x + tall * 0.04, neck + tall * 0.36],
            radius=tall * 0.04,
            fill=_darker(coat),
        )
    draw.rounded_rectangle(
        [cx - shoulders, neck + tall * 0.015, cx + shoulders, hip + tall * 0.05],
        radius=shoulders * 0.5,
        fill=coat,
    )
    if look % 5 == 2:  # a bag on the shoulder
        draw.line(
            [
                (cx - shoulders * 0.4, neck + tall * 0.03),
                (cx + shoulders * 0.95, neck + tall * 0.24),
            ],
            fill=(96, 66, 48),
            width=max(int(tall * 0.012), 2),
        )
        draw.rounded_rectangle(
            [cx + shoulders * 0.75, neck + tall * 0.2, cx + shoulders * 1.45, neck + tall * 0.33],
            radius=tall * 0.02,
            fill=(128, 90, 64),
        )
    facing = scene != "counter"
    if not facing:
        draw.rectangle(
            [cx - radius * 0.38, neck - radius * 0.4, cx + radius * 0.38, neck + tall * 0.03],
            fill=SKIN[(look // 3) % len(SKIN)],
        )
    _head(draw, cx, foot - tall + radius, radius, look, facing=facing)


def box_of(person: Person, scene: str) -> list[float]:
    """The figure's box `[x, y, w, h]`, normalized (as a box reports it, docs/KOZ.md §5.6)."""
    tall = _height(person, scene)
    if person.role == "staff" and scene == "counter":
        width = tall * 0.23 * 2.2 * 9 / 16
        top = person.y - tall
        return [round(person.x - width / 2, 4), round(top, 4), round(width, 4), round(tall, 4)]
    width = tall * 0.17 * 2.5 * 9 / 16
    top = person.y - tall
    return [round(person.x - width / 2, 4), round(top, 4), round(width, 4), round(tall, 4)]


# Drawing a frame ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _shadow(width: int, height: int) -> Image.Image:
    """A soft shadow under a figure's feet (small, so blurring it costs nothing)."""
    pad = 6 * SCALE
    sprite = Image.new("RGBA", (width + 2 * pad, height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(sprite).ellipse([pad, pad, pad + width, pad + height], fill=(30, 40, 50, 52))
    return sprite.filter(ImageFilter.GaussianBlur(3 * SCALE))


def _mask(draw, zones, width, height) -> None:
    for zone in zones or []:
        if zone.get("kind") == "mask":
            draw.polygon(_px(zone["points"], width, height), fill=(0, 0, 0))


def _annotate(image: Image.Image, scene: str, people, zones, width, height, title: str) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for zone in zones or []:
        kind = zone.get("kind")
        if kind not in ("queue", "staff"):
            continue
        color = QUEUE_COLOR if kind == "queue" else STAFF_COLOR
        points = _px(zone["points"], width, height)
        draw.polygon(points, fill=(*color, 38))
        draw.line([*points, points[0]], fill=(*color, 220), width=3 * SCALE, joint="curve")
    font = _font(15 * SCALE, True)
    for person in people:
        x, y, w, h = box_of(person, scene)
        color = STAFF_COLOR if person.role == "staff" else QUEUE_COLOR
        rect = [x * width, y * height, (x + w) * width, (y + h) * height]
        draw.rounded_rectangle(rect, radius=6 * SCALE, outline=(*color, 255), width=3 * SCALE)
        if person.wait_s:
            label = f"{person.wait_s // 60}:{person.wait_s % 60:02d}"
            bbox = draw.textbbox((0, 0), label, font=font)
            tag = [
                rect[0],
                rect[1] - (bbox[3] - bbox[1]) - 14 * SCALE,
                rect[0] + (bbox[2] - bbox[0]) + 16 * SCALE,
                rect[1] - 2 * SCALE,
            ]
            draw.rounded_rectangle(tag, radius=5 * SCALE, fill=(*color, 235))
            draw.text(
                (tag[0] + 8 * SCALE, tag[1] + 3 * SCALE),
                label,
                fill=(255, 255, 255, 255),
                font=font,
            )
    if title:
        small = _font(14 * SCALE, True)
        bbox = draw.textbbox((0, 0), title, font=small)
        draw.rounded_rectangle(
            [
                14 * SCALE,
                14 * SCALE,
                34 * SCALE + bbox[2] - bbox[0],
                26 * SCALE + bbox[3] - bbox[1],
            ],
            radius=6 * SCALE,
            fill=(20, 28, 36, 190),
        )
        draw.text((24 * SCALE, 16 * SCALE), title, fill=(255, 255, 255, 255), font=small)
    image.alpha_composite(layer)


def render(
    scene: str,
    people: list[Person],
    *,
    size: tuple[int, int] = (1280, 720),
    seed: int = 0,
    zones: list[dict] | None = None,
    annotate: bool = False,
    title: str = "",
) -> Image.Image:
    width, height = size
    big_w, big_h = width * SCALE, height * SCALE
    image = background(scene, width, height, seed).copy().convert("RGBA")
    draw = ImageDraw.Draw(image)
    order = sorted(people, key=lambda person: (person.role != "staff", person.y))
    for person in order:
        if person.role == "staff" and scene == "counter":
            _staff(draw, person, big_w, big_h)
    if scene == "counter":
        top = big_h * 0.505
        front = big_h * 0.555
        draw.rectangle([big_w * 0.03, front, big_w * 0.97, big_h * 0.70], fill=COUNTER_FRONT)
        draw.rectangle([big_w * 0.03, big_h * 0.60, big_w * 0.97, big_h * 0.615], fill=STRIPE)
        draw.rounded_rectangle(
            [big_w * 0.02, top, big_w * 0.98, front],
            radius=4 * SCALE,
            fill=COUNTER_TOP,
            outline=COUNTER_EDGE,
            width=SCALE,
        )
        _counter_things(draw, big_w, big_h)
    standing = [p for p in order if not (p.role == "staff" and scene == "counter")]
    for person in standing:
        tall = _height(person, scene) * big_h
        sprite = _shadow(int(tall * 0.44) // 8 * 8, max(int(tall * 0.055) // 4 * 4, 4))
        left = int(person.x * big_w - sprite.width / 2)
        top = int(person.y * big_h - sprite.height * 0.45)
        if left >= 0 and left + sprite.width <= big_w and top >= 0 and top + sprite.height <= big_h:
            image.alpha_composite(sprite, dest=(left, top))
    for person in standing:
        _customer(draw, person, big_w, big_h, scene)
    _mask(draw, zones if zones is not None else ZONES.get(scene), big_w, big_h)
    if annotate:
        _annotate(
            image,
            scene,
            people,
            zones if zones is not None else ZONES.get(scene),
            big_w,
            big_h,
            title,
        )
    return image.convert("RGB").reduce(SCALE)


def encode(image: Image.Image, quality: int = 82) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


# Who stands where --------------------------------------------------------------------------

# The first in the queue stands at the counter; the others behind, nearer the camera. The
# pharmacists stand to the right of the till, where the queue doesn't hide them.
QUEUE_SPOTS = [(0.34, 0.69), (0.25, 0.76), (0.40, 0.82), (0.17, 0.87), (0.31, 0.92), (0.47, 0.95)]
STAFF_SPOTS = [(0.60, 0.515), (0.77, 0.515), (0.46, 0.515)]


def counter_people(
    queue: int, staff: int, wait_s: int, *, seed: int = 0, drift: float = 0.0
) -> list[Person]:
    """`queue` customers at the counter (the first waited `wait_s`), `staff` behind it."""
    rng = random.Random(seed)
    people = []
    for index in range(min(staff, len(STAFF_SPOTS))):
        x, y = STAFF_SPOTS[index]
        people.append(
            Person(
                x + rng.uniform(-0.02, 0.02) + drift * 0.01,
                y,
                "staff",
                look=rng.randint(0, 11),
                zone="s1",
                track=100 + index,
            )
        )
    for index in range(min(queue, len(QUEUE_SPOTS))):
        x, y = QUEUE_SPOTS[index]
        waited = max(wait_s - index * 35, 5)
        people.append(
            Person(
                x + rng.uniform(-0.025, 0.025) + drift * 0.008 * (index % 2 * 2 - 1),
                y + rng.uniform(-0.01, 0.01),
                "customer",
                look=rng.randint(0, 23),
                wait_s=waited,
                zone="q1",
                track=10 + index,
            )
        )
    return people


def walking_people(count: int, scene: str, *, seed: int = 0, drift: float = 0.0) -> list[Person]:
    """`count` people spread over the floor (away from the masked window), walking a little
    as `drift` grows."""
    rng = random.Random(f"{scene}:{seed}")
    people = []
    lanes = sorted(range(count), key=lambda _lane: rng.random())
    for index in range(count):
        lane = (lanes[index] + 0.5) / max(count, 1)
        x = 0.12 + 0.62 * lane + rng.uniform(-0.04, 0.04) + drift * 0.02 * (1 if index % 2 else -1)
        y = rng.uniform(0.72, 0.97)
        role = "staff" if scene == "storeroom" else "customer"
        people.append(
            Person(
                min(max(x, 0.08), 0.92),
                y,
                role,
                look=rng.randint(0, 23),
                zone="f1",
                track=20 + index,
            )
        )
    return people


def people_for(role: str, report: dict, *, seed: int = 0, drift: float = 0.0) -> list[Person]:
    """The figures of a camera's live numbers (`demo_live.camera_report`)."""
    if role == "counter":
        return counter_people(
            report.get("queue") or 0,
            report.get("staff") or 0,
            report.get("wait_s") or 0,
            seed=seed,
            drift=drift,
        )
    scene = role if role in SCENES else "floor"
    return walking_people(report.get("people") or 0, scene, seed=seed, drift=drift)


def frame_people(people: list[Person], scene: str) -> list[dict]:
    """What a box's frame meta says about the figures (docs/KOZ.md §5.6)."""
    return [
        {
            "track": person.track,
            "box": box_of(person, scene),
            "role": person.role,
            "zone": person.zone,
            "wait_s": person.wait_s if person.zone == "q1" else None,
        }
        for person in people
    ]


# What the demo stores and shows -------------------------------------------------------------

SCENE_OF = {
    "counter": "counter",
    "entrance": "entrance",
    "floor": "floor",
    "storeroom": "storeroom",
}


def scene_of(role: str) -> str:
    return SCENE_OF.get(role, "floor")


def snapshot(role: str, *, seed: int = 0, zones=None) -> bytes:
    """A camera's setup picture: its scene with a few people, masked, not annotated."""
    scene = scene_of(role)
    if scene == "counter":
        people = counter_people(1, 1, 30, seed=seed)
    else:
        people = walking_people({"entrance": 2, "floor": 3}.get(scene, 1), scene, seed=seed)
    return encode(render(scene, people, seed=seed, zones=zones))


def alert_photo(
    *, queue: int, wait_s: int, staff: int, title: str, seed: int = 0, zones=None
) -> bytes:
    """What a box sends with an alert's start: the counter with its zones, a box around each
    person and the queue's waiting times."""
    people = counter_people(queue, staff, wait_s, seed=seed)
    image = render("counter", people, seed=seed, zones=zones, annotate=True, title=title)
    return encode(image, quality=80)
