"""Minute stats of one camera (contract §5.7).

Every analysed frame adds to the bucket of the UTC minute it was taken in. ``staff_seconds`` is
measured by holding each frame's state until the next frame (at most ``hold_cap_s``), split exactly
at minute boundaries. A minute is closed once the clock is past its end by ``grace_s``; minutes
without a single frame are not reported.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import FrameResult
from .clock import iso, minute_floor


@dataclass
class _Bucket:
    minute: float
    frames: int = 0
    people_sum: int = 0
    people_max: int = 0
    queue_sum: int = 0
    queue_max: int = 0
    entered: int = 0
    exited: int = 0
    wait_max: int = 0
    staff_seconds: float = 0.0


class MinuteAggregator:
    def __init__(self, key: str, *, hold_cap_s: float = 3.0, grace_s: float = 1.0) -> None:
        self.key = key
        self.hold_cap_s = hold_cap_s
        self.grace_s = grace_s
        self._buckets: dict[float, _Bucket] = {}
        self._prev_t: float | None = None
        self._prev_staff = False
        self._credited_until = 0.0

    def _bucket(self, minute: float) -> _Bucket:
        bucket = self._buckets.get(minute)
        if bucket is None:
            bucket = self._buckets[minute] = _Bucket(minute)
        return bucket

    def _credit(self, until: float) -> None:
        """Credit the previous frame's staff state from where we stopped up to ``until``."""
        if self._prev_t is None:
            return
        start = max(self._credited_until, self._prev_t)
        end = min(until, self._prev_t + self.hold_cap_s)
        if end <= start:
            return
        if self._prev_staff:
            s = start
            while s < end - 1e-9:
                minute = minute_floor(s)
                e = min(end, minute + 60.0)
                self._bucket(minute).staff_seconds += e - s
                s = e
        self._credited_until = end

    def add(self, result: FrameResult) -> None:
        t = result.t
        if self._prev_t is not None and t < self._prev_t:
            return  # out of order; never happens with one analysis thread
        self._credit(t)
        bucket = self._bucket(minute_floor(t))
        people, queue = result.people_count, result.queue
        bucket.frames += 1
        bucket.people_sum += people
        bucket.people_max = max(bucket.people_max, people)
        bucket.queue_sum += queue
        bucket.queue_max = max(bucket.queue_max, queue)
        bucket.entered += result.entered
        bucket.exited += result.exited
        bucket.wait_max = max(bucket.wait_max, result.wait_s)
        self._prev_t = t
        self._prev_staff = result.staff > 0
        self._credited_until = t

    def close_until(self, now: float) -> list[dict]:
        """Rows for every minute that ended at least ``grace_s`` before ``now``, oldest first."""
        rows = []
        for minute in sorted(self._buckets):
            end = minute + 60.0
            if end + self.grace_s > now:
                break
            self._credit(end)
            bucket = self._buckets.pop(minute)
            if bucket.frames == 0:
                continue
            rows.append(self._row(bucket))
        return rows

    def pending_minutes(self) -> int:
        return len(self._buckets)

    def _row(self, b: _Bucket) -> dict:
        return {
            "key": self.key,
            "minute": iso(b.minute),
            "frames": b.frames,
            "people_avg": round(b.people_sum / b.frames, 2),
            "people_max": b.people_max,
            "entered": b.entered,
            "exited": b.exited,
            "queue_avg": round(b.queue_sum / b.frames, 2),
            "queue_max": b.queue_max,
            "wait_max_s": int(b.wait_max),
            "staff_seconds": int(min(60, max(0, round(b.staff_seconds)))),
        }
