"""Zones of a camera (contract §4): queue, staff, line, floor and mask, normalized to 0..1."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from .geometry import Point, point_in_polygon

log = logging.getLogger(__name__)

KINDS = ("queue", "staff", "line", "floor", "mask")
ZONE_ID = re.compile(r"^[a-z0-9_-]{1,16}$")
MAX_ZONES = 8


class ZoneError(ValueError):
    pass


@dataclass(frozen=True)
class Zone:
    id: str
    kind: str
    points: tuple[Point, ...]
    inside: str | None = None  # a line's ``in`` side: "left" or "right"

    def contains(self, p: Point) -> bool:
        return self.kind != "line" and point_in_polygon(p, self.points)

    def to_json(self) -> dict:
        data: dict = {
            "id": self.id,
            "kind": self.kind,
            "points": [[round(x, 4), round(y, 4)] for x, y in self.points],
        }
        if self.kind == "line":
            data["in"] = self.inside
        return data


def parse_zone(data: dict) -> Zone:
    if not isinstance(data, dict):
        raise ZoneError("a zone is an object")
    zone_id = data.get("id")
    kind = data.get("kind")
    if not isinstance(zone_id, str) or not ZONE_ID.match(zone_id):
        raise ZoneError(f"bad zone id {zone_id!r}")
    if kind not in KINDS:
        raise ZoneError(f"unknown zone kind {kind!r}")
    raw = data.get("points")
    if not isinstance(raw, list):
        raise ZoneError(f"zone {zone_id}: points must be a list")
    points: list[Point] = []
    for item in raw:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            raise ZoneError(f"zone {zone_id}: a point is [x, y]")
        x, y = item
        if isinstance(x, bool) or isinstance(y, bool):
            raise ZoneError(f"zone {zone_id}: coordinates are numbers")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ZoneError(f"zone {zone_id}: coordinates are numbers")
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ZoneError(f"zone {zone_id}: coordinates must be within 0..1")
        points.append((float(x), float(y)))
    inside = None
    if kind == "line":
        if len(points) != 2:
            raise ZoneError(f"zone {zone_id}: a line has exactly 2 points")
        inside = data.get("in")
        if inside not in ("left", "right"):
            raise ZoneError(f"zone {zone_id}: a line needs in = left or right")
    elif not 3 <= len(points) <= 24:
        raise ZoneError(f"zone {zone_id}: a polygon has 3 to 24 points")
    return Zone(zone_id, kind, tuple(points), inside)


def parse_zones(items: Iterable[dict] | None, *, strict: bool = False) -> list[Zone]:
    """Parse a camera's zone list. The backend validates on PATCH already; here a bad zone is
    skipped with a warning (or raises when ``strict``)."""
    zones: list[Zone] = []
    seen: set[str] = set()
    for item in items or []:
        try:
            zone = parse_zone(item)
            if zone.id in seen:
                raise ZoneError(f"duplicate zone id {zone.id}")
            if len(zones) >= MAX_ZONES:
                raise ZoneError("at most 8 zones")
        except ZoneError as exc:
            if strict:
                raise
            log.warning("ignoring a zone: %s", exc)
            continue
        seen.add(zone.id)
        zones.append(zone)
    return zones


class ZoneSet:
    """A camera's zones, grouped by kind, with the lookups the analysis needs."""

    def __init__(self, zones: Iterable[Zone] = ()) -> None:
        self.all: list[Zone] = list(zones)
        self.queues = [z for z in self.all if z.kind == "queue"]
        self.staffs = [z for z in self.all if z.kind == "staff"]
        self.lines = [z for z in self.all if z.kind == "line"]
        self.floors = [z for z in self.all if z.kind == "floor"]
        self.masks = [z for z in self.all if z.kind == "mask"]

    @classmethod
    def from_json(cls, items: Iterable[dict] | None) -> ZoneSet:
        return cls(parse_zones(items))

    def to_json(self) -> list[dict]:
        return [z.to_json() for z in self.all]

    def in_mask(self, p: Point) -> bool:
        return any(z.contains(p) for z in self.masks)

    def queue_zone(self, p: Point) -> str | None:
        return next((z.id for z in self.queues if z.contains(p)), None)

    def staff_zone(self, p: Point) -> str | None:
        return next((z.id for z in self.staffs if z.contains(p)), None)

    def zone_of(self, p: Point) -> str | None:
        """The zone a foot point is in: a queue first, then staff, then floor."""
        for group in (self.queues, self.staffs, self.floors):
            for zone in group:
                if zone.contains(p):
                    return zone.id
        return None

    @property
    def has_queue(self) -> bool:
        return bool(self.queues)

    @property
    def has_staff(self) -> bool:
        return bool(self.staffs)
