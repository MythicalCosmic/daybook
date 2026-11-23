"""People in the flat illustration style: soft shapes, no outlines, a shadow on the floor."""

from __future__ import annotations

import math

import cv2
import numpy as np

from ..draw import capsule, circle, ellipse, hexc, poly, rounded_rect, shade, shadow_ellipse
from .world import BASE_HEIGHT, Actor

GREEN = hexc("#2FA36B")
TEAL = hexc("#2E9C8A")
COAT_SHADE = hexc("#DCE3EA")
BOX_COLORS = (
    "#7CC6B6",
    "#7FB2E0",
    "#F2A97E",
    "#B49BE0",
    "#E8C766",
    "#EE8E8E",
    "#6FC1BC",
    "#9DC98A",
)


def figure_height(actor: Actor, scale: float) -> float:
    return BASE_HEIGHT * scale * actor.look.height


def draw_person(img: np.ndarray, actor: Actor, scale: float) -> tuple[float, float, float, float]:
    """Draw ``actor`` standing at its foot point; return its full box (x1, y1, x2, y2)."""
    look = actor.look
    fx, fy = actor.x, actor.y
    H = figure_height(actor, scale)
    wide = look.width
    staff = actor.kind == "staff"
    toward = actor.facing == "toward"

    phase = actor.walked / max(1.0, 0.40 * H) * math.pi
    swing = math.sin(phase) if actor.moving else 0.0
    bob = -abs(math.sin(phase)) * 0.012 * H if actor.moving else 0.0

    r = 0.105 * H
    cy = fy - H + r + bob
    neck_y = cy + r * 0.92
    sh_y = neck_y + 0.03 * H
    sh = 0.185 * H * wide
    hem_y = fy - 0.27 * H + bob
    hem = 0.165 * H * wide
    foot_y = fy - 0.012 * H
    coat = hexc(look.coat)
    coat_dark = COAT_SHADE if staff else shade(coat, 0.84)
    skin = hexc(look.skin)
    hair = hexc(look.hair)
    trousers = hexc(look.trousers)
    shoes = hexc(look.shoes)

    # shadow and legs
    shadow_ellipse(img, (fx, fy), (0.21 * H * wide, 0.05 * H), 0.20)
    for side in (-1, 1):
        lx = fx + side * 0.055 * H
        step = swing * side
        top = (lx, hem_y - 0.05 * H)
        bottom = (lx + 0.008 * H * step, foot_y - 0.035 * H * step)
        capsule(img, top, bottom, 0.078 * H, trousers)
        ellipse(img, (bottom[0], bottom[1] + 0.012 * H), (0.045 * H, 0.024 * H), shoes)

    # coat
    body = [
        (fx - sh, sh_y + 0.035 * H),
        (fx + sh, sh_y + 0.035 * H),
        (fx + hem, hem_y),
        (fx - hem, hem_y),
    ]
    poly(img, body, coat)
    ellipse(img, (fx, sh_y + 0.04 * H), (sh, 0.055 * H), coat, start=180, end=360)
    shade_band = [
        (fx + sh * 0.55, sh_y + 0.03 * H),
        (fx + sh, sh_y + 0.035 * H),
        (fx + hem, hem_y),
        (fx + hem * 0.55, hem_y),
    ]
    poly(img, shade_band, coat_dark if not staff else shade(COAT_SHADE, 1.04))
    if staff:
        if toward:
            poly(
                img,
                [
                    (fx - 0.055 * H, sh_y - 0.004 * H),
                    (fx + 0.055 * H, sh_y - 0.004 * H),
                    (fx, sh_y + 0.12 * H),
                ],
                TEAL,
            )
            for side in (-1, 1):
                poly(
                    img,
                    [
                        (fx + side * 0.055 * H, sh_y),
                        (fx + side * 0.012 * H, sh_y + 0.13 * H),
                        (fx + side * 0.09 * H, sh_y + 0.07 * H),
                    ],
                    COAT_SHADE,
                )
            rounded_rect(
                img,
                fx + 0.07 * H,
                sh_y + 0.085 * H,
                fx + 0.135 * H,
                sh_y + 0.112 * H,
                0.006 * H,
                TEAL,
            )
            rounded_rect(
                img,
                fx - 0.135 * H,
                sh_y + 0.19 * H,
                fx - 0.07 * H,
                sh_y + 0.20 * H,
                0.004 * H,
                hexc("#C3CCD5"),
            )
        else:
            capsule(img, (fx, sh_y + 0.06 * H), (fx, hem_y - 0.03 * H), 0.008 * H, COAT_SHADE)
    else:
        ellipse(img, (fx, sh_y + 0.004 * H), (0.075 * H, 0.03 * H), shade(coat, 0.72))
        if toward:
            capsule(img, (fx, sh_y + 0.05 * H), (fx, hem_y - 0.02 * H), 0.012 * H, shade(coat, 0.8))

    # arms
    hands = []
    for side in (-1, 1):
        shoulder = (fx + side * (sh - 0.035 * H), sh_y + 0.045 * H)
        if actor.carrying == "box":
            hand = (fx + side * 0.06 * H, sh_y + 0.17 * H)
        else:
            hand = (fx + side * (sh + 0.006 * H), hem_y - 0.03 * H - 0.025 * H * swing * side)
        capsule(img, shoulder, hand, 0.072 * H, shade(coat, 0.92) if not staff else COAT_SHADE)
        hands.append(hand)
    if actor.carrying == "box":
        color = hexc(BOX_COLORS[actor.box_color % len(BOX_COLORS)])
        bx1, by1 = fx - 0.075 * H, sh_y + 0.10 * H
        bx2, by2 = fx + 0.075 * H, sh_y + 0.19 * H
        rounded_rect(img, bx1, by1, bx2, by2, 0.006 * H, color)
        rounded_rect(img, bx1, by1 + 0.03 * H, bx2, by1 + 0.055 * H, 0, (250, 250, 250))
    for hand in hands:
        circle(img, hand, 0.032 * H, skin)
    bag_box = None
    if actor.carrying == "bag":
        hx, hy = hands[1]
        x1, y1, x2, y2 = hx - 0.035 * H, hy + 0.01 * H, hx + 0.075 * H, hy + 0.13 * H
        rounded_rect(img, x1, y1, x2, y2, 0.008 * H, hexc("#FBFBF8"))
        rounded_rect(img, x1, y1, x1 + 0.02 * H, y2, 0, hexc("#E7E7E1"))
        cx, cyb, arm = (x1 + x2) / 2 + 0.005 * H, (y1 + y2) / 2 + 0.01 * H, 0.018 * H
        rounded_rect(img, cx - arm, cyb - arm / 3, cx + arm, cyb + arm / 3, 0, GREEN)
        rounded_rect(img, cx - arm / 3, cyb - arm, cx + arm / 3, cyb + arm, 0, GREEN)
        bag_box = (x1, y1, x2, y2)

    # head
    top = _head(img, actor, fx, cy, r, skin, hair, toward)

    half = max(sh + 0.05 * H, 0.21 * H * wide)
    x1, x2 = fx - half, fx + half
    if bag_box is not None:
        x2 = max(x2, bag_box[2])
    return (x1, top, x2, fy)


