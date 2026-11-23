"""Queue and unattended incidents with hysteresis (contract §5.8).

- **queue**: at least ``queue_people`` in the queue zones and the longest wait at least
  ``queue_wait_s``, for 5 s in a row → ``start``; ends after ``clear_after_s`` with either below.
- **unattended**: at least one person in a queue zone and nobody in the staff zones for
  ``unattended_s`` → ``start``; ends after ``clear_after_s`` with someone in a staff zone or nobody
  waiting.
- While open, an ``update`` goes out at most once a minute (every 60 s).
- Only ``counter`` cameras with the zones a rule needs raise alerts. If a camera stops delivering
  frames for ``stale_s``, or stops qualifying, its open incidents end.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from .clock import iso
from .rules import Rules

START_HOLD_S = 5.0
UPDATE_EVERY_S = 60.0


@dataclass
class _Rule:
    kind: str
    cond_since: float | None = None
    clear_since: float | None = None
    incident_id: str | None = None
    started_at: float | None = None
    last_sent_at: float | None = None
    peak_queue: int = 0
    peak_wait_s: int = 0

    @property
    def open(self) -> bool:
        return self.incident_id is not None


class IncidentEngine:
    def __init__(
        self,
        key: str,
        rules: Rules | None = None,
        *,
        new_id: Callable[[], str] | None = None,
        stale_s: float = 60.0,
    ) -> None:
        self.key = key
        self.rules = rules or Rules()
        self.queue_enabled = False
        self.unattended_enabled = False
        self.stale_s = stale_s
        self._new_id = new_id or (lambda: str(uuid.uuid4()))
        self._rules = {"queue": _Rule("queue"), "unattended": _Rule("unattended")}
        self._last: tuple[float, int, int, int] | None = None  # t, queue, wait, staff

    def configure(
        self, rules: Rules, *, is_counter: bool, has_queue: bool, has_staff: bool, at: float
    ) -> list[dict]:
        """Apply new rules or zones; incidents that no longer qualify end now."""
        self.rules = rules
        self.queue_enabled = is_counter and has_queue
        self.unattended_enabled = is_counter and has_queue and has_staff
        events = []
        for kind, enabled in (("queue", self.queue_enabled), ("unattended", self.unattended_enabled)):
            rule = self._rules[kind]
            if not enabled:
                if rule.open:
                    events.append(self._end(rule, at))
                rule.cond_since = rule.clear_since = None
        return events

    def open_incidents(self) -> list[dict]:
        return [
            {
                "kind": r.kind,
                "incident_id": r.incident_id,
                "started_at": r.started_at,
                "peak_queue": r.peak_queue,
                "peak_wait_s": r.peak_wait_s,
            }
            for r in self._rules.values()
            if r.open
        ]

    def check_stale(self, now: float) -> list[dict]:
        """End open incidents when no frame came for ``stale_s`` (the camera went away)."""
        if self._last is None or now - self._last[0] < self.stale_s:
            return []
        events = []
        for rule in self._rules.values():
            if rule.open:
                events.append(self._end(rule, now))
            rule.cond_since = rule.clear_since = None
        return events

    def step(self, t: float, queue: int, wait_s: int, staff: int) -> list[dict]:
        self._last = (t, queue, wait_s, staff)
        events: list[dict] = []
        r = self.rules
        if self.queue_enabled:
            active = queue >= r.queue_people and wait_s >= r.queue_wait_s
            events += self._advance(self._rules["queue"], t, active, START_HOLD_S)
        if self.unattended_enabled:
            active = queue >= 1 and staff == 0
            events += self._advance(self._rules["unattended"], t, active, float(r.unattended_s))
        return events

    def _advance(self, rule: _Rule, t: float, active: bool, hold_s: float) -> list[dict]:
        _, queue, wait_s, _staff = self._last  # type: ignore[misc]
        if not rule.open:
            if not active:
                rule.cond_since = None
                return []
            if rule.cond_since is None:
                rule.cond_since = t
            if t - rule.cond_since < hold_s:
                return []
            rule.incident_id = self._new_id()
            rule.started_at = t
            rule.peak_queue = queue
            rule.peak_wait_s = wait_s
            rule.clear_since = None
            rule.last_sent_at = t
            return [self._event(rule, "start", t)]

        rule.peak_queue = max(rule.peak_queue, queue)
        rule.peak_wait_s = max(rule.peak_wait_s, wait_s)
        if active:
            rule.clear_since = None
        else:
            if rule.clear_since is None:
                rule.clear_since = t
            if t - rule.clear_since >= self.rules.clear_after_s:
                return [self._end(rule, t)]
        if rule.last_sent_at is not None and t - rule.last_sent_at >= UPDATE_EVERY_S:
            rule.last_sent_at = t
            return [self._event(rule, "update", t)]
        return []

    def _end(self, rule: _Rule, t: float) -> dict:
        event = self._event(rule, "end", t)
        rule.incident_id = None
        rule.started_at = None
        rule.cond_since = rule.clear_since = rule.last_sent_at = None
        rule.peak_queue = rule.peak_wait_s = 0
        return event

    def _event(self, rule: _Rule, phase: str, t: float) -> dict:
        _, queue, wait_s, staff = self._last or (t, 0, 0, 0)
        return {
            "event_id": self._new_id(),
            "incident_id": rule.incident_id,
            "kind": rule.kind,
            "phase": phase,
            "key": self.key,
            "at": iso(t),
            "started_at": iso(rule.started_at if rule.started_at is not None else t),
            "queue": int(queue),
            "wait_s": int(wait_s),
            "staff": int(staff),
            "peak_queue": int(rule.peak_queue),
            "peak_wait_s": int(rule.peak_wait_s),
        }
