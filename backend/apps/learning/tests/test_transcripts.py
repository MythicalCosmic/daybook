"""Lesson transcripts (apps.learning.transcripts): the uploaded video's sound goes to the speech
service a piece at a time on the ai queue, and what was heard becomes the lesson's transcript."""

import subprocess
from types import SimpleNamespace

import pytest
from celery.exceptions import Retry
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files import File

from apps.ai import conf as ai_conf
from apps.ai import speech
from apps.audit.models import AuditLog
from apps.companies.models import Feature
from apps.core.storage import learning_storage
from apps.learning import media, tasks, transcripts
from apps.learning.models import Lesson, Video
from apps.learning.tests.factories import LessonFactory, VideoFactory
from apps.learning.tests.helpers_courses import make_mp4, manager, needs_ffmpeg, role, turn_on

pytestmark = pytest.mark.django_db

BASE = "/api/v1/owner/companies/{}/learning/"


@pytest.fixture(autouse=True)
def fresh_cache():
    cache.clear()
    yield
    cache.clear()


def ai_switched_on(company):
    turn_on(company, Feature.AI)
    row = ai_conf.get_settings(company)
    row.enabled = True
    row.save()


@pytest.fixture
def boss(company, member):
    ai_switched_on(company)
    return manager(company, member)


@pytest.fixture
def service(monkeypatch, settings):
    """A speech service "set up" that answers `service.answers` in turn (an exception is
    raised), else a sentence; every call is kept in `service.calls`."""
    settings.AI_SPEECH_URL = "http://stt.test/v1"
    calls, answers = [], []

    def transcribe(audio, **kwargs):
        calls.append({"audio": audio, **kwargs})
        answer = answers.pop(0) if answers else "Muzlatgich harorati ikki va sakkiz daraja orasida."
        if isinstance(answer, Exception):
            raise answer
        return speech.Transcript(answer, "uz", None)

    monkeypatch.setattr(speech, "transcribe", transcribe)
    return SimpleNamespace(calls=calls, answers=answers)


def ready_lesson(company, tmp_path, *, seconds: int = 3, sound: bool = True) -> Lesson:
    """A lesson with a ready uploaded video, the MP4 really in the learning storage."""
    source = make_mp4(tmp_path / "made.mp4", seconds=seconds, sound=sound)
    with source.open("rb") as handle:
        name = learning_storage.save(f"videos/{company.pk}/lesson.mp4", File(handle))
    video = VideoFactory(company=company, file=name, duration_seconds=seconds)
    return LessonFactory(
        company=company, source=Lesson.Source.UPLOAD, video=video, youtube_id="", transcript=""
    )


