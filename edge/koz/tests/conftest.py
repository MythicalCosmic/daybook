import os

import pytest

from koz_agent.recorder import ffmpeg_exe, pick_encoder

T0 = 1_795_438_800.0  # 2026-11-23T13:00:00Z


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """No test touches the real data folder (token, model, recordings)."""
    monkeypatch.setenv("KOZ_HOME", str(tmp_path / "koz-home"))
    yield


_ENCODER: list = []


def encoder_or_none():
    if not _ENCODER:
        ffmpeg = ffmpeg_exe()
        _ENCODER.append((ffmpeg, pick_encoder(ffmpeg) if ffmpeg else None))
    return _ENCODER[0]


@pytest.fixture
def h264():
    """(ffmpeg, encoder), or skip when this machine has no working H.264 encoder."""
    ffmpeg, encoder = encoder_or_none()
    if not encoder:
        pytest.skip("no H.264 encoder in this ffmpeg build")
    return ffmpeg, encoder


def pytest_report_header(config):
    ffmpeg, encoder = encoder_or_none()
    return [f"koz: ffmpeg {os.path.basename(ffmpeg) if ffmpeg else 'none'}, "
            f"H.264 encoder {encoder or 'none'}"]
