"""Pure logic: the flap rule, incidents and uptime math. No I/O here, so it is easy to test."""

from __future__ import annotations

from dataclasses import dataclass, field

DAY = 86400
WINDOWS = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY, "90d": 90 * DAY}


@dataclass
class CheckState:
    """Running state for one check. A check is "down" only after `threshold` failures in a row."""

    threshold: int = 2
    fails: int = 0
    first_fail_ts: float | None = None
    down: bool = False
    incident_start: float | None = None
    events: list = field(default_factory=list)

    def observe(self, ts: float, ok: bool) -> str | None:
        """Feed one result. Returns "down" when an incident opens, "up" when it closes, else None.

        The incident starts at the first failure of the streak (that is when it really broke),
        but it is only declared after the threshold is reached, so one blip never counts.
        """
        if ok:
            self.fails = 0
            self.first_fail_ts = None
            if self.down:
                self.down = False
                return "up"
            return None
        self.fails += 1
        if self.fails == 1:
            self.first_fail_ts = ts
        if not self.down and self.fails >= self.threshold:
            self.down = True
            self.incident_start = self.first_fail_ts
            return "down"
        return None


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def uptime(incidents, start: float, end: float, coverage_start: float | None) -> float | None:
    """Uptime % in [start, end] given incidents as (start, end_or_None).

    Time before the first sample (`coverage_start`) is not counted either way.
    Returns None when there is no data in the window.
    """
    if coverage_start is None:
        return None
    start = max(start, coverage_start)
    if end <= start:
        return None
    total = end - start
    down = sum(overlap(s, e if e is not None else end, start, end) for s, e in incidents)
    return round(max(0.0, 100.0 * (1 - down / total)), 3)


def uptimes(incidents, now: float, coverage_start: float | None) -> dict:
    return {k: uptime(incidents, now - w, now, coverage_start) for k, w in WINDOWS.items()}


def daily_bars(incidents, now: float, coverage_start: float | None, days: int = 90, tz_offset: int = 0):
    """One entry per local day, oldest first: {"day": unix day start, "uptime": % or None, "down_s": seconds}."""
    local_now = now + tz_offset
    today0 = local_now - (local_now % DAY) - tz_offset
    out = []
    for i in range(days - 1, -1, -1):
        d0 = today0 - i * DAY
        d1 = min(d0 + DAY, now)
        up = uptime(incidents, d0, d1, coverage_start)
        down = sum(overlap(s, e if e is not None else now, max(d0, coverage_start or d0), d1) for s, e in incidents)
        out.append({"day": d0, "uptime": up, "down_s": round(down)})
    return out


def duration_text(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m" if m else f"{h}h"
    d, h = divmod(h, 24)
    return f"{d}d {h}h" if h else f"{d}d"


def level(statuses) -> str:
    """Combine check levels ("up", "warn", "down") into one: worst wins."""
    statuses = list(statuses)
    if "down" in statuses:
        return "down"
    if "warn" in statuses:
        return "warn"
    return "up"


def overall(service_levels) -> str:
    """operational / degraded / partial / major."""
    levels = list(service_levels)
    if not levels or all(lv == "up" for lv in levels):
        return "operational"
    if all(lv == "down" for lv in levels):
        return "major"
    if "down" in levels:
        return "partial"
    return "degraded"