@needs_ffmpeg
def test_the_sound_is_written_down_a_piece_at_a_time_into_the_transcript(
    company, boss, service, tmp_path, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr(transcripts, "PIECE_SECONDS", 1)
    lesson = ready_lesson(company, tmp_path, seconds=3)
    service.answers.extend(["Birinchi qism.", "Ikkinchi qism.", "Uchinchi qism."])

    with django_capture_on_commit_callbacks(execute=True):
        job = transcripts.start(lesson, by=boss)
    assert job["total"] == 3

    lesson.refresh_from_db()
    assert lesson.transcript == "Birinchi qism.\n\nIkkinchi qism.\n\nUchinchi qism."
    assert len(service.calls) == 3
    for call in service.calls:
        # Ogg/Opus a few KB long, far under the 25 MB a hosted service takes.
        assert call["audio"].startswith(b"OggS")
        assert transcripts.MIN_PIECE_BYTES <= len(call["audio"]) <= transcripts.MAX_PIECE_BYTES
        assert call["content_type"] == "audio/ogg"
        assert call["language"] == company.default_language
    assert transcripts.describe(lesson)["state"] == ""
    entry = AuditLog.objects.get(action="learning.transcript_requested")
    assert entry.actor == boss.user


@needs_ffmpeg
def test_a_piece_delivered_twice_or_after_stop_adds_nothing(company, boss, service, tmp_path):
    lesson = ready_lesson(company, tmp_path, seconds=2)
    job = transcripts.start(lesson, by=boss)
    assert transcripts.run_piece(lesson.pk, job["job"], 0) == "done"
    assert transcripts.run_piece(lesson.pk, job["job"], 0) == "stale"
    assert len(service.calls) == 1

    again = transcripts.start(lesson, by=boss)
    transcripts.stop(lesson, by=boss)
    assert transcripts.run_piece(lesson.pk, again["job"], 0) == "stale"
    newer = transcripts.start(lesson, by=boss)
    assert transcripts.run_piece(lesson.pk, again["job"], 0) == "stale"
    assert transcripts.job_of(lesson.pk)["job"] == newer["job"]
    assert len(service.calls) == 1


@needs_ffmpeg
def test_a_service_loading_its_models_is_tried_again_then_the_job_fails(
    company, boss, service, tmp_path
):
    lesson = ready_lesson(company, tmp_path, seconds=2)
    lesson.transcript = "Typed by hand."
    lesson.save()
    job = transcripts.start(lesson, by=boss)
    service.answers.extend(speech.SpeechBusy("loading") for _ in range(2))

    # The task asks Celery to try the same piece again in a while...
    with pytest.raises(Retry):
        tasks.transcribe_lesson.apply(args=(lesson.pk, job["job"], 0))
    assert transcripts.describe(lesson)["state"] == "working"
    # ...and on its last try gives up.
    last = tasks.transcribe_lesson.apply(
        args=(lesson.pk, job["job"], 0), retries=tasks.TRANSCRIBE_RETRIES
    )
    assert last.get() == "failed"
    assert len(service.calls) == 2
    view = transcripts.describe(lesson)
    assert (view["state"], view["error"]) == ("failed", "speech_unavailable")
    lesson.refresh_from_db()
    assert lesson.transcript == "Typed by hand."


@needs_ffmpeg
@pytest.mark.parametrize(
    ("answer", "sound", "code"),
    [
        (speech.AudioUnreadable("bad file"), True, "audio_unreadable"),
        (speech.SpeechError("down"), True, "speech_unavailable"),
        ("", True, "nothing_heard"),
        ("never asked", False, "no_sound"),
    ],
)
def test_a_failure_keeps_its_reason_and_the_old_transcript(
    company, boss, service, tmp_path, django_capture_on_commit_callbacks, answer, sound, code
):
    lesson = ready_lesson(company, tmp_path, seconds=2, sound=sound)
    service.answers.append(answer)
    with django_capture_on_commit_callbacks(execute=True):
        transcripts.start(lesson, by=boss)
    view = transcripts.describe(lesson)
    assert (view["state"], view["error"]) == ("failed", code)
    lesson.refresh_from_db()
    assert lesson.transcript == ""
    if not sound:
        assert service.calls == []
    # Starting again forgets the failure.
    assert transcripts.start(lesson, by=boss)["state"] == "working"


def test_a_lesson_whose_video_changed_meanwhile_stops(company, boss, service):
    lesson = LessonFactory(
        company=company,
        source=Lesson.Source.UPLOAD,
        video=VideoFactory(company=company, file="videos/x.mp4"),
        youtube_id="",
    )
    job = transcripts.start(lesson, by=boss)
    lesson.video = VideoFactory(company=company, file="videos/y.mp4")
    lesson.save()
    assert transcripts.run_piece(lesson.pk, job["job"], 0) == "failed"
    assert transcripts.describe(lesson)["error"] == "no_video"
    assert service.calls == []


def test_it_starts_only_with_a_ready_video_ai_on_and_a_speech_service(
    company, boss, member, service, settings
):
    youtube = LessonFactory(company=company)
    processing = LessonFactory(
        company=company,
        source=Lesson.Source.UPLOAD,
        video=VideoFactory(company=company, state=Video.State.PROCESSING),
        youtube_id="",
    )
    long = LessonFactory(
        company=company,
        source=Lesson.Source.UPLOAD,
        video=VideoFactory(company=company, file="videos/long.mp4", duration_seconds=3601),
        youtube_id="",
    )
    ready = LessonFactory(
        company=company,
        source=Lesson.Source.UPLOAD,
        video=VideoFactory(company=company, file="videos/ready.mp4", duration_seconds=3600),
        youtube_id="",
    )
    for lesson, code in [(youtube, "no_video"), (processing, "no_video"), (long, "too_long")]:
        with pytest.raises(transcripts.Unavailable) as refused:
            transcripts.start(lesson, by=boss)
        assert refused.value.code == code
        assert transcripts.describe(lesson)["unavailable"] == code
    assert transcripts.describe(ready)["unavailable"] == ""

    settings.AI_SPEECH_URL = ""
    settings.AI_FAKE = False
    assert transcripts.unavailable(ready) == "no_speech"
    settings.AI_SPEECH_URL = "http://stt.test/v1"
    row = ai_conf.get_settings(company)
    row.enabled = False
    row.save()
    assert transcripts.unavailable(ready) == "ai_off"
    row.enabled = True
    row.save()

    first = transcripts.start(ready, by=boss)
    assert transcripts.start(ready, by=boss)["job"] == first["job"]  # a running job stays
    reader = member(company, role(company, "Training viewer", "learning.view").name)
    with pytest.raises(PermissionDenied):
        transcripts.start(ready, by=reader)
    assert AuditLog.objects.filter(action="learning.transcript_requested").count() == 1


def test_the_sound_is_cut_only_from_the_local_file_without_the_environment(tmp_path, monkeypatch):
    seen = []

    def record(args, **kwargs):
        seen.append((list(args), kwargs))
        target = next(arg for arg in args if arg.startswith("file:") and arg.endswith(".ogg"))
        with open(target.removeprefix("file:"), "wb") as handle:
            handle.write(b"OggS" + b"\x00" * 2000)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(media.subprocess, "run", record)
    monkeypatch.setattr(media, "_binary", lambda name: f"/usr/bin/{name}")
    data = media.audio_piece(tmp_path / "lesson.mp4", start=60, seconds=30)
    assert data.startswith(b"OggS")
    [(args, kwargs)] = seen
    at = args.index("-i")
    before = args[:at]
    assert before[before.index("-protocol_whitelist") + 1] == "file"
    assert before[before.index("-f") + 1] == "mov"
    assert before[before.index("-enable_drefs") + 1] == "0"
    assert (before[before.index("-ss") + 1], before[before.index("-t") + 1]) == ("60", "30")
    assert args[at + 1] == f"file:{tmp_path / 'lesson.mp4'}"
    after = args[at:]
    assert after[after.index("-map") + 1] == "0:a:0"
    assert {"-vn", "-sn", "-dn"} <= set(after)
    assert after[after.index("-map_metadata") + 1] == "-1"
    assert after[after.index("-c:a") + 1] == "libopus"
    assert after[-3:-1] == ["-f", "ogg"] and after[-1].startswith("file:")
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert "shell" not in kwargs


def url(company, rest=""):
    return BASE.format(company.pk) + rest


def test_the_owner_endpoint_starts_and_stops_it(
    company, other_company, boss, member, owner_api, settings
):
    settings.AI_SPEECH_URL = "http://stt.test/v1"
    lesson = LessonFactory(
        company=company,
        source=Lesson.Source.UPLOAD,
        video=VideoFactory(company=company, file="videos/ready.mp4", duration_seconds=95),
        youtube_id="",
    )
    api = owner_api(boss)
    shown = api.get(url(company, f"lessons/{lesson.pk}/")).json()
    assert shown["transcription"] == {
        "state": "",
        "done": 0,
        "total": 0,
        "error": "",
        "unavailable": "",
    }
    started = api.post(url(company, f"lessons/{lesson.pk}/transcribe/"))
    assert started.status_code == 200, started.content
    assert started.json()["transcription"]["state"] == "working"
    assert started.json()["transcription"]["total"] == 4
    stopped = api.delete(url(company, f"lessons/{lesson.pk}/transcribe/"))
    assert stopped.status_code == 200
    assert stopped.json()["transcription"]["state"] == ""

    youtube = LessonFactory(company=company)
    refused = api.post(url(company, f"lessons/{youtube.pk}/transcribe/"))
    assert refused.status_code == 400
    assert refused.json()["detail"] == "Upload the video first and wait until it is ready."

    reader = owner_api(member(company, role(company, "Viewer", "learning.view").name))
    assert reader.post(url(company, f"lessons/{lesson.pk}/transcribe/")).status_code == 403
    ai_switched_on(other_company)
    stranger = owner_api(manager(other_company, member))
    assert stranger.post(url(other_company, f"lessons/{lesson.pk}/transcribe/")).status_code == 404
