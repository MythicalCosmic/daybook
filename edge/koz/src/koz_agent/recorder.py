"""The rolling recorder of ``counter`` cameras and the clips cut from it (contract §5.9–5.10).

Frames are piped raw into the ``ffmpeg`` binary that ships with ``imageio-ffmpeg`` and encoded to
H.264 in MPEG-TS segments (robust if the PC loses power). A segment starts at a frame and ends at
the next wall-clock minute, so segments are at most 60 s long; GOPs are short (one keyframe a
second). Frames arrive whenever the camera gives them and are written at a constant rate, the
latest frame repeated to fill gaps, so a segment's stream time is its wall time. Segments older
than ``record_hours`` are deleted.

The encoder is chosen by probing: ``h264_mf`` (Windows Media Foundation), then ``libopenh264``,
then ``libx264``, the first that really encodes a test picture on this machine.

A clip for ``[start, end]`` concatenates the segments that cover it, cuts the window exactly
(re-encoding ≤ 60 s) into an MP4 with ``+faststart``, and takes a poster JPEG from its middle.
"""

from __future__ import annotations

import logging
import math
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .clock import Clock

log = logging.getLogger(__name__)

PREFERRED_ENCODERS = ("h264_mf", "libopenh264", "libx264")
SEGMENT_S = 60.0
MAX_CLIP_S = 60.0
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ClipError(RuntimeError):
    """A clip that cannot be made; ``reason`` is the contract's ``failed`` value."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # no binary for this platform
        return None


def parse_encoders(text: str) -> set[str]:
    """Names of the video encoders in ``ffmpeg -encoders`` output."""
    names = set()
    for line in text.splitlines():
        match = re.match(r"^\s*V[A-Z.]{5}\s+(\S+)", line)
        if match:
            names.add(match.group(1))
    return names


def listed_encoders(ffmpeg: str) -> set[str]:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30,
        creationflags=NO_WINDOW,
    )
    return parse_encoders(result.stdout)


def encoder_args(name: str, fps: float, *, clip: bool = False) -> list[str]:
    gop = str(max(1, round(fps)))
    if name == "h264_mf":
        return ["-c:v", "h264_mf", "-pix_fmt", "nv12", "-rate_control", "quality",
                "-quality", "62" if clip else "55", "-scenario", "camera_record", "-g", gop]
    if name == "libopenh264":
        return ["-c:v", "libopenh264", "-pix_fmt", "yuv420p", "-b:v",
                "1500k" if clip else "900k", "-g", gop]
    return ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-crf",
            "25" if clip else "27", "-maxrate", "3M", "-bufsize", "6M", "-pix_fmt", "yuv420p",
            "-g", gop, "-keyint_min", gop, "-sc_threshold", "0"]


def probe_encoder(ffmpeg: str, name: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="koz-probe-") as folder:
        out = Path(folder) / "probe.ts"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               "testsrc=size=320x240:rate=5", "-frames:v", "10", "-an",
               *encoder_args(name, 5), "-f", "mpegts", str(out)]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and out.exists() and out.stat().st_size > 1000


def pick_encoder(ffmpeg: str | None) -> str | None:
    if not ffmpeg:
        return None
    try:
        listed = listed_encoders(ffmpeg)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for name in PREFERRED_ENCODERS:
        if name in listed and probe_encoder(ffmpeg, name):
            return name
    return None


# --- segments and windows -----------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Segment:
    start: float
    end: float
    path: Path

    @property
    def duration(self) -> float:
        return self.end - self.start


_NAME = re.compile(r"^(\d+)_(\d+)\.ts$")


def segment_name(start: float, end: float) -> str:
    return f"{round(start * 1000)}_{round(end * 1000)}.ts"


def parse_segment_name(name: str) -> tuple[float, float] | None:
    match = _NAME.match(name)
    if not match:
        return None
    return int(match.group(1)) / 1000.0, int(match.group(2)) / 1000.0


def segment_end(start: float, segment_s: float = SEGMENT_S) -> float:
    """A segment that starts at ``start`` ends at the next multiple of ``segment_s``."""
    return (math.floor(start / segment_s) + 1) * segment_s


def frames_due(start: float, t: float, fps: float) -> int:
    """How many frames a constant-rate stream that began at ``start`` holds by time ``t``."""
    if t < start:
        return 0
    return int(math.floor((t - start) * fps + 1e-6)) + 1


@dataclass(frozen=True)
class ClipPlan:
    segments: tuple[Segment, ...]
    offset: float  # seconds into the first segment
    duration: float


def plan_clip(
    segments: list[Segment],
    start: float,
    end: float,
    *,
    oldest_allowed: float | None = None,
    tolerance_s: float = 1.0,
    max_gap_s: float = 2.0,
) -> ClipPlan:
    """Which segments cover ``[start, end]`` and where to cut. Raises ``ClipError``."""
    if end <= start:
        raise ClipError("not_recorded", "the window is empty")
    if end - start > MAX_CLIP_S:
        end = start + MAX_CLIP_S
    if oldest_allowed is not None and start < oldest_allowed:
        raise ClipError("too_old", "older than the recorder keeps")
    chosen = sorted(s for s in segments if s.end > start and s.start < end)
    if not chosen:
        raise ClipError("not_recorded", "no recording for this time")
    if chosen[0].start > start + tolerance_s or chosen[-1].end < end - tolerance_s:
        raise ClipError("not_recorded", "the recording does not cover the whole window")
    for a, b in zip(chosen, chosen[1:], strict=False):
        if b.start - a.end > max_gap_s:
            raise ClipError("not_recorded", "the recording has a gap in this window")
    first = chosen[0]
    offset = max(0.0, start - first.start)
    duration = min(end, chosen[-1].end) - max(start, first.start)
    return ClipPlan(tuple(chosen), offset, max(0.1, duration))


def expired(segments: list[Segment], now: float, keep_hours: float) -> list[Segment]:
    cutoff = now - keep_hours * 3600.0
    return [s for s in segments if s.end < cutoff]


@dataclass
class Clip:
    video: bytes
    poster: bytes
    duration_s: float
    w: int
    h: int
    source: str = "recorder"

    @property
    def meta(self) -> dict:
        return {"duration_s": round(self.duration_s, 1), "source": self.source, "w": self.w,
                "h": self.h}


def _concat_line(path: Path) -> str:
    return "file '" + str(path).replace("\\", "/").replace("'", "'\\''") + "'\n"


def cut_clip(ffmpeg: str, encoder: str, plan: ClipPlan, *, fps: float = 8.0) -> Clip:
    with tempfile.TemporaryDirectory(prefix="koz-clip-") as folder:
        listing = Path(folder) / "list.txt"
        lines = "".join(_concat_line(s.path) for s in plan.segments)
        listing.write_text("ffconcat version 1.0\n" + lines, encoding="utf-8")
        out = Path(folder) / "clip.mp4"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
               "-i", str(listing), "-ss", f"{plan.offset:.3f}", "-t", f"{plan.duration:.3f}", "-an",
               *encoder_args(encoder, fps, clip=True), "-movflags", "+faststart", str(out)]
        _run(cmd, timeout=180)
        w, h = _probe_size(ffmpeg, out)
        poster = _poster(ffmpeg, out, plan.duration)
        return Clip(out.read_bytes(), poster, plan.duration, w, h, "recorder")


def cut_nvr_clip(ffmpeg: str, encoder: str, url: str, duration: float) -> Clip:
    """Fetch a window from the NVR's playback stream and re-encode it to H.264 (≤ 1280 px)."""
    with tempfile.TemporaryDirectory(prefix="koz-nvr-") as folder:
        out = Path(folder) / "clip.mp4"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-rtsp_transport", "tcp",
               "-i", url, "-t", f"{duration:.3f}", "-an", "-vf", "scale='min(1280,iw)':-2",
               *encoder_args(encoder, 12, clip=True), "-movflags", "+faststart", str(out)]
        _run(cmd, timeout=duration + 90)
        size = _probe_size(ffmpeg, out)
        poster = _poster(ffmpeg, out, duration)
        return Clip(out.read_bytes(), poster, duration, size[0], size[1], "nvr")


