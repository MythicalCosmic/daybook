"""Live numbers of the demo's boxes, made from the clock (docs/KOZ.md §9): the demo has no box
sending reports, yet its live page moves. Every number is a function of the time and the camera,
so two people looking at once see the same thing, and nothing is stored.

    busy(branch, moment)          how busy the pharmacy is then, 0..1 (0 while it is closed)
    camera_report(camera, now)    what a box would report for the camera now (as live/ does)
    branch_today(branch, now)     (visitors, receipts) so far today at the branch
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise

from apps.attendance import clock

# (hour of the day, how busy): a quiet morning, a lunch bump and the evening peak.
CURVE = (
    (0.0, 0.06),
    (6.0, 0.05),
    (8.0, 0.25),
    (9.5, 0.55),
    (11.0, 0.45),
    (13.0, 0.6),
    (15.0, 0.45),
    (17.0, 0.7),
    (18.5, 1.0),
    (20.0, 0.8),
    (21.5, 0.4),
    (23.0, 0.15),
    (24.0, 0.06),
)
TICK = 5  # seconds: a box reports every 5 s
# Visitors a minute at the busiest moment; receipts are a share of them.
VISITORS_AT_PEAK = {False: 0.45, True: 0.6}


def noise(*parts) -> float:
    """A number in [0, 1) that depends only on `parts`."""
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def is_open(branch, moment: datetime) -> bool:
    if branch.open_24h:
        return True
    local = clock.local(branch.company, moment).time()
    opens = branch.opens_at or time(8, 0)
    closes = branch.closes_at or time(22, 0)
    return opens <= local < closes


def busy(branch, moment: datetime) -> float:
    if not is_open(branch, moment):
        return 0.0
    local = clock.local(branch.company, moment)
    hour = local.hour + local.minute / 60 + local.second / 3600
    for (start, low), (end, high) in pairwise(CURVE):
        if start <= hour <= end:
            return low + (high - low) * (hour - start) / (end - start)
    return CURVE[-1][1]


def camera_report(camera, now: datetime) -> dict:
    """people, queue, staff and the longest wait as a box would report them now."""
    tick = int(now.timestamp() // TICK)
    level = busy(camera.branch, now)
    jitter = noise("koz", camera.pk, tick)
    queue = staff = wait = 0
    if camera.role == "counter" and level:
        queue = round(level * 5 * (0.4 + 0.9 * jitter))
        staff = 1 + int(level > 0.75 and noise("staff", camera.pk, tick // 24) > 0.45)
        wait = queue * 22 + int(noise("wait", camera.pk, tick) * 25) if queue else 0
        people = queue + staff
    elif camera.role == "entrance":
        people = round(level * 3 * jitter)
    elif camera.role == "floor":
        people = round(level * 7 * (0.3 + 0.7 * jitter)) + (1 if level else 0)
    elif camera.role == "storeroom":
        people = int(jitter > 0.75) if level else 0
    else:
        people = 0
    return {
        "online": True,
        "fps": 2.0,
        "people": people,
        "queue": queue,
        "staff": staff,
        "wait_s": wait,
        "error": None,
    }


def branch_today(branch, now: datetime) -> tuple[int, int]:
    """Visitors and receipts at the branch from midnight to now, minute by minute."""
    local = clock.local(branch.company, now)
    midnight = clock.at(branch.company, local.date(), time(0, 0))
    peak = VISITORS_AT_PEAK[bool(branch.open_24h)]
    visitors = 0.0
    minute = midnight
    while minute < now:
        level = busy(branch, minute)
        if level:
            visitors += level * peak * (0.6 + 0.8 * noise("in", branch.pk, minute.timestamp()))
        minute += timedelta(minutes=1)
    share = 0.62 + 0.1 * noise("buy", branch.pk, local.date())
    return int(visitors), int(visitors * share)


def frame(camera, now: datetime | None = None) -> dict | None:
    """A live frame of a demo camera: its drawn scene with the people of `camera_report`, the
    same for everyone watching in the same half second (kept 2 s in the cache)."""
    from django.core.cache import cache
    from django.utils import timezone

    from apps.vision import demo_art

    now = now or timezone.now()
    key = f"vision:demo-frame:{camera.pk}:{int(now.timestamp() * 2)}"
    found = cache.get(key)
    if found is not None:
        return found
    scene = demo_art.scene_of(camera.role)
    sway = math.sin(now.timestamp() / 2.5)
    people = demo_art.people_for(
        camera.role, camera_report(camera, now), seed=camera.pk, drift=sway
    )
    image = demo_art.render(scene, people, size=(960, 540), seed=camera.pk, zones=camera.zones)
    found = {
        "at": now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "w": 960,
        "h": 540,
        "people": demo_art.frame_people(people, scene),
        "jpeg": demo_art.encode(image, quality=78),
    }
    cache.set(key, found, 2)
    return found
