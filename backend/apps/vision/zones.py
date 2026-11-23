"""A camera's zones (docs/KOZ.md §4): where customers queue, where pharmacists stand, entrance
lines, counting areas and masks, as a JSON list on the camera with coordinates normalized to
0..1 of the frame (x to the right, y down).

    clean(raw) -> the zones as stored, or ZoneError with a message for the person who drew them
"""

import math
import re

from django.utils.translation import gettext as _

from apps.core.exceptions import DomainError

MAX_ZONES = 8
MIN_POINTS, MAX_POINTS = 3, 24
POLYGONS = ("queue", "staff", "floor", "mask")
KINDS = (*POLYGONS, "line")
SIDES = ("left", "right")
ZONE_ID = re.compile(r"^[a-z0-9_-]{1,16}$")


class ZoneError(DomainError):
    """The zones can't be saved; the message says why."""


def clean(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ZoneError(_("Zones must be a list."))
    if len(raw) > MAX_ZONES:
        raise ZoneError(_("A camera has at most %(count)d zones.") % {"count": MAX_ZONES})
    zones, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise ZoneError(_("Each zone needs an id, a kind and its points."))
        zone_id = item.get("id")
        if not isinstance(zone_id, str) or not ZONE_ID.match(zone_id):
            raise ZoneError(
                _("A zone's id is 1 to 16 small letters, digits, dashes or underscores.")
            )
        if zone_id in seen:
            raise ZoneError(
                _("Two zones are called %(id)s: give each its own id.") % {"id": zone_id}
            )
        seen.add(zone_id)
        kind = item.get("kind")
        if kind not in KINDS:
            raise ZoneError(_("Zone %(id)s has a kind we don't know.") % {"id": zone_id})
        points = _points(item.get("points"), zone_id)
        zone = {"id": zone_id, "kind": kind, "points": points}
        if kind == "line":
            if len(points) != 2:
                raise ZoneError(
                    _("The entrance line %(id)s needs exactly two points.") % {"id": zone_id}
                )
            if item.get("in") not in SIDES:
                raise ZoneError(
                    _("Say which side of the line %(id)s is inside the pharmacy.") % {"id": zone_id}
                )
            zone["in"] = item["in"]
        elif not MIN_POINTS <= len(points) <= MAX_POINTS:
            raise ZoneError(_("Zone %(id)s needs 3 to 24 points.") % {"id": zone_id})
        zones.append(zone)
    return zones


def _points(raw, zone_id: str) -> list[list[float]]:
    if not isinstance(raw, list):
        raise ZoneError(_("Zone %(id)s has no points.") % {"id": zone_id})
    points = []
    for point in raw:
        if (
            not isinstance(point, list | tuple)
            or len(point) != 2
            or not all(_number(value) for value in point)
        ):
            raise ZoneError(_("Each point of zone %(id)s is a pair of numbers.") % {"id": zone_id})
        x, y = (float(value) for value in point)
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ZoneError(
                _("Every point of zone %(id)s must lie inside the picture.") % {"id": zone_id}
            )
        points.append([round(x, 4), round(y, 4)])
    return points


def _number(value) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def has(zones: list[dict], kind: str) -> bool:
    return any(zone.get("kind") == kind for zone in zones or [])