def _run(cmd: list[str], timeout: float) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise ClipError("not_recorded", "ffmpeg took too long") from exc
    if result.returncode != 0:
        from .logutil import redact

        message = redact(result.stderr.decode("utf-8", "replace").strip().splitlines()[-1:][0]
                         if result.stderr.strip() else f"exit {result.returncode}")
        raise ClipError("not_recorded", f"ffmpeg failed: {message[:200]}")


def _poster(ffmpeg: str, video: Path, duration: float) -> bytes:
    poster = video.with_name("poster.jpg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, duration / 2):.3f}",
           "-i", str(video), "-frames:v", "1", "-q:v", "4", str(poster)]
    _run(cmd, timeout=60)
    return poster.read_bytes()


def _probe_size(ffmpeg: str, video: Path) -> tuple[int, int]:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)], capture_output=True,
                            text=True, timeout=30, creationflags=NO_WINDOW)
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", result.stderr)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


# --- recording ------------------------------------------------------------------------------


class CameraRecorder:
    """Segments of one camera in ``folder``."""

    def __init__(self, key: str, folder: Path, ffmpeg: str, encoder: str, fps: float = 6.0) -> None:
        self.key = key
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = ffmpeg
        self.encoder = encoder
        self.fps = fps
        self.error: str | None = None
        self.size: tuple[int, int] | None = None
        self._proc: subprocess.Popen | None = None
        self._part: Path | None = None
        self._start = 0.0
        self._end = 0.0
        self._written = 0
        self._lock = threading.RLock()
        self._recover()

    def _recover(self) -> None:
        """A part file left by a crash becomes a segment ending at its last write."""
        for part in self.folder.glob("*.part.ts"):
            try:
                start = int(part.name.split(".", 1)[0]) / 1000.0
                end = part.stat().st_mtime
                if part.stat().st_size > 0 and end > start:
                    part.rename(part.with_name(segment_name(start, end)))
                else:
                    part.unlink()
            except (ValueError, OSError):
                continue

    @property
    def recording(self) -> bool:
        return self._proc is not None

    def segments(self) -> list[Segment]:
        found = []
        for path in self.folder.glob("*.ts"):
            parsed = parse_segment_name(path.name)
            if parsed:
                found.append(Segment(parsed[0], parsed[1], path))
        return sorted(found)

    def push(self, image: np.ndarray, t: float) -> None:
        with self._lock:
            h, w = image.shape[:2]
            if self._proc is not None and (t >= self._end or (w, h) != self.size):
                self._close()
            if self._proc is None:
                if not self._open(t, w, h):
                    return
            due = frames_due(self._start, t, self.fps)
            if due - self._written > 3 * self.fps:  # a long pause: start a new segment instead
                self._close()
                if not self._open(t, w, h):
                    return
                due = 1
            frame = np.ascontiguousarray(image)
            try:
                while self._written < due:
                    self._proc.stdin.write(frame.data)  # type: ignore[union-attr]
                    self._written += 1
            except (BrokenPipeError, OSError, ValueError) as exc:
                self.error = f"the encoder stopped: {type(exc).__name__}"
                log.warning("%s: %s", self.key, self.error)
                self._close(failed=True)
                return

    def _open(self, t: float, w: int, h: int) -> bool:
        self._start = t
        self._end = segment_end(t)
        self._written = 0
        self.size = (w, h)
        self._part = self.folder / f"{round(t * 1000)}.part.ts"
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{self.fps:g}", "-i", "-", "-an",
               *encoder_args(self.encoder, self.fps), "-f", "mpegts", str(self._part)]
        try:
            log_file = (self.folder / "ffmpeg.log").open("ab")
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                          stderr=log_file, creationflags=NO_WINDOW)
            log_file.close()
        except OSError as exc:
            self.error = f"cannot start ffmpeg: {exc}"
            self._proc = None
            return False
        self.error = None
        return True

    def _close(self, *, failed: bool = False) -> Segment | None:
        proc, part = self._proc, self._part
        self._proc, self._part = None, None
        if proc is None or part is None:
            return None
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        end = self._start + self._written / self.fps
        if failed or proc.returncode != 0 or not part.exists() or self._written == 0:
            part.unlink(missing_ok=True)
            return None
        final = part.with_name(segment_name(self._start, end))
        os.replace(part, final)
        return Segment(self._start, end, final)

    def close(self) -> None:
        with self._lock:
            self._close()

    def flush_through(self, t: float) -> None:
        """Close the open segment if it began by ``t``, so a clip can use its frames; the next
        frame starts a new one."""
        with self._lock:
            if self._proc is not None and self._start <= t:
                self._close()

    def prune(self, now: float, keep_hours: float) -> int:
        removed = 0
        for segment in expired(self.segments(), now, keep_hours):
            try:
                segment.path.unlink()
                removed += 1
            except OSError:
                pass
        return removed


