"""Lesson videos (docs/PLAN-LEARNING.md §5): chunked uploads that resume, the storage limit,
processing with ffmpeg into a 720p MP4 with a poster, refusals, cleanup."""

import json
import subprocess
from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core.exceptions import DomainError
from apps.core.storage import learning_storage
from apps.learning import conf, media
from apps.learning.models import Lesson, Video
from apps.learning.tests.factories import LessonFactory
from apps.learning.tests.helpers_courses import make_mp4, manager, needs_ffmpeg, turn_on

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss(company, member):
    turn_on(company)
    return manager(company, member)


def upload(company, by, data: bytes, *, pieces: int = 3, name: str = "Sovuq zanjir.mp4") -> Video:
    video = media.start_upload(company, by=by, name=name, size=len(data))
    step = max(1, -(-len(data) // pieces))
    for offset in range(0, len(data), step):
        video = media.receive_chunk(video, by=by, offset=offset, data=data[offset : offset + step])
    return video


def probe(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True,
        check=True,
    )
    return json.loads(out.stdout)


@needs_ffmpeg
def test_an_upload_becomes_a_720p_mp4_with_a_poster(
    company, boss, tmp_path, django_capture_on_commit_callbacks
):
    source = make_mp4(tmp_path / "in.mp4", seconds=2, size="1280x960", rate=60).read_bytes()
    video = upload(company, boss, source)
    lesson = LessonFactory(company=company, source=Lesson.Source.UPLOAD, video=video, youtube_id="")
    assert video.received_bytes == len(source)

    with django_capture_on_commit_callbacks(execute=True):
        media.finish_upload(video, by=boss)

    video.refresh_from_db()
    assert video.state == Video.State.READY, video.error
    assert video.file.name.endswith(".mp4") and video.file.name.startswith(f"videos/{company.pk}/")
    assert video.poster.name.endswith(".jpg") and video.poster.name.startswith("posters/")
    assert (video.width, video.height) == (960, 720)
    assert video.duration_seconds == 2
    assert video.size_bytes == learning_storage.size(video.file.name)
    stream = next(
        s
        for s in probe(learning_storage.path(video.file.name))["streams"]
        if s["codec_type"] == "video"
    )
    assert stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
    assert media._rate(stream["avg_frame_rate"]) <= 30
    audio = [
        s
        for s in probe(learning_storage.path(video.file.name))["streams"]
        if s["codec_type"] == "audio"
    ]
    assert audio and audio[0]["codec_name"] == "aac" and audio[0]["channels"] == 2
    # The original's pieces are gone, the lessons using the video learn its length.
    assert not learning_storage.exists(media.part_name(video))
    lesson.refresh_from_db()
    assert lesson.duration_seconds == 2


@needs_ffmpeg
def test_a_small_video_keeps_its_size_and_the_client_name_is_never_used(
    company, boss, tmp_path, django_capture_on_commit_callbacks
):
    source = make_mp4(tmp_path / "in.mp4", seconds=2, size="320x240").read_bytes()
    video = upload(company, boss, source, name="../../etc/passwd.mp4")
    with django_capture_on_commit_callbacks(execute=True):
        media.finish_upload(video, by=boss)
    video.refresh_from_db()
    assert video.state == Video.State.READY
    assert (video.width, video.height) == (320, 240)
    assert "passwd" not in video.file.name and ".." not in video.file.name


def test_a_2_gb_and_one_byte_upload_is_refused(company, boss):
    with pytest.raises(DomainError, match="2 GB"):
        media.start_upload(company, by=boss, name="big.mp4", size=media.MAX_VIDEO_BYTES + 1)
    assert media.start_upload(company, by=boss, name="ok.mp4", size=media.MAX_VIDEO_BYTES)


def test_the_storage_limit_counts_kept_videos_and_uploads_under_way(company, boss):
    row = conf.get_settings(company)
    row.storage_limit_mb = 10
    row.save()
    Video.objects.create(company=company, state=Video.State.READY, size_bytes=6 * 1024 * 1024)
    media.start_upload(company, by=boss, name="a.mp4", size=3 * 1024 * 1024)  # 9 MB used
    with pytest.raises(DomainError, match="room"):
        media.start_upload(company, by=boss, name="b.mp4", size=2 * 1024 * 1024)
    # A failed video takes no room.
    Video.objects.create(company=company, state=Video.State.FAILED, original_bytes=50 * 1024**2)
    assert media.start_upload(company, by=boss, name="c.mp4", size=1024 * 1024)


def test_a_dropped_upload_resumes_from_the_servers_offset(company, boss):
    data = bytes(range(256)) * 40  # 10 240 bytes
    video = media.start_upload(company, by=boss, name="x.mp4", size=len(data))
    video = media.receive_chunk(video, by=boss, offset=0, data=data[:4000])
    # The connection dropped after the server got the piece; the client resends it: fine.
    video = media.receive_chunk(video, by=boss, offset=0, data=data[:4000])
    assert video.received_bytes == 4000
    # A piece past what arrived leaves a gap: refused with where to continue.
    with pytest.raises(media.OffsetMismatch) as refused:
        media.receive_chunk(video, by=boss, offset=8000, data=data[8000:])
    assert refused.value.received == 4000
    video = media.receive_chunk(video, by=boss, offset=4000, data=data[4000:])
    assert learning_storage.open(media.part_name(video)).read() == data
    with pytest.raises(DomainError):  # more than announced
        media.receive_chunk(video, by=boss, offset=len(data), data=b"x")
    assert media.finish_upload(video, by=boss).state == Video.State.PROCESSING


def test_pieces_are_at_most_8_mb_and_an_unfinished_upload_cant_finish(company, boss, monkeypatch):
    monkeypatch.setattr(media, "CHUNK_BYTES", 10)
    video = media.start_upload(company, by=boss, name="x.mp4", size=30)
    with pytest.raises(DomainError, match="8 MB"):
        media.receive_chunk(video, by=boss, offset=0, data=b"x" * 11)
    media.receive_chunk(video, by=boss, offset=0, data=b"x" * 10)
    with pytest.raises(DomainError, match="isn't complete"):
        media.finish_upload(video, by=boss)


def test_only_learning_managers_upload_and_only_with_the_module_on(company, other_company, member):
    turn_on(company)
    staff = member(company)
    with pytest.raises(PermissionDenied):
        media.start_upload(company, by=staff, name="x.mp4", size=10)
    boss = manager(other_company, member)
    with pytest.raises(PermissionDenied):  # learning is off there
        media.start_upload(other_company, by=boss, name="x.mp4", size=10)


def test_an_expired_upload_refuses_pieces(company, boss):
    video = media.start_upload(company, by=boss, name="x.mp4", size=10)
    Video.objects.filter(pk=video.pk).update(
        upload_expires_at=timezone.now() - timedelta(minutes=1)
    )
    with pytest.raises(DomainError, match="expired"):
        media.receive_chunk(video, by=boss, offset=0, data=b"x")


def test_cleanup_removes_stale_uploads_and_unused_videos(
    company, boss, django_capture_on_commit_callbacks
):
    stale = media.start_upload(company, by=boss, name="old.mp4", size=10)
    fresh = media.start_upload(company, by=boss, name="new.mp4", size=10)
    Video.objects.filter(pk=stale.pk).update(upload_expires_at=timezone.now() - timedelta(hours=1))
    unused = Video.objects.create(company=company, state=Video.State.READY)
    used = Video.objects.create(company=company, state=Video.State.READY)
    LessonFactory(company=company, source=Lesson.Source.UPLOAD, video=used, youtube_id="")
    week_ago = timezone.now() - timedelta(days=8)
    Video.objects.filter(pk__in=[unused.pk, used.pk]).update(updated_at=week_ago)

    with django_capture_on_commit_callbacks(execute=True):
        assert media.clean_uploads() == 2

    assert set(Video.objects.values_list("pk", flat=True)) == {fresh.pk, used.pk}
    assert not learning_storage.exists(media.part_name(stale))
    assert learning_storage.exists(media.part_name(fresh))


def test_a_video_a_lesson_uses_cant_be_deleted(company, boss, django_capture_on_commit_callbacks):
    video = media.start_upload(company, by=boss, name="x.mp4", size=10)
    lesson = LessonFactory(company=company, source=Lesson.Source.UPLOAD, video=video, youtube_id="")
    with pytest.raises(DomainError):
        media.delete_video(video, by=boss)
    lesson.delete()
    with django_capture_on_commit_callbacks(execute=True):
        media.delete_video(video, by=boss)
    assert not Video.objects.filter(pk=video.pk).exists()
    assert not learning_storage.exists(media.part_name(video))


def test_probe_rules():
    good = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.5"},
        "streams": [
            {"index": 0, "codec_type": "video", "avg_frame_rate": "30000/1001"},
            {"index": 1, "codec_type": "data"},  # a phone's timecode track: left out
            {"index": 2, "codec_type": "audio"},
        ],
    }
    found = media.check_source(good, "mov")
    assert (found.duration, found.video["index"], found.audio["index"]) == (12.5, 0, 2)
    # ffprobe must agree with what the first bytes said.
    with pytest.raises(media.ProcessingFailed, match="read"):
        media.check_source(good, "matroska")
    cover = {
        "format": {"format_name": "mov,mp4,m4a", "duration": "12"},
        "streams": [
            {"index": 0, "codec_type": "audio"},
            {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 1}},
        ],
    }
    with pytest.raises(media.ProcessingFailed, match="only sound"):
        media.check_source(cover, "mov")
    for kind in ("subtitle", "attachment"):
        extra = {
            "format": {"format_name": "matroska,webm", "duration": "12"},
            "streams": [{"index": 0, "codec_type": "video"}, {"index": 1, "codec_type": kind}],
        }
        with pytest.raises(media.ProcessingFailed, match="subtitles"):
            media.check_source(extra, "matroska")
    long = {
        "format": {"format_name": "matroska,webm", "duration": str(3 * 3600 + 1)},
        "streams": [{"index": 0, "codec_type": "video"}],
    }
    with pytest.raises(media.ProcessingFailed, match="3 hours"):
        media.check_source(long, "matroska")
    assert "fps=30" in media._filters({"avg_frame_rate": "60/1"})
    assert "fps" not in media._filters({"avg_frame_rate": "25/1"})


