"""The recorder: segment and window maths, encoders, and a real encode and cut."""

from pathlib import Path

import numpy as np
import pytest

from koz_agent.recorder import (
    CameraRecorder,
    ClipError,
    Recorder,
    Segment,
    expired,
    frames_due,
    parse_encoders,
    parse_segment_name,
    plan_clip,
    segment_end,
    segment_name,
)

from .conftest import T0


def seg(a: float, b: float) -> Segment:
    return Segment(T0 + a, T0 + b, Path(f"{a}.ts"))


def test_segments_end_at_the_next_minute():
    assert segment_end(T0) == T0 + 60
    assert segment_end(T0 + 5.3) == T0 + 60
    assert segment_end(T0 + 59.99) == T0 + 60
    assert segment_end(T0 + 60) == T0 + 120


def test_frames_due_at_a_constant_rate():
    assert frames_due(T0, T0 - 1, 6) == 0
    assert frames_due(T0, T0, 2) == 1
    assert frames_due(T0, T0 + 0.49, 2) == 1
    assert frames_due(T0, T0 + 0.5, 2) == 2
    assert frames_due(T0, T0 + 60, 6) == 361


def test_segment_names_round_trip():
    name = segment_name(T0 + 0.25, T0 + 60)
    assert name == "1795438800250_1795438860000.ts"
    assert parse_segment_name(name) == (T0 + 0.25, T0 + 60)
    assert parse_segment_name("1795438800250.part.ts") is None


def test_plan_spans_segments_with_an_offset():
    segments = [seg(0, 60), seg(60, 120), seg(120, 150)]
    plan = plan_clip(segments, T0 + 50, T0 + 70)
    assert [s.start for s in plan.segments] == [T0, T0 + 60]
    assert plan.offset == pytest.approx(50) and plan.duration == pytest.approx(20)
    plan = plan_clip(segments, T0 + 125, T0 + 140)
    assert plan.segments == (segments[2],) and plan.offset == pytest.approx(5)


def test_plan_refuses_what_is_not_recorded():
    segments = [seg(0, 60), seg(65, 120)]
    with pytest.raises(ClipError) as caught:
        plan_clip(segments, T0 + 55, T0 + 70)  # a 5 s gap
    assert caught.value.reason == "not_recorded"
    with pytest.raises(ClipError):
        plan_clip(segments, T0 + 110, T0 + 130)  # past the end
    with pytest.raises(ClipError):
        plan_clip(segments, T0 - 30, T0 + 10)  # before the start
    with pytest.raises(ClipError) as caught:
        plan_clip(segments, T0 + 10, T0 + 20, oldest_allowed=T0 + 30)
    assert caught.value.reason == "too_old"
    with pytest.raises(ClipError):
        plan_clip(segments, T0 + 20, T0 + 20)


def test_plan_allows_small_gaps_and_caps_at_60_s():
    segments = [seg(0, 59.6), seg(60, 120), seg(120, 180)]
    plan = plan_clip(segments, T0 + 30, T0 + 150)
    assert plan.duration == pytest.approx(60) and len(plan.segments) == 2


def test_old_segments_expire():
    segments = [seg(0, 60), seg(3600, 3660), seg(7200, 7260)]
    assert expired(segments, T0 + 7230, keep_hours=1) == segments[:1]
    assert expired(segments, T0 + 7300, keep_hours=1) == segments[:2]


def test_encoders_are_read_from_ffmpeg_output():
    text = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D h264_mf              H264 via MediaFoundation (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
 V....D libopenh264          OpenH264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
"""
    names = parse_encoders(text)
    assert {"libx264", "h264_mf", "libopenh264"} <= names and "aac" not in names


def numbered_frame(i: int) -> np.ndarray:
    image = np.zeros((240, 320, 3), np.uint8)
    image[:, :] = ((i * 37) % 255, (i * 91) % 255, (i * 53) % 255)
    image[100:140, (i * 7) % 280 : (i * 7) % 280 + 40] = 255
    return image


def test_record_across_a_minute_and_cut_a_clip(tmp_path, h264):
    ffmpeg, encoder = h264
    rec = CameraRecorder("sim:counter", tmp_path / "rec", ffmpeg, encoder, fps=4.0)
    start = T0 + 52.0
    for i in range(16 * 4):  # 16 s at 4 fps: 8 s before the minute, 8 s after
        rec.push(numbered_frame(i), start + i / 4)
    rec.close()
    segments = rec.segments()
    assert len(segments) == 2
    assert segments[0].start == pytest.approx(start) and segments[0].end == pytest.approx(T0 + 60)
    assert segments[1].start == pytest.approx(T0 + 60)
    assert segments[1].end == pytest.approx(start + 16, abs=0.3)

    recorder = Recorder(tmp_path / "rec-all", None, ffmpeg=ffmpeg, encoder=encoder, fps=4.0)
    recorder.root = tmp_path  # read the segments written above

    class Clock:
        def time(self):
            return T0 + 120

    recorder.clock = Clock()
    recorder.folder = lambda _key: tmp_path / "rec"
    clip = recorder.cut("sim:counter", T0 + 56, T0 + 66)
    assert clip.meta == {"duration_s": 10.0, "source": "recorder", "w": 320, "h": 240}
    assert clip.video[4:8] == b"ftyp"
    assert 0 < clip.video.find(b"moov") < clip.video.find(b"mdat")  # faststart
    assert clip.poster[:2] == b"\xff\xd8"


def test_a_crashed_part_file_becomes_a_segment(tmp_path, h264):
    ffmpeg, encoder = h264
    folder = tmp_path / "rec"
    folder.mkdir()
    part = folder / f"{round((T0 + 10) * 1000)}.part.ts"
    part.write_bytes(b"\x47" * 188 * 10)
    import os

    os.utime(part, (T0 + 40, T0 + 40))
    rec = CameraRecorder("k", folder, ffmpeg, encoder)
    assert [(s.start, s.end) for s in rec.segments()] == [(T0 + 10, T0 + 40)]


def test_prune_keeps_record_hours(tmp_path, h264):
    ffmpeg, encoder = h264
    folder = tmp_path / "rec"
    folder.mkdir()
    for a in (0, 3600, 7200):
        (folder / segment_name(T0 + a, T0 + a + 60)).write_bytes(b"x")
    rec = CameraRecorder("k", folder, ffmpeg, encoder)
    assert rec.prune(T0 + 7230, keep_hours=1) == 1
    assert len(rec.segments()) == 2