def _head(img, actor: Actor, fx, cy, r, skin, hair, toward: bool) -> float:
    look = actor.look
    hat = look.hat
    hat_color = hexc(look.hat_color)
    top = cy - r
    capsule(img, (fx, cy + r * 0.5), (fx, cy + r * 1.05), r * 0.62, shade(skin, 0.9))
    if hat == "scarf":
        drape = [
            (fx - r * 1.05, cy + r * 0.1),
            (fx + r * 1.05, cy + r * 0.1),
            (fx + r * 1.55, cy + r * 2.15),
            (fx - r * 1.55, cy + r * 2.15),
        ]
        poly(img, drape, shade(hat_color, 0.92))
        circle(img, (fx, cy), r * 1.12, hat_color)
        if toward:
            ellipse(img, (fx, cy + r * 0.12), (r * 0.62, r * 0.76), skin)
        else:
            ellipse(
                img,
                (fx - r * 0.35, cy - r * 0.45),
                (r * 0.32, r * 0.16),
                shade(hat_color, 1.18),
                angle=-30,
            )
        return cy - r * 1.12

    for side in (-1, 1):
        circle(img, (fx + side * r * 0.96, cy + r * 0.1), r * 0.22, shade(skin, 0.95))
    if toward:
        circle(img, (fx, cy), r, skin)
        ellipse(img, (fx, cy - r * 0.05), (r * 1.04, r * 1.0), hair, start=180, end=360)
        poly(
            img,
            [
                (fx - r * 1.02, cy - r * 0.1),
                (fx - r * 0.2, cy - r * 0.35),
                (fx - r * 0.95, cy + r * 0.35),
            ],
            hair,
        )
        poly(
            img,
            [
                (fx + r * 1.02, cy - r * 0.1),
                (fx + r * 0.4, cy - r * 0.42),
                (fx + r * 0.98, cy + r * 0.25),
            ],
            hair,
        )
    else:
        circle(img, (fx, cy - r * 0.02), r * 1.0, hair)
    if hat is None or hat == "bun":
        ellipse(
            img, (fx - r * 0.38, cy - r * 0.5), (r * 0.34, r * 0.17), shade(hair, 1.22), angle=-28
        )
    if hat == "bun":
        circle(img, (fx + r * 0.1, cy - r * 1.02), r * 0.42, hair)
        top = cy - r * 1.44
    elif hat == "doppi":
        cap = [
            (fx - r * 0.86, cy - r * 0.36),
            (fx + r * 0.86, cy - r * 0.36),
            (fx + r * 0.74, cy - r * 1.05),
            (fx - r * 0.74, cy - r * 1.05),
        ]
        poly(img, cap, hat_color)
        band = (226, 226, 222)
        cv2.line(
            img,
            (round(fx - r * 0.84), round(cy - r * 0.42)),
            (round(fx + r * 0.84), round(cy - r * 0.42)),
            band,
            max(1, round(r * 0.1)),
            cv2.LINE_AA,
        )
        for dx in (-0.42, 0.42):
            ellipse(
                img,
                (fx + r * dx, cy - r * 0.72),
                (r * 0.07, r * 0.16),
                band,
                angle=35 if dx < 0 else -35,
            )
        top = cy - r * 1.05
    elif hat == "knit":
        ellipse(img, (fx, cy - r * 0.12), (r * 1.08, r * 1.0), hat_color, start=180, end=360)
        rounded_rect(
            img,
            fx - r * 1.08,
            cy - r * 0.3,
            fx + r * 1.08,
            cy - r * 0.02,
            r * 0.12,
            shade(hat_color, 1.25),
        )
        circle(img, (fx, cy - r * 1.18), r * 0.28, shade(hat_color, 1.35))
        top = cy - r * 1.46
    return top
