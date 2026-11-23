"""Picture sources behind one interface: ``nvr``, ``rtsp``, ``file``, ``webcam`` and ``sim``.

Each source reads on its own thread and keeps only the latest frame. Capture sources demux and
decode every packet (an H.264 stream cannot skip frames) but convert to BGR only at ``want_fps``,
which is most of the cost. A lost stream reconnects with a growing pause (1 s … 60 s).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable

# OpenCV's FFmpeg reads RTSP over TCP: no smeared frames from lost UDP packets.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2

from .clock import Clock, SystemClock
from .frames import Frame
from .logutil import mask_url

log = logging.getLogger(__name__)

KEY = re.compile(r"^[a-z0-9:_-]{1,64}$")
RECONNECT_S = (1, 2, 5, 10, 30, 60)
AUTH_CHECK_AFTER = 3  # failed opens before asking the NVR whether the login is still right


def slug(name: str, limit: int = 40) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    return (value or "camera")[:limit]


class Source:
    """A camera (or something that looks like one)."""

    kind = "base"

    def __init__(self, key: str, name: str, clock: Clock | None = None) -> None:
        if not KEY.match(key):
            raise ValueError(f"bad camera key {key!r}")
        self.key = key
        self.name = name
        self.clock = clock or SystemClock()
        self.channel: int | None = None
        self.error: str | None = None
        self._frame: Frame | None = None
        self._seq = 0
        self._fps_in = 0.0

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest(self) -> Frame | None:
        return self._frame

    @property
    def online(self) -> bool:
        frame = self._frame
        return frame is not None and self.clock.time() - frame.t < 10.0 and self.error is None

    @property
    def size(self) -> tuple[int, int] | None:
        frame = self._frame
        return (frame.w, frame.h) if frame is not None else None

    @property
    def fps_in(self) -> float:
        return round(self._fps_in, 1)

    def describe(self) -> dict:
        """The camera's line in the inventory (contract §5.3)."""
        size = self.size
        return {
            "key": self.key,
            "name": self.name,
            "source": self.kind,
            "channel": self.channel,
            "w": size[0] if size else None,
            "h": size[1] if size else None,
            "online": self.online,
        }

    def _publish(self, image, t: float) -> None:
        self._seq += 1
        previous = self._frame
        self._frame = Frame(image=image, t=t, seq=self._seq)
        if previous is not None and t > previous.t:
            inst = 1.0 / (t - previous.t)
            self._fps_in = inst if self._fps_in == 0 else 0.9 * self._fps_in + 0.1 * inst


class CaptureSource(Source):
    """A source read through OpenCV's FFmpeg on a thread of its own."""

    def __init__(
        self,
        key: str,
        name: str,
        target: str | int,
        *,
        clock: Clock | None = None,
        want_fps: float = 8.0,
        paced: bool = False,
    ) -> None:
        super().__init__(key, name, clock)
        self._target = target
        self.want_fps = want_fps
        self.paced = paced  # a file plays at its own speed instead of as fast as it decodes
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def display_target(self) -> str:
        return mask_url(str(self._target))

    def _open(self) -> cv2.VideoCapture:
        params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000]
        return cv2.VideoCapture(self._target, cv2.CAP_FFMPEG, params)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"source-{self.key}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _at_end(self, cap: cv2.VideoCapture) -> bool:
        """Called when a read fails; return True to keep the same capture."""
        return False

    def login_ok(self) -> bool:
        """Asked after a few failed opens: False means the login is wrong, so stop for good."""
        return True

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            cap = self._open()
            if not cap.isOpened():
                self.error = "cannot open the stream"
                log.warning("%s: cannot open %s", self.key, self.display_target)
                cap.release()
                attempt += 1
                if attempt % AUTH_CHECK_AFTER == 0 and not self.login_ok():
                    self.error = "wrong NVR login"
                    log.error("%s: wrong NVR login; not trying again", self.key)
                    return
                pause = RECONNECT_S[min(attempt - 1, len(RECONNECT_S) - 1)]
                if self._stop.wait(pause):
                    break
                continue
            log.info("%s: reading %s", self.key, self.display_target)
            attempt = 0
            fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
            frame_s = 1.0 / fps if self.paced and 1.0 <= fps <= 120.0 else 0.0
            last_retrieve = 0.0
            next_grab = time.monotonic()
            while not self._stop.is_set():
                if frame_s:
                    delay = next_grab - time.monotonic()
                    if delay > 0 and self._stop.wait(delay):
                        break
                    next_grab = max(next_grab + frame_s, time.monotonic() - frame_s)
                if not cap.grab():
                    if self._at_end(cap):
                        continue
                    self.error = "the stream stopped"
                    log.warning("%s: the stream stopped", self.key)
                    break
                now = self.clock.time()
                if now - last_retrieve < 1.0 / max(0.5, self.want_fps):
                    continue
                ok, image = cap.retrieve()
                if not ok or image is None:
                    continue
                last_retrieve = now
                self.error = None
                self._publish(image, now)
            cap.release()
            if not self._stop.is_set() and self._stop.wait(1.0):
                break


