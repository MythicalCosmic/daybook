"""The agent itself: analysis, reports to Daybook, the recorder and clip jobs.

Work is split into steps that a test can drive with a ``FakeClock`` (``tick``, ``record_tick``,
``net_tick``, ``clip_tick``); a real run calls each step in a loop on a thread of its own, so a
slow network never holds up the analysis.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__
from .analysis import CameraAnalyzer, FrameResult
from .annotate import alert_photo, apply_masks, encode_jpeg, preview
from .client import DaybookClient, DaybookError, OfflineError, RevokedError
from .clock import Clock, iso, iso_ms, parse_iso
from .cpu import CpuMeter
from .detectors import Detector
from .frames import Frame
from .incidents import IncidentEngine
from .outbox import Outbox
from .recorder import Clip, ClipError, Recorder
from .rules import Rules
from .scheduler import InferenceScheduler
from .sources import Source
from .stats import MinuteAggregator
from .zones import ZoneSet

log = logging.getLogger(__name__)

LIVE_EVERY_S = 5.0
INVENTORY_EVERY_S = 600.0
CONFIG_EVERY_S = 600.0
SNAPSHOT_EVERY_S = 600.0
SNAPSHOT_SOON_S = 2.0
STATS_FLUSH_EVERY_S = 5.0
OFFLINE_PAUSE_S = 10.0
FRESH_RESULT_S = 10.0
CLIP_GRACE_S = 2.0
FRAME_MAX_BYTES = 400_000
FRAME_MAX_WIDTH = 960
SNAPSHOT_MAX_BYTES = 1_500_000


@dataclass
class CameraConfig:
    """What Daybook says about a camera (or, before pairing, the scene's suggestion)."""

    id: int | None = None
    name: str | None = None
    role: str = "other"
    enabled: bool = False
    zones: list = field(default_factory=list)
    register_id: int | None = None

    @classmethod
    def from_server(cls, data: dict) -> CameraConfig:
        return cls(
            id=data.get("id"),
            name=data.get("name"),
            role=data.get("role") or "other",
            enabled=bool(data.get("enabled")),
            zones=list(data.get("zones") or []),
            register_id=data.get("register_id"),
        )


class Cam:
    """One camera's moving parts."""

    def __init__(self, source: Source, detector: Detector) -> None:
        self.source = source
        self.key = source.key
        self.detector = detector
        self.cfg = CameraConfig()
        self.zones = ZoneSet()
        self.analyzer = CameraAnalyzer()
        self.stats = MinuteAggregator(self.key)
        self.incidents = IncidentEngine(self.key)
        self.last_seq = -1
        self.frame: Frame | None = None  # the frame of ``result``
        self.result: FrameResult | None = None
        self.analysed: deque[float] = deque(maxlen=64)
        self.day: int | None = None
        self.entered_today = 0
        self.exited_today = 0
        self.snapshot_due_at: float | None = 0.0
        self.last_snapshot_at: float | None = None
        self.last_frame_sent_at = -1e9
        self.frame_sent_seq = -1
        self.next_record_at = 0.0
        self.error: str | None = None

    @property
    def name(self) -> str:
        return self.cfg.name or self.source.name

    def fps(self, now: float) -> float:
        recent = [t for t in self.analysed if now - t <= 5.0]
        if len(recent) < 2:
            return 0.0
        span = max(recent[-1] - recent[0], 1e-6)
        return round((len(recent) - 1) / span, 1)

    def fresh_result(self, now: float) -> FrameResult | None:
        if self.result is None or now - self.result.t > FRESH_RESULT_S:
            return None
        return self.result


class Agent:
    def __init__(
        self,
        *,
        clock: Clock,
        sources: list[Source],
        detector_for: Callable[[Source], Detector],
        client: DaybookClient | None = None,
        outbox: Outbox | None = None,
        recorder: Recorder | None = None,
        defaults: dict[str, CameraConfig] | None = None,
        max_inferences_per_s: float = 6.0,
        lang: str = "uz",
        config_cache: Path | None = None,
        nvr_clip: Callable[[Cam, float, float], Clip] | None = None,
        nvr_snapshot: Callable[[Cam], bytes | None] | None = None,
        detector_name: str = "sim",
        encoder: str | None = None,
    ) -> None:
        self.clock = clock
        self.client = client
        self.outbox = outbox
        self.recorder = recorder
        self.lang = lang
        self.config_cache = config_cache
        self.nvr_clip = nvr_clip
        self.nvr_snapshot = nvr_snapshot
        self.detector_name = detector_name
        self.encoder = encoder
        self.defaults = defaults or {}
        self.lock = threading.RLock()
        self.cams: dict[str, Cam] = {s.key: Cam(s, detector_for(s)) for s in sources}
        self.rules = Rules()
        self.scheduler = InferenceScheduler(max_inferences_per_s)
        self.watch: set[str] = set()
        self.jobs_flag = False
        self.config_version: str | None = None
        self.agent_info: dict | None = None
        self.pending_clips: dict[int, dict] = {}
        self.events_log: deque[dict] = deque(maxlen=40)
        self.started_at = clock.time()
        self.net_state = "unpaired" if client is None else "starting"
        self.net_error: str | None = None
        self.counters = {
            "frames_sent": 0,
            "snapshots_sent": 0,
            "events_sent": 0,
            "minutes_sent": 0,
            "clips_sent": 0,
            "clips_failed": 0,
            "lives_sent": 0,
        }
        self.server_skew_s: float | None = None
        self.cpu = CpuMeter()
        self._cpu_value = 0
        self._cpu_at = -1e9
        self._next = {
            "live": 0.0,
            "inventory": 0.0,
            "config": 0.0,
            "stats": 0.0,
            "housekeeping": 0.0,
            "purge": 0.0,
        }
        self._need_inventory = True
        self._need_config = True
        self._offline_until = 0.0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

        for key, cfg in self.defaults.items():
            if key in self.cams and client is None:
                self._set_cam_config(self.cams[key], cfg, clock.time())
        if client is not None and config_cache is not None and config_cache.exists():
            try:
                self.apply_config(
                    json.loads(config_cache.read_text(encoding="utf-8")), from_cache=True
                )
            except (OSError, ValueError) as exc:
                log.warning("cannot read the cached config: %s", exc)
        self._apply_rules()

    # --- configuration --------------------------------------------------------------------

    @property
    def paired(self) -> bool:
        return self.client is not None

    def apply_config(self, cfg: dict, *, from_cache: bool = False) -> None:
        now = self.clock.time()
        with self.lock:
            self.rules = Rules.from_dict(cfg.get("rules"))
            self.agent_info = cfg.get("agent") or self.agent_info
            known = {c.get("key"): c for c in cfg.get("cameras") or [] if isinstance(c, dict)}
            for key, cam in self.cams.items():
                data = known.get(key)
                self._set_cam_config(
                    cam, CameraConfig.from_server(data) if data else CameraConfig(), now
                )
            for key in cfg.get("snapshot_requested") or []:
                self._snapshot_soon(key, now)
            self.config_version = cfg.get("config_version")
            self._apply_rules()
        if not from_cache and self.config_cache is not None:
            try:
                self.config_cache.parent.mkdir(parents=True, exist_ok=True)
                self.config_cache.write_text(json.dumps(cfg), encoding="utf-8")
            except OSError as exc:
                log.warning("cannot cache the config: %s", exc)

    def _set_cam_config(self, cam: Cam, cfg: CameraConfig, now: float) -> None:
        cam.cfg = cfg
        cam.zones = ZoneSet.from_json(cfg.zones)
        cam.analyzer.set_zones(cam.zones)
        events = cam.incidents.configure(
            self.rules,
            is_counter=cfg.enabled and cfg.role == "counter",
            has_queue=cam.zones.has_queue,
            has_staff=cam.zones.has_staff,
            at=now,
        )
        self._queue_events(cam, events, None, now)

    def _apply_rules(self) -> None:
        enabled = {k: c for k, c in self.cams.items() if c.cfg.enabled}
        self.scheduler.set_cameras({k: self.rules.analysis_fps for k in enabled})
        for cam in self.cams.values():
            cam.incidents.rules = self.rules
        if self.recorder is not None:
            keys = {k for k, c in enabled.items() if c.cfg.role == "counter"}
            self.recorder.set_cameras(
                keys if self.rules.record_counter else set(), self.rules.record_hours
            )

    def _snapshot_soon(self, key: str, now: float) -> None:
        cam = self.cams.get(key)
        if cam is not None:
            due = now + SNAPSHOT_SOON_S
            cam.snapshot_due_at = (
                due if cam.snapshot_due_at is None else min(cam.snapshot_due_at, due)
            )

    # --- analysis -------------------------------------------------------------------------

    def tick(self) -> float:
        """Analyse the next camera that is due, if any. Returns a hint of how long to wait."""
        now = self.clock.time()

        def ready(key: str) -> bool:
            frame = self.cams[key].source.latest()
            return frame is not None and frame.seq != self.cams[key].last_seq

        with self.lock:
            key = self.scheduler.next(now, ready)
        if key is not None:
            self._analyse(self.cams[key], now)
        if now >= self._next["housekeeping"]:
            self._next["housekeeping"] = now + 1.0
            self.housekeeping(now)
        return self.scheduler.wait_hint(self.clock.time())

    def _analyse(self, cam: Cam, now: float) -> None:
        frame = cam.source.latest()
        if frame is None:
            return
        cam.last_seq = frame.seq
        try:
            detections = cam.detector.detect(frame)
        except Exception as exc:  # a broken model must not stop the other cameras
            cam.error = f"detector error: {type(exc).__name__}"
            log.exception("%s: detector failed", cam.key)
            return
        cam.error = None
        with self.lock:
            result = cam.analyzer.process(detections, frame.t, frame.w, frame.h)
            cam.result, cam.frame = result, frame
            cam.analysed.append(now)
            cam.stats.add(result)
            self._count_today(cam, result, now)
            events = cam.incidents.step(frame.t, result.queue, result.wait_s, result.staff)
            if events:
                self._queue_events(cam, events, (frame, result), now)

    def _count_today(self, cam: Cam, result: FrameResult, now: float) -> None:
        day = time.localtime(now).tm_yday
        if cam.day != day:
            cam.day, cam.entered_today, cam.exited_today = day, 0, 0
        cam.entered_today += result.entered
        cam.exited_today += result.exited

    def _queue_events(self, cam: Cam, events: list[dict], ctx, now: float) -> None:
        for event in events:
            image = None
            if event["phase"] == "start" and ctx is not None and self.rules.alert_photo:
                frame, result = ctx
                image = alert_photo(
                    frame.image,
                    result,
                    cam.zones,
                    kind=event["kind"],
                    privacy_blur=self.rules.privacy_blur,
                    lang=self.lang,
                )
            if self.client is not None and self.outbox is not None:
                self.outbox.put_event(event, image, created=now)
            self.events_log.appendleft(
                {
                    **{
                        k: event[k]
                        for k in (
                            "kind",
                            "phase",
                            "key",
                            "at",
                            "queue",
                            "wait_s",
                            "staff",
                            "peak_queue",
                            "peak_wait_s",
                        )
                    },
                    "camera": cam.name,
                    "photo": image is not None,
                }
            )
            log.info(
                "%s %s on %s (queue %s, wait %s s, staff %s)",
                event["kind"],
                event["phase"],
                cam.key,
                event["queue"],
                event["wait_s"],
                event["staff"],
            )

    def housekeeping(self, now: float) -> None:
        with self.lock:
            for cam in self.cams.values():
                rows = cam.stats.close_until(now)
                if rows and self.client is not None and self.outbox is not None:
                    self.outbox.put_stats(rows, created=now)
                stale = cam.incidents.check_stale(now)
                if stale:
                    self._queue_events(cam, stale, None, now)
        if now >= self._next["purge"]:
            self._next["purge"] = now + 3600.0
            if self.outbox is not None:
                dropped = self.outbox.purge(now)
                if dropped:
                    log.warning("dropped %d items older than 7 days", dropped)
            if self.recorder is not None:
                self.recorder.prune()

    # --- recording ------------------------------------------------------------------------

    def record_tick(self) -> float:
        recorder = self.recorder
        if recorder is None or not recorder.wanted:
            return 0.5
        now = self.clock.time()
        period = 1.0 / recorder.fps
        for key in sorted(recorder.wanted):
            cam = self.cams.get(key)
            if cam is None or now < cam.next_record_at:
                continue
            late = now - cam.next_record_at
            cam.next_record_at = (cam.next_record_at if late < period else now) + period
            frame = cam.source.latest()
            if frame is None or now - frame.t > 5.0:
                continue
            recorder.push(key, apply_masks(frame.image, cam.zones), now)
        return period

    # --- the network ----------------------------------------------------------------------

    def net_tick(self) -> float:
        """Talk to Daybook: inventory, config, live, jobs, frames, snapshots, events, stats."""
        if self.client is None:
            return 1.0
        now = self.clock.time()
        if now < self._offline_until:
            return min(1.0, self._offline_until - now)
        try:
            due = self._need_inventory or now >= self._next["inventory"]
            if due and not self._send_inventory(now):
                return 0.5
            if self._need_config or now >= self._next["config"]:
                self._fetch_config(now)
            if now >= self._next["live"]:
                self._send_live(now)
                if self._need_config:
                    self._fetch_config(now)
            if self.jobs_flag:
                self._fetch_jobs(now)
            self._send_frames(now)
            self._send_snapshots(now)
            self._flush_events(now)
            if now >= self._next["stats"]:
                self._flush_stats(now)
            self.net_state, self.net_error = "ok", None
        except RevokedError as exc:
            self.net_state = "not_paired" if exc.code == "not_paired" else "revoked"
            self.net_error = exc.detail or exc.code
        except OfflineError as exc:
            self.net_state, self.net_error = "offline", exc.detail or exc.code
            self._offline_until = self.clock.time() + OFFLINE_PAUSE_S
        except DaybookError as exc:
            self.net_state, self.net_error = "error", str(exc)
            log.warning("Daybook said %s", exc)
        return 0.1 if self.watch else 0.5

    def _send_inventory(self, now: float) -> bool:
        if (
            self._need_inventory
            and now - self.started_at < 15.0
            and any(cam.source.latest() is None for cam in self.cams.values())
        ):
            return False  # wait a moment for the cameras to give their size
        reply = self.client.cameras([cam.source.describe() for cam in self.cams.values()])
        with self.lock:
            for item in reply.get("cameras") or []:
                cam = self.cams.get(item.get("key"))
                if cam is not None and item.get("id") is not None:
                    cam.cfg.id = item["id"]
        self._need_inventory = False
        self._next["inventory"] = now + INVENTORY_EVERY_S
        return True

    def _fetch_config(self, now: float) -> None:
        self.apply_config(self.client.config())
        self._need_config = False
        self._next["config"] = now + CONFIG_EVERY_S

    def _live_payload(self, now: float) -> dict:
        self._cpu_value = self.cpu.sample()
        cameras, total_fps = [], 0.0
        with self.lock:
            for cam in self.cams.values():
                result = cam.fresh_result(now) if cam.cfg.enabled else None
                fps = cam.fps(now) if cam.cfg.enabled else 0.0
                total_fps += fps
                cameras.append(
                    {
                        "key": cam.key,
                        "online": cam.source.online,
                        "fps": fps,
                        "people": result.people_count if result else 0,
                        "queue": result.queue if result else 0,
                        "staff": result.staff if result else 0,
                        "wait_s": result.wait_s if result else 0,
                        "error": cam.error or cam.source.error,
                    }
                )
        return {
            "at": iso(now),
            "agent": {"version": __version__, "fps": round(total_fps, 1), "cpu": self._cpu_value},
            "cameras": cameras,
        }

    def _send_live(self, now: float) -> None:
        reply = self.client.live(self._live_payload(now))
        self.counters["lives_sent"] += 1
        self._next["live"] = now + LIVE_EVERY_S
        with self.lock:
            self.watch = {k for k in reply.get("watch") or [] if k in self.cams}
        version = reply.get("config_version")
        if version and version != self.config_version:
            self._need_config = True
        if (reply.get("jobs") or 0) > 0:
            self.jobs_flag = True
        if reply.get("server_time"):
            try:
                self.server_skew_s = round(parse_iso(reply["server_time"]) - now, 1)
                if abs(self.server_skew_s) > 120:
                    log.warning("this PC's clock is %+.0f s off Daybook's", -self.server_skew_s)
            except ValueError:
                pass

    def _fetch_jobs(self, now: float) -> None:
        jobs = self.client.jobs()
        self.jobs_flag = False
        with self.lock:
            for clip in jobs.get("clips") or []:
                try:
                    self.pending_clips[int(clip["id"])] = {
                        "key": clip["key"],
                        "start": parse_iso(clip["start"]),
                        "end": parse_iso(clip["end"]),
                        "received_at": now,
                    }
                except (KeyError, TypeError, ValueError):
                    log.warning("ignoring a malformed clip job: %r", clip)
            for key in jobs.get("snapshots") or []:
                self._snapshot_soon(key, now)

    def _send_frames(self, now: float) -> None:
        with self.lock:
            watched = sorted(self.watch)
        period = 1.0 / max(0.5, self.rules.live_fps)
        for key in watched:
            cam = self.cams[key]
            if now - cam.last_frame_sent_at < period - 1e-6:
                continue
            with self.lock:
                if cam.cfg.enabled:
                    frame, result = cam.frame, cam.result
                    if frame is None or result is None or frame.seq == cam.frame_sent_seq:
                        continue
                    people = list(result.people)
                else:
                    frame, people = cam.source.latest(), []
                    if frame is None or frame.seq == cam.frame_sent_seq:
                        continue
                zones = cam.zones
            jpeg, w, h = self._jpeg(
                apply_masks(frame.image, zones), FRAME_MAX_BYTES, FRAME_MAX_WIDTH
            )
            meta = {"at": iso_ms(frame.t), "w": w, "h": h, "people": [p.to_meta() for p in people]}
            self.client.frame(key, jpeg, meta)
            cam.last_frame_sent_at = now
            cam.frame_sent_seq = frame.seq
            self.counters["frames_sent"] += 1

    @staticmethod
    def _jpeg(image, max_bytes: int, max_width: int) -> tuple[bytes, int, int]:
        h, w = image.shape[:2]
        if w > max_width:
            h, w = round(h * max_width / w), max_width
        data = encode_jpeg(image, max_bytes=max_bytes, max_width=max_width, quality=80)
        return data, w, h

    def _snapshot_jpeg(self, cam: Cam) -> bytes | None:
        if cam.source.kind == "nvr" and self.nvr_snapshot is not None:
            try:
                data = self.nvr_snapshot(cam)
            except Exception as exc:  # fall back to the stream
                log.warning("%s: NVR snapshot failed: %s", cam.key, exc)
                data = None
            if data:
                import cv2
                import numpy as np

                image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if image is not None:
                    return encode_jpeg(
                        apply_masks(image, cam.zones),
                        max_bytes=SNAPSHOT_MAX_BYTES,
                        max_width=1920,
                        quality=88,
                    )
        frame = cam.source.latest()
        if frame is None:
            return None
        return encode_jpeg(
            apply_masks(frame.image, cam.zones),
            max_bytes=SNAPSHOT_MAX_BYTES,
            max_width=1920,
            quality=88,
        )

    def _send_snapshots(self, now: float) -> None:
        for cam in self.cams.values():
            if cam.snapshot_due_at is None or now < cam.snapshot_due_at:
                continue
            jpeg = self._snapshot_jpeg(cam)
            if jpeg is None:
                continue
            self.client.snapshot(cam.key, jpeg)
            cam.last_snapshot_at = now
            cam.snapshot_due_at = now + SNAPSHOT_EVERY_S
            self.counters["snapshots_sent"] += 1

    def _flush_events(self, now: float) -> None:
        if self.outbox is None:
            return
        for item_id, event, image in self.outbox.peek("event", 50):
            try:
                self.client.event(event, image)
            except (OfflineError, RevokedError):
                raise
            except DaybookError as exc:
                log.warning(
                    "Daybook refused event %s (%s); dropping it", event.get("event_id"), exc
                )
            self.outbox.delete([item_id])
            self.counters["events_sent"] += 1

    def _flush_stats(self, now: float) -> None:
        self._next["stats"] = now + STATS_FLUSH_EVERY_S
        if self.outbox is None:
            return
        while True:
            items = self.outbox.peek("stats", 2000)
            if not items:
                return
            try:
                reply = self.client.stats([body for _id, body, _blob in items])
            except (OfflineError, RevokedError):
                raise
            except DaybookError as exc:
                log.warning("Daybook refused %d stat rows (%s); dropping them", len(items), exc)
                reply = {}
            if reply.get("skipped"):
                log.info("Daybook skipped %d stat rows", len(reply["skipped"]))
            self.outbox.delete([item_id for item_id, _body, _blob in items])
            self.counters["minutes_sent"] += len(items)
            if len(items) < 2000:
                return

    # --- clip jobs ------------------------------------------------------------------------

    def clip_tick(self) -> int:
        """Answer the clip jobs whose window has passed. Returns how many were answered."""
        if self.client is None:
            return 0
        now = self.clock.time()
        with self.lock:
            due = [
                (cid, job)
                for cid, job in sorted(self.pending_clips.items())
                if now >= job["end"] + CLIP_GRACE_S
            ]
            for cid, _job in due:
                del self.pending_clips[cid]
        answered = 0
        for cid, job in due:
            try:
                clip = self._make_clip(job)
            except ClipError as exc:
                try:
                    self.client.clip_failed(cid, exc.reason, exc.detail)
                    self.counters["clips_failed"] += 1
                    answered += 1
                except DaybookError as send_exc:
                    log.warning("cannot report clip %s: %s", cid, send_exc)
                continue
            try:
                self.client.clip(cid, clip.video, clip.poster, clip.meta)
                self.counters["clips_sent"] += 1
                answered += 1
                self.events_log.appendleft(
                    {
                        "kind": "clip",
                        "phase": "ready",
                        "key": job["key"],
                        "at": iso(now),
                        "camera": self.cams[job["key"]].name,
                        "duration_s": clip.meta["duration_s"],
                    }
                )
            except DaybookError as exc:  # Daybook offers it again after 5 minutes
                log.warning("cannot upload clip %s: %s", cid, exc)
        return answered

    def _make_clip(self, job: dict) -> Clip:
        cam = self.cams.get(job["key"])
        if cam is None:
            raise ClipError("camera_offline", "this box has no such camera")
        start, end = job["start"], job["end"]
        recorder_error: ClipError | None = None
        if self.recorder is not None and self.recorder.available:
            try:
                return self.recorder.cut(cam.key, start, end)
            except ClipError as exc:
                recorder_error = exc
        if cam.source.kind == "nvr" and self.nvr_clip is not None:
            try:
                return self.nvr_clip(cam, start, end)
            except ClipError:
                raise
            except Exception as exc:
                raise ClipError("nvr_error", str(exc)[:200]) from exc
        if recorder_error is not None and recorder_error.reason == "too_old":
            raise recorder_error
        if not cam.source.online:
            raise ClipError("camera_offline", "the camera is offline")
        raise recorder_error or ClipError("not_recorded", "this camera is not recorded")

    # --- what the status page shows -------------------------------------------------------

    def status(self) -> dict:
        now = self.clock.time()
        with self.lock:
            cameras = []
            for cam in self.cams.values():
                result = cam.fresh_result(now) if cam.cfg.enabled else None
                size = cam.source.size
                cameras.append(
                    {
                        "key": cam.key,
                        "name": cam.name,
                        "source": cam.source.kind,
                        "role": cam.cfg.role,
                        "enabled": cam.cfg.enabled,
                        "online": cam.source.online,
                        "fps": cam.fps(now),
                        "fps_in": cam.source.fps_in,
                        "w": size[0] if size else None,
                        "h": size[1] if size else None,
                        "people": result.people_count if result else None,
                        "queue": result.queue if result else None,
                        "staff": result.staff if result else None,
                        "wait_s": result.wait_s if result else None,
                        "entered_today": cam.entered_today,
                        "exited_today": cam.exited_today,
                        "zones": len(cam.zones.all),
                        "watched": cam.key in self.watch,
                        "recording": bool(self.recorder and cam.key in self.recorder.wanted),
                        "error": cam.error or cam.source.error,
                        "open": cam.incidents.open_incidents(),
                    }
                )
            open_count = sum(len(c["open"]) for c in cameras)
            entrance = [c for c in cameras if c["role"] == "entrance"]
            totals = {
                "entered_today": sum(c["entered_today"] for c in (entrance or cameras)),
                "queue": sum(c["queue"] or 0 for c in cameras if c["role"] == "counter"),
                "staff": sum(c["staff"] or 0 for c in cameras if c["role"] == "counter"),
                "wait_s": max([c["wait_s"] or 0 for c in cameras] or [0]),
                "open": open_count,
            }
            client = self.client
            return {
                "version": __version__,
                "now": iso(now),
                "uptime_s": int(now - self.started_at),
                "lang": self.lang,
                "agent": self.agent_info,
                "server": {
                    "state": self.net_state,
                    "url": client.base_url if client else None,
                    "error": self.net_error,
                    "last_ok": iso(client.last_ok_at) if client and client.last_ok_at else None,
                    "queued": {
                        "stats": self.outbox.count("stats") if self.outbox else 0,
                        "events": self.outbox.count("event") if self.outbox else 0,
                    },
                    "counters": dict(self.counters),
                },
                "detector": self.detector_name,
                "encoder": self.encoder,
                "cpu": self._cpu_now(now),
                "rules": asdict(self.rules),
                "cameras": cameras,
                "totals": totals,
                "events": list(self.events_log)[:12],
            }

    def _cpu_now(self, now: float) -> int:
        """The live report samples the CPU every 5 s; without a server, the page does."""
        if self.client is None and now - self._cpu_at >= 5.0:
            self._cpu_at = now
            self._cpu_value = self.cpu.sample()
        return self._cpu_value

    def preview_jpeg(self, key: str, *, max_width: int = 960) -> bytes | None:
        cam = self.cams.get(key)
        if cam is None:
            return None
        frame = cam.source.latest()
        if frame is None:
            return None
        with self.lock:
            result = cam.fresh_result(self.clock.time()) if cam.cfg.enabled else None
            zones = cam.zones
            blur = self.rules.privacy_blur
        shift = min(1.0, max(0.0, frame.t - result.t)) if result is not None else 0.0
        image = preview(
            frame.image, result, zones, privacy_blur=blur, lang=self.lang, shift_s=shift
        )
        return encode_jpeg(image, max_bytes=700_000, max_width=max_width, quality=82)

    # --- running for real -----------------------------------------------------------------

    def start(self) -> None:
        for cam in self.cams.values():
            cam.source.start()
        loops = [
            ("analysis", self.tick, 0.05),
            ("recorder", self.record_tick, 0.5),
            ("network", self.net_tick, 1.0),
            ("clips", self.clip_tick, 1.0),
        ]
        for name, step, cap in loops:
            thread = threading.Thread(
                target=self._loop, args=(name, step, cap), name=f"koz-{name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def _loop(self, name: str, step: Callable[[], float | int | None], cap: float) -> None:
        while not self._stop.is_set():
            try:
                wait = step()
            except Exception:  # keep the service up; the next turn tries again
                log.exception("the %s loop failed", name)
                wait = 2.0
            if not isinstance(wait, float):
                wait = cap
            self._stop.wait(min(cap, max(0.01, wait)))

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=10)
        self._threads.clear()
        for cam in self.cams.values():
            cam.source.stop()
        if self.recorder is not None:
            self.recorder.close()
