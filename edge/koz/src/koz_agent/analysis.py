"""Per-camera analysis of one frame: masks, tracking, zones, waits, line crossings and who is
staff (contract §4, §5.5, §5.6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .frames import Detection
from .geometry import Box, Point, clip_box, extend_segment, foot_point, segments_intersect
from .geometry import side_of_line, side_sign
from .tracker import Tracker
from .zones import ZoneSet

FOOT_MAX = 0.999999  # a box cut by the bottom edge still has its foot inside the frame


@dataclass(frozen=True)
class Person:
    track: int
    box: Box  # normalized x1 y1 x2 y2
    foot: Point  # normalized
    role: str  # "staff" inside a staff zone, otherwise "customer"
    zone: str | None
    in_queue: bool
    in_staff: bool
    wait_s: float | None  # only inside a queue zone
    score: float = 1.0
    vx: float = 0.0  # normalized units per second
    vy: float = 0.0

    def to_meta(self) -> dict:
        x1, y1, x2, y2 = self.box
        item: dict = {
            "track": self.track,
            "box": [round(x1, 4), round(y1, 4), round(x2 - x1, 4), round(y2 - y1, 4)],
            "role": self.role,
            "zone": self.zone,
        }
        if self.in_queue and self.wait_s is not None:
            item["wait_s"] = int(self.wait_s)
        return item


@dataclass(frozen=True)
class Crossing:
    track: int
    line: str
    direction: str  # "entered" or "exited"


@dataclass
class FrameResult:
    t: float
    w: int
    h: int
    people: list[Person] = field(default_factory=list)
    crossings: list[Crossing] = field(default_factory=list)

    @property
    def people_count(self) -> int:
        return len(self.people)

    @property
    def queue(self) -> int:
        return sum(1 for p in self.people if p.in_queue)

    @property
    def staff(self) -> int:
        return sum(1 for p in self.people if p.in_staff)

    @property
    def wait_s(self) -> int:
        waits = [p.wait_s for p in self.people if p.in_queue and p.wait_s is not None]
        return int(max(waits)) if waits else 0

    @property
    def entered(self) -> int:
        return sum(1 for c in self.crossings if c.direction == "entered")

    @property
    def exited(self) -> int:
        return sum(1 for c in self.crossings if c.direction == "exited")


class CameraAnalyzer:
    def __init__(
        self,
        zones: ZoneSet | None = None,
        *,
        queue_grace_s: float = 3.0,
        line_margin: float = 0.01,
        max_age_s: float = 2.0,
    ) -> None:
        self.zones = zones or ZoneSet()
        self.queue_grace_s = queue_grace_s
        self.line_margin = line_margin
        self.tracker = Tracker(max_age_s=max_age_s)

    def set_zones(self, zones: ZoneSet) -> None:
        old_lines = {z.id: z for z in self.zones.lines}
        self.zones = zones
        for zone in zones.lines:
            if old_lines.get(zone.id) != zone:
                for tr in self.tracker.tracks.values():
                    tr.line_side.pop(zone.id, None)
                    tr.line_anchor.pop(zone.id, None)

    def process(self, detections: list[Detection], t: float, w: int, h: int) -> FrameResult:
        kept: list[Detection] = []
        for det in detections:
            box = clip_box(det.box, w, h)
            if box[2] - box[0] < 2 or box[3] - box[1] < 2:
                continue
            if self.zones.in_mask(self._foot(box, w, h)):
                continue
            kept.append(Detection(box, det.score))

        result = FrameResult(t=t, w=w, h=h)
        for tr in self.tracker.update(kept, t):
            foot = self._foot(tr.box, w, h)
            queue_zone = self.zones.queue_zone(foot)
            staff_zone = self.zones.staff_zone(foot)

            wait = None
            if queue_zone is not None:
                gone_too_long = (
                    tr.queue_last_in is not None and t - tr.queue_last_in > self.queue_grace_s
                )
                if tr.queue_since is None or gone_too_long:
                    tr.queue_since = t
                tr.queue_last_in = t
                wait = max(0.0, t - tr.queue_since)
            elif tr.queue_last_in is not None and t - tr.queue_last_in > self.queue_grace_s:
                tr.queue_since = None
                tr.queue_last_in = None

            for line in self.zones.lines:
                crossing = self._line_step(tr, line.id, line.points, line.inside or "left", foot)
                if crossing:
                    result.crossings.append(Crossing(tr.id, line.id, crossing))

            x1, y1, x2, y2 = tr.box
            result.people.append(
                Person(
                    track=tr.id,
                    box=(x1 / w, y1 / h, x2 / w, y2 / h),
                    foot=foot,
                    role="staff" if staff_zone else "customer",
                    zone=self.zones.zone_of(foot),
                    in_queue=queue_zone is not None,
                    in_staff=staff_zone is not None,
                    wait_s=wait,
                    score=tr.score,
                    vx=tr.vx / w,
                    vy=tr.vy / h,
                )
            )
        return result

    def _line_step(self, tr, line_id: str, points, inside: str, foot: Point) -> str | None:
        a, b = points
        side = side_of_line(foot, a, b, self.line_margin)
        if side == 0:
            return None
        previous = tr.line_side.get(line_id)
        anchor = tr.line_anchor.get(line_id)
        tr.line_side[line_id] = side
        tr.line_anchor[line_id] = foot
        if previous is None or previous == side or anchor is None:
            return None
        ea, eb = extend_segment(a, b, self.line_margin * 2)
        if not segments_intersect(anchor, foot, ea, eb):
            return None  # went round the end of the line
        return "entered" if side == side_sign(inside) else "exited"

    @staticmethod
    def _foot(box: Box, w: int, h: int) -> Point:
        fx, fy = foot_point(box)
        return (min(max(fx / w, 0.0), FOOT_MAX), min(max(fy / h, 0.0), FOOT_MAX))
