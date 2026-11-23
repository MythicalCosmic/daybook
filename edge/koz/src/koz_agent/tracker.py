"""An IoU + centroid tracker with stable ids.

Each frame, detections are matched to the tracks' predicted boxes, first by overlap (IoU) and then,
for what is left, by the distance between centres measured in box heights, so people who walk far
between two analysed frames (2 fps) keep their id. Unmatched detections start new tracks; a track
that is not seen for ``max_age_s`` is dropped. Ids only grow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .frames import Detection
from .geometry import Box, Point, centre, iou


@dataclass
class Track:
    id: int
    box: Box  # pixels, x1 y1 x2 y2
    score: float
    first_seen: float
    last_seen: float
    hits: int = 1
    vx: float = 0.0  # centre velocity, pixels per second
    vy: float = 0.0
    visible: bool = True
    # state kept by the analysis
    queue_since: float | None = None
    queue_last_in: float | None = None
    line_side: dict[str, int] = field(default_factory=dict)
    line_anchor: dict[str, Point] = field(default_factory=dict)

    @property
    def height(self) -> float:
        return max(1.0, self.box[3] - self.box[1])

    def predicted_box(self, t: float) -> Box:
        dt = min(max(t - self.last_seen, 0.0), 2.0)
        dx, dy = self.vx * dt, self.vy * dt
        x1, y1, x2, y2 = self.box
        return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)


class Tracker:
    def __init__(
        self,
        *,
        iou_match: float = 0.2,
        max_jump: float = 1.2,
        max_age_s: float = 2.0,
        max_speed: float = 900.0,
    ) -> None:
        self.iou_match = iou_match
        self.max_jump = max_jump  # in box heights
        self.max_age_s = max_age_s
        self.max_speed = max_speed  # pixels per second
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def reset(self) -> None:
        self.tracks.clear()

    def update(self, detections: list[Detection], t: float) -> list[Track]:
        for stale in [tr for tr in self.tracks.values() if t - tr.last_seen > self.max_age_s]:
            del self.tracks[stale.id]
        tracks = list(self.tracks.values())
        predicted = [tr.predicted_box(t) for tr in tracks]
        assigned: dict[int, int] = {}  # track index → detection index
        used: set[int] = set()

        pairs = []
        for ti, pbox in enumerate(predicted):
            for di, det in enumerate(detections):
                overlap = iou(pbox, det.box)
                if overlap >= self.iou_match:
                    pairs.append((overlap, ti, di))
        for _overlap, ti, di in sorted(pairs, key=lambda p: (-p[0], p[1], p[2])):
            if ti not in assigned and di not in used:
                assigned[ti] = di
                used.add(di)

        candidates = []
        for ti, pbox in enumerate(predicted):
            if ti in assigned:
                continue
            pc = centre(pbox)
            ph = max(1.0, pbox[3] - pbox[1])
            for di, det in enumerate(detections):
                if di in used:
                    continue
                dh = max(1.0, det.box[3] - det.box[1])
                if not 0.5 <= dh / ph <= 2.0:
                    continue
                dc = centre(det.box)
                distance = ((dc[0] - pc[0]) ** 2 + (dc[1] - pc[1]) ** 2) ** 0.5 / max(ph, dh)
                if distance <= self.max_jump:
                    candidates.append((distance, ti, di))
        for _distance, ti, di in sorted(candidates):
            if ti not in assigned and di not in used:
                assigned[ti] = di
                used.add(di)

        for ti, tr in enumerate(tracks):
            di = assigned.get(ti)
            if di is None:
                tr.visible = False
                continue
            det = detections[di]
            dt = t - tr.last_seen
            if dt > 1e-6:
                old_c, new_c = centre(tr.box), centre(det.box)
                vx = (new_c[0] - old_c[0]) / dt
                vy = (new_c[1] - old_c[1]) / dt
                speed = (vx * vx + vy * vy) ** 0.5
                if speed > self.max_speed:
                    vx, vy = vx * self.max_speed / speed, vy * self.max_speed / speed
                if tr.hits == 1:
                    tr.vx, tr.vy = vx, vy
                else:
                    tr.vx, tr.vy = 0.5 * tr.vx + 0.5 * vx, 0.5 * tr.vy + 0.5 * vy
            tr.box = det.box
            tr.score = det.score
            tr.last_seen = t
            tr.hits += 1
            tr.visible = True

        for tr in tracks:
            if not tr.visible and t - tr.last_seen > self.max_age_s:
                del self.tracks[tr.id]

        for di, det in enumerate(detections):
            if di in used:
                continue
            tr = Track(id=self._next_id, box=det.box, score=det.score, first_seen=t, last_seen=t)
            self._next_id += 1
            self.tracks[tr.id] = tr

        return sorted((tr for tr in self.tracks.values() if tr.visible), key=lambda tr: tr.id)