# Crafted uploads ------------------------------------------------------------------------

PLAYLIST = b"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:10.0,\nfile:///proc/self/environ\n"
CONCAT = b"ffconcat version 1.0\nfile '/etc/passwd'\n"
AVI = b"RIFF\x24\x00\x00\x00AVI LIST\x00\x00\x00\x00hdrlavih" + b"\x00" * 64


@pytest.fixture
def no_programs(monkeypatch):
    """Fails the test if ffprobe or ffmpeg would run."""
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError("A program ran on a file that should have been refused.")

    monkeypatch.setattr(media.subprocess, "run", refuse)
    return calls


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"this is not a video at all\n" * 40, "This file isn't a video we can read."),
        (PLAYLIST, "This file isn't a video we can read."),
        (CONCAT, "This file isn't a video we can read."),
        (b"\x00\x00\x00\x18" + b"fake" + b"\x00" * 40, "This file isn't a video we can read."),
        (AVI, "Videos of this type can't be used. Upload an MP4, MOV, WebM or MKV file."),
    ],
    ids=["text", "hls-playlist", "concat-list", "unknown-box", "avi"],
)
def test_a_crafted_upload_is_refused_before_any_program_reads_it(
    company, boss, no_programs, django_capture_on_commit_callbacks, data, message
):
    video = upload(company, boss, data, name="lesson.mp4")
    with django_capture_on_commit_callbacks(execute=True):
        media.finish_upload(video, by=boss)
    video.refresh_from_db()
    assert video.state == Video.State.FAILED
    assert video.error == message
    assert no_programs == []
    assert not learning_storage.exists(media.part_name(video))


