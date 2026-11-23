"""One inference budget shared by every camera, so the PC stays cool.

Cameras take turns (round robin). No camera is analysed more often than its ``analysis_fps``, and
all of them together never more than ``max_per_s`` times a second (default 6).
"""

from __future__ import annotations

from collections.abc import Callable


class InferenceScheduler:
    def __init__(self, max_per_s: float = 6.0) -> None:
        self.max_per_s = max(0.1, float(max_per_s))
        self._fps: dict[str, float] = {}
        self._order: list[str] = []
        self._due: dict[str, float] = {}
        self._next_global = 0.0
        self._cursor = 0

    def set_cameras(self, fps_by_key: dict[str, float]) -> None:
        """Which cameras to analyse and at what rate; others are dropped."""
        self._fps = {k: max(0.1, float(v)) for k, v in fps_by_key.items() if v and v > 0}
        self._order = sorted(self._fps)
        self._due = {k: self._due.get(k, 0.0) for k in self._order}
        self._cursor %= max(1, len(self._order))

    @property
    def cameras(self) -> list[str]:
        return list(self._order)

    def next(self, now: float, ready: Callable[[str], bool] = lambda _k: True) -> str | None:
        """The camera to analyse now, or None. ``ready`` says whether a camera has a new frame."""
        if not self._order or now < self._next_global:
            return None
        n = len(self._order)
        for i in range(n):
            key = self._order[(self._cursor + i) % n]
            if now >= self._due[key] and ready(key):
                self._cursor = (self._cursor + i + 1) % n
                period = 1.0 / self._fps[key]
                # keep a steady rhythm, but never bank up turns after a pause
                base = self._due[key] if now - self._due[key] < period else now
                self._due[key] = base + period
                self._next_global = now + 1.0 / self.max_per_s
                return key
        return None

    def wait_hint(self, now: float) -> float:
        """Seconds until something could be due (for sleeping)."""
        if not self._order:
            return 0.5
        soonest = min(self._due.values())
        return max(0.0, max(soonest, self._next_global) - now)
