"""Time behind one small interface, so tests can run minutes of scene time in milliseconds.

Every part of the agent asks a ``Clock`` for the time and sleeps through it. ``SystemClock`` is the
real one; ``FakeClock`` only moves when a test advances it (and ``sleep`` advances it at once).
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def time(self) -> float:
        """Seconds since the epoch (UTC wall time)."""
        ...

    def monotonic(self) -> float:
        """A clock that never goes backwards, for measuring durations."""
        ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock:
    """A clock that moves only when told to. ``sleep`` advances it immediately."""

    def __init__(self, start: float = 1_795_438_800.0) -> None:  # 2026-11-23T13:00:00Z
        self._start = float(start)
        self._offset = 0.0
        self._lock = threading.Lock()

    def time(self) -> float:
        with self._lock:
            return self._start + self._offset

    def monotonic(self) -> float:
        with self._lock:
            return 10_000.0 + self._offset

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.advance(seconds)

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._offset += float(seconds)


def iso(t: float) -> str:
    """``2026-11-23T16:31:05Z``: whole seconds, UTC."""
    return datetime.fromtimestamp(int(t), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ms(t: float) -> str:
    """``2026-11-23T16:31:05.400Z``: milliseconds, UTC."""
    ms = round(t * 1000)
    base = datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms % 1000:03d}Z"


def parse_iso(text: str) -> float:
    """Parse an ISO 8601 time (``Z`` or an offset) into epoch seconds."""
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def minute_floor(t: float) -> float:
    return float(int(t // 60) * 60)