def test_the_first_bytes_pick_the_demuxer(tmp_path):
    cases = {
        b"\x00\x00\x00\x20ftypisom": "mov",
        b"\x00\x00\x00\x20ftypqt  ": "mov",
        b"\x00\x00\x00\x08wide": "mov",
        b"\x00\x00\x10\x00mdat": "mov",
        b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81": "matroska",
    }
    for head, demuxer in cases.items():
        path = tmp_path / "x.part"
        path.write_bytes(head + b"\x00" * 32)
        assert media.sniff(path) == demuxer


def test_programs_open_only_the_local_file_with_the_chosen_demuxer(tmp_path, monkeypatch):
    seen = []

    def record(args, **kwargs):
        seen.append((list(args), kwargs))
        target = tmp_path / "out.mp4"
        target.write_bytes(b"x")
        return subprocess.CompletedProcess(args, 0, b'{"format": {}, "streams": []}', b"")

    monkeypatch.setattr(media.subprocess, "run", record)
    source = tmp_path / "in.part"
    found = media.Source(
        duration=10, video={"index": 3, "avg_frame_rate": "25/1"}, audio={"index": 5}
    )
    media.probe(source, "matroska")
    media.transcode(source, tmp_path / "out.mp4", demuxer="mov", found=found)
    probe_args, probe_kwargs = seen[0]
    ffmpeg_args, ffmpeg_kwargs = seen[1]
    for args in (probe_args, ffmpeg_args):
        at = args.index("-i")
        before = args[:at]
        assert before[before.index("-protocol_whitelist") + 1] == "file"
        assert args[at + 1].startswith("file:")
        assert "-f" in before
    assert probe_args[probe_args.index("-f") + 1] == "matroska"
    assert ffmpeg_args[ffmpeg_args.index("-f") + 1] == "mov"
    assert ffmpeg_args[ffmpeg_args.index("-enable_drefs") + 1] == "0"
    maps = [ffmpeg_args[i + 1] for i, arg in enumerate(ffmpeg_args) if arg == "-map"]
    assert maps == ["0:3", "0:5"]
    assert {"-sn", "-dn"} <= set(ffmpeg_args)
    assert ffmpeg_args[ffmpeg_args.index("-map_metadata") + 1] == "-1"
    # Nothing of the worker's environment (database password, secret key, bot tokens).
    for kwargs in (probe_kwargs, ffmpeg_kwargs):
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        assert "shell" not in kwargs


def test_no_sound_means_no_sound_map(tmp_path):
    found = media.Source(duration=5, video={"index": 0}, audio=None)
    args = media.transcode_args(tmp_path / "a", tmp_path / "b", demuxer="mov", found=found)
    assert [args[i + 1] for i, arg in enumerate(args) if arg == "-map"] == ["0:0"]
