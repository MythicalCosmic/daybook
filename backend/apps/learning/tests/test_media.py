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


@needs_ffmpeg
def test_a_text_file_named_mp4_fails_with_a_message(
    company, boss, django_capture_on_commit_callbacks
):
    video = upload(company, boss, b"this is not a video at all\n" * 40, name="notes.mp4")
    with django_capture_on_commit_callbacks(execute=True):
        media.finish_upload(video, by=boss)
    video.refresh_from_db()
    assert video.state == Video.State.FAILED
    assert video.error == "This file isn't a video we can read."
    assert not video.file
    assert not learning_storage.exists(media.part_name(video))


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
        "streams": [{"codec_type": "video", "avg_frame_rate": "30000/1001"}],
    }
    assert media.check_source(good)[0] == 12.5
    cover = {
        "format": {"format_name": "mov,mp4,m4a", "duration": "12"},
        "streams": [
            {"codec_type": "audio"},
            {"codec_type": "video", "disposition": {"attached_pic": 1}},
        ],
    }
    with pytest.raises(media.ProcessingFailed, match="only sound"):
        media.check_source(cover)
    with pytest.raises(media.ProcessingFailed, match="type"):
        media.check_source({"format": {"format_name": "gif"}, "streams": []})
    long = {
        "format": {"format_name": "matroska,webm", "duration": str(3 * 3600 + 1)},
        "streams": [{"codec_type": "video"}],
    }
    with pytest.raises(media.ProcessingFailed, match="3 hours"):
        media.check_source(long)
    assert "fps=30" in media._filters({"avg_frame_rate": "60/1"})
    assert "fps" not in media._filters({"avg_frame_rate": "25/1"})