class Recorder:
    """All recorded cameras. Thread-safe."""

    def __init__(self, root: Path, clock: Clock, *, ffmpeg: str | None = None,
                 encoder: str | None = None, fps: float = 6.0) -> None:
        self.root = Path(root)
        self.clock = clock
        self.ffmpeg = ffmpeg
        self.encoder = encoder
        self.fps = fps
        self.keep_hours = 24.0
        self._cameras: dict[str, CameraRecorder] = {}
        self._wanted: set[str] = set()
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.encoder)

    def folder(self, key: str) -> Path:
        return self.root / re.sub(r"[^a-z0-9_-]", "_", key)

    def set_cameras(self, keys: set[str], keep_hours: float) -> None:
        with self._lock:
            self._wanted = set(keys) if self.available else set()
            self.keep_hours = keep_hours
            for key in list(self._cameras):
                if key not in self._wanted:
                    self._cameras.pop(key).close()

    @property
    def wanted(self) -> set[str]:
        return set(self._wanted)

    def camera(self, key: str) -> CameraRecorder | None:
        with self._lock:
            if key not in self._wanted:
                return self._cameras.get(key)
            rec = self._cameras.get(key)
            if rec is None and self.available:
                rec = CameraRecorder(key, self.folder(key), self.ffmpeg, self.encoder, self.fps)
                self._cameras[key] = rec
            return rec

    def push(self, key: str, image: np.ndarray, t: float) -> None:
        if key not in self._wanted:
            return
        rec = self.camera(key)
        if rec is not None:
            rec.push(image, t)

    def segments(self, key: str) -> list[Segment]:
        folder = self.folder(key)
        if not folder.exists():
            return []
        rec = self._cameras.get(key)
        if rec is not None:
            return rec.segments()
        found = []
        for path in folder.glob("*.ts"):
            parsed = parse_segment_name(path.name)
            if parsed:
                found.append(Segment(parsed[0], parsed[1], path))
        return sorted(found)

    def covers(self, key: str, start: float, end: float) -> bool:
        rec = self._cameras.get(key)
        if rec is not None and rec.recording:
            rec.flush_through(end)
        try:
            plan_clip(self.segments(key), start, end)
            return True
        except ClipError:
            return False

    def cut(self, key: str, start: float, end: float) -> Clip:
        if not self.available:
            raise ClipError("not_recorded", "no H.264 encoder on this PC")
        rec = self._cameras.get(key)
        if rec is not None:
            rec.flush_through(end)
        oldest = self.clock.time() - self.keep_hours * 3600.0
        plan = plan_clip(self.segments(key), start, end, oldest_allowed=oldest)
        return cut_clip(self.ffmpeg, self.encoder, plan, fps=self.fps)

    def prune(self) -> int:
        now = self.clock.time()
        removed = 0
        for key in list(self._cameras):
            rec = self._cameras.get(key)
            if rec is not None:
                removed += rec.prune(now, self.keep_hours)
        return removed

    def close(self) -> None:
        with self._lock:
            for rec in self._cameras.values():
                rec.close()
            self._cameras.clear()
