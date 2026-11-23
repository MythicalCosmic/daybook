"""Sources: a looped file, the webcam guard, and NVR streams that stop on a wrong login."""

import logging
import subprocess
import time

import httpx

from koz_agent import sources
from koz_agent.cli import NvrLink
from koz_agent.logutil import RedactingFilter
from koz_agent.nvr import NvrClient
from koz_agent.settings import NvrSettings, Settings
from koz_agent.sources import FileSource, NvrSource, WebcamSource


class ClosedCapture:
    def isOpened(self):
        return False

    def release(self):
        pass


def test_nvr_stream_stops_for_good_after_a_wrong_login(monkeypatch):
    monkeypatch.setattr(sources, "RECONNECT_S", (0.01,))
    opens, checks = [], []
    source = NvrSource(
        "nvr:3",
        "Kassa 1",
        "rtsp://admin:x@192.0.2.1:554/Streaming/Channels/302",
        3,
        login_check=lambda: checks.append(1) or False,
    )
    monkeypatch.setattr(source, "_open", lambda: opens.append(1) or ClosedCapture())
    source.start()
    source._thread.join(timeout=5)
    assert not source._thread.is_alive()
    assert source.error == "wrong NVR login"
    assert len(opens) == sources.AUTH_CHECK_AFTER and len(checks) == 1


def test_nvr_stream_keeps_trying_when_the_nvr_is_only_unreachable(monkeypatch):
    monkeypatch.setattr(sources, "RECONNECT_S", (0.01,))
    opens = []
    source = NvrSource("nvr:3", "Kassa 1", "rtsp://u:p@192.0.2.1/x", 3, login_check=lambda: True)
    monkeypatch.setattr(source, "_open", lambda: opens.append(1) or ClosedCapture())
    source.start()
    time.sleep(0.4)
    source.stop()
    assert len(opens) > sources.AUTH_CHECK_AFTER and source.error == "cannot open the stream"


def test_nvr_link_remembers_a_wrong_login_on_disk(tmp_path):
    calls = []

    def nvr(request):
        calls.append(request.headers.get("authorization"))
        return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="x", nonce="n"'})

    settings = Settings(nvrs=[NvrSettings(host="192.0.2.1")])
    path = tmp_path / "agent.json"
    link = NvrLink(settings.nvrs[0], "wrong", settings, path)
    link.client = NvrClient("192.0.2.1", "admin", "wrong", transport=httpx.MockTransport(nvr))
    assert link.login_ok() is False
    assert Settings.load(path).nvrs[0].auth_failed_at
    assert link.login_ok() is False
    assert sum(1 for c in calls if c) == 1  # one login attempt in all


def test_a_video_file_plays_and_loops(tmp_path, h264):
    ffmpeg, _encoder = h264
    video = tmp_path / "shop.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=10",
            "-frames:v",
            "8",
            "-c:v",
            "mpeg4",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    source = FileSource("file:shop", "Shop", str(video), want_fps=20)
    source.start()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and source._seq <= 12:
        time.sleep(0.1)
    source.stop()
    frame = source.latest()
    assert frame is not None and frame.w == 320 and frame.h == 240
    assert source._seq > 12  # more frames than the file has: it looped
    assert source.describe()["source"] == "file"


def test_a_webcam_opens_nothing_unless_allowed():
    cam = WebcamSource("webcam:0", "Webcam", 0)
    cam.start()
    assert cam._thread is None and cam.error == "webcam not allowed" and cam.latest() is None


def test_log_lines_never_show_secrets(caplog):
    logger = logging.getLogger("koz-test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="koz-test"):
        logger.info("opening %s", "rtsp://admin:hunter2@192.0.2.1:554/Streaming/Channels/302")
        logger.info("token koz_%s", "z" * 40)
    text = caplog.text
    assert "hunter2" not in text and "rtsp://***@192.0.2.1" in text and "zzzz" not in text
