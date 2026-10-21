"""Distances on the Earth's surface, for geofences. The location is read only at the check-in
or check-out tap; nothing here tracks anyone."""

import math
from decimal import Decimal, InvalidOperation

EARTH_RADIUS_M = 6_371_008.8


def distance_m(lat1, lng1, lat2, lng2) -> int:
    """Great-circle (haversine) distance between two points in whole metres."""
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lng2) - float(lng1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a))))


def coordinate(value) -> Decimal | None:
    """A latitude or longitude rounded to the 6 places the models keep (about 11 cm)."""
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except InvalidOperation:
        return None


def valid_point(lat, lng) -> bool:
    try:
        return -90 <= float(lat) <= 90 and -180 <= float(lng) <= 180
    except TypeError, ValueError:
        return False