class RtspSource(CaptureSource):
    kind = "rtsp"


class NvrSource(CaptureSource):
    """One NVR channel's sub-stream (``…/Streaming/Channels/<ch>02``).

    Hikvision counts failed RTSP logins too, so after a few failed opens the login is checked
    once over ISAPI (``login_check``); a wrong login stops the stream for good."""

    kind = "nvr"

    def __init__(
        self,
        key: str,
        name: str,
        url: str,
        channel: int,
        *,
        login_check: Callable[[], bool] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(key, name, url, **kwargs)
        self.channel = channel
        self._login_check = login_check

    def login_ok(self) -> bool:
        return self._login_check() if self._login_check is not None else True


class FileSource(CaptureSource):
    """A video file, played at its own speed and looped."""

    kind = "file"

    def __init__(self, key: str, name: str, path: str, **kwargs) -> None:
        kwargs.setdefault("paced", True)
        super().__init__(key, name, path, **kwargs)

    def _at_end(self, cap: cv2.VideoCapture) -> bool:
        return bool(cap.set(cv2.CAP_PROP_POS_FRAMES, 0))


class WebcamSource(CaptureSource):
    """A local camera. Code only: it opens nothing unless created with ``allow=True``, which only
    happens when the pharmacy adds a webcam in the agent's settings."""

    kind = "webcam"

    def __init__(self, key: str, name: str, index: int, *, allow: bool = False, **kwargs) -> None:
        super().__init__(key, name, index, **kwargs)
        self.allow = allow

    def _open(self) -> cv2.VideoCapture:
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_V4L2
        return cv2.VideoCapture(int(self._target), backend)

    def start(self) -> None:
        if not self.allow:
            self.error = "webcam not allowed"
            return
        super().start()


class SimSource(Source):
    """A camera of the generated scene. ``threaded`` renders at ``render_fps`` on its own thread
    (a real run); otherwise each ``latest()`` renders the scene at the clock's time (tests)."""

    kind = "sim"

    def __init__(
        self,
        key: str,
        scene,
        *,
        clock: Clock | None = None,
        threaded: bool = True,
        render_fps: float = 10.0,
        name: str | None = None,
    ) -> None:
        from .scene import CAMERAS

        super().__init__(key, name or CAMERAS[key][1], clock)
        self.scene = scene
        self.threaded = threaded
        self.render_fps = render_fps
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _render(self) -> None:
        t = self.clock.time()
        image, truth = self.scene.frame(self.key, t)
        self._publish(image, t)
        self._frame.truth = truth  # type: ignore[union-attr]

    def start(self) -> None:
        if not self.threaded or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"source-{self.key}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        period = 1.0 / self.render_fps
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._render()
                self.error = None
            except Exception as exc:  # keep the camera alive and say why
                self.error = f"scene error: {exc}"
                log.exception("%s: scene error", self.key)
            self._stop.wait(max(0.0, period - (time.monotonic() - started)))

    def latest(self) -> Frame | None:
        if not self.threaded:
            frame = self._frame
            if frame is None or frame.t != self.clock.time():
                self._render()
        return self._frame


def make_sim_sources(
    scene_name: str,
    seed: int,
    clock: Clock,
    *,
    threaded: bool = True,
    start: float | None = None,
) -> list[SimSource]:
    """Both cameras of the generated scene, looking at one shared world that starts at
    ``start`` (default: now)."""
    from .scene import CAMERAS, Scene

    scene = Scene(scene_name, seed, float(start if start is not None else int(clock.time())))
    return [SimSource(key, scene, clock=clock, threaded=threaded) for key in CAMERAS]


SourceFactory = Callable[[], list[Source]]
