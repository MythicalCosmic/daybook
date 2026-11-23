"""The PC's CPU use in percent, for the live report (no extra packages)."""

from __future__ import annotations

import ctypes
import os
import sys
import time


def _system_times() -> tuple[float, float] | None:
    """(idle, total) CPU time so far, in any unit."""
    if sys.platform == "win32":
        idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
        ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined]
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
        if not ok:
            return None
        return float(idle.value), float(kernel.value + user.value)  # kernel includes idle
    try:
        with open("/proc/stat", encoding="ascii") as fh:
            parts = [float(v) for v in fh.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
    return idle, sum(parts)


class CpuMeter:
    def __init__(self) -> None:
        self._last = _system_times()
        self._last_proc = (time.process_time(), time.monotonic())
        self.value = 0

    def sample(self) -> int:
        now = _system_times()
        if now is not None and self._last is not None:
            idle = now[0] - self._last[0]
            total = now[1] - self._last[1]
            self._last = now
            if total > 0:
                self.value = round(max(0.0, min(100.0, 100.0 * (1.0 - idle / total))))
                return self.value
        cpu, wall = time.process_time(), time.monotonic()
        d_cpu, d_wall = cpu - self._last_proc[0], wall - self._last_proc[1]
        self._last_proc = (cpu, wall)
        if d_wall > 0:
            share = d_cpu / d_wall / max(1, os.cpu_count() or 1)
            self.value = round(max(0.0, min(100.0, 100.0 * share)))
        return self.value
