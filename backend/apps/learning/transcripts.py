"""Transcripts of uploaded lesson videos (docs/PLAN-LEARNING.md §1, Should): what is said in a
video, written down by the speech service (`apps.ai.speech`), so questions can be written from a
lesson's notes and transcript, and so it can be searched.

A manager presses "Write down from the video" on a lesson whose uploaded video is ready
(`start`). The job runs on the `ai` queue one piece at a time (`run_piece`): ffmpeg cuts
`PIECE_SECONDS` of our own MP4's sound into mono Opus (`media.audio_piece`, about 100 KB, far
under the services' 25 MB limit), the speech service writes it down, and the next piece is queued
after it. So the voice task drafts sharing the queue never wait behind a long lesson, and no
piece outlasts the service's timeout (a CPU service needs up to 2.5 s per second of speech).
When the last piece is in, the pieces' text, a paragraph each, becomes the lesson's transcript,
replacing what was there (the editor asks first).

The job's state is in the cache (`learning:transcript:<lesson>`: job, state, video, done,
total, parts, error). "working" is refreshed with every piece, so a job whose worker died lets the
button come back after `STATE_TTL`; "failed" keeps the reason's code for a day. A piece is taken
only as the job's next one, so a task delivered twice adds nothing, and Stop wins over a piece
in flight.

The company's AI switch (`apps.ai.conf.ai_on`) and a configured speech service are required;
videos longer than an hour aren't written down. The fake service (AI_FAKE without
AI_SPEECH_URL) answers canned text, as it does for voice drafts. Neither the sound nor the text
is ever logged.
"""

from __future__ import annotations

import logging
import math
import secrets
from pathlib import Path

from django.core.cache import cache
from django.db import transaction
from django.utils.translation import gettext as _

from apps.ai import conf as ai_conf
from apps.ai import speech
from apps.audit import services as audit
from apps.companies.models import Feature
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.learning import conf, media
from apps.learning.audit_actions import CourseAction
from apps.learning.models import Lesson, Video
from apps.learning.services import ensure_manager
from apps.members.models import Membership

logger = logging.getLogger(__name__)

PULSE_KEY = media.PULSE_KEY
PIECE_SECONDS = 30
MAX_PIECE_BYTES = 25 * 1024 * 1024  # the hosted services' limit for one file
MIN_PIECE_BYTES = 1024  # less is the Ogg headers without any sound
MAX_SECONDS = 60 * 60
STATE_TTL = 60 * 60
FAILED_TTL = 24 * 60 * 60
MAX_CHARACTERS = 200_000  # as for a typed transcript (lessons.py)

WORKING = "working"
FAILED = "failed"

# Why a job can't start, or why it stopped (the editor words each).
NO_VIDEO = "no_video"
TOO_LONG = "too_long"
AI_OFF = "ai_off"
NO_SPEECH = "no_speech"
NO_SOUND = "no_sound"
NOTHING_HEARD = "nothing_heard"
UNREADABLE = "audio_unreadable"  # as apps.ai.speech.AudioUnreadable.code
SPEECH_UNAVAILABLE = "speech_unavailable"  # as apps.ai.speech.SpeechError.code


class Unavailable(DomainError):
    """The lesson's video can't be written down now; `code` says why."""

    def __init__(self, code: str):
        messages = {
            NO_VIDEO: _("Upload the video first and wait until it is ready."),
            TOO_LONG: _("Videos longer than an hour aren't written down."),
            AI_OFF: _("Turn on AI in the settings to write down videos."),
            NO_SPEECH: _("No speech service is set up on this server."),
        }
        super().__init__(messages[code])
        self.code = code


def _key(lesson_id: int) -> str:
    return f"learning:transcript:{lesson_id}"


def job_of(lesson_id: int) -> dict | None:
    return cache.get(_key(lesson_id))


def pieces(duration_seconds: int) -> int:
    return max(1, math.ceil(duration_seconds / PIECE_SECONDS))


def unavailable(lesson: Lesson) -> str:
    """ "" when the lesson's video can be written down now, else why not: `NO_VIDEO` (no
    uploaded video ready), `TOO_LONG`, `AI_OFF` (the company's AI switch) or `NO_SPEECH`."""
    video = lesson.video if lesson.video_id else None
    if (
        lesson.source != Lesson.Source.UPLOAD
        or video is None
        or video.state != Video.State.READY
        or not video.file
    ):
        return NO_VIDEO
    if video.duration_seconds > MAX_SECONDS:
        return TOO_LONG
    # Without the AI module there are no AI settings to read (reading would make the row).
    if not lesson.company.has_feature(Feature.AI) or not ai_conf.ai_on(lesson.company):
        return AI_OFF
    if speech.status() == "not_configured":
        return NO_SPEECH
    return ""


def describe(lesson: Lesson) -> dict:
    """The lesson editor's view: `{state, done, total, error, unavailable}` (state "" when no
    job is running or failed lately)."""
    job = job_of(lesson.pk) or {}
    state = job.get("state", "")
    return {
        "state": state,
        "done": int(job.get("done", 0)),
        "total": int(job.get("total", 0)),
        "error": job.get("error", "") if state == FAILED else "",
        "unavailable": unavailable(lesson),
    }


def start(lesson: Lesson, *, by: Membership | None) -> dict:
    """Start writing the lesson's video down (a running job is left alone)."""
    from apps.learning import tasks

    ensure_manager(by)
    running = job_of(lesson.pk)
    if running and running.get("state") == WORKING:
        return running
    reason = unavailable(lesson)
    if reason:
        raise Unavailable(reason)
    job = {
        "job": secrets.token_hex(8),
        "state": WORKING,
        "video": lesson.video_id,
        "done": 0,
        "total": pieces(lesson.video.duration_seconds),
        "parts": [],
        "error": "",
    }
    cache.set(_key(lesson.pk), job, STATE_TTL)
    audit.record(
        CourseAction.TRANSCRIPT_REQUESTED,
        company_id=lesson.company_id,
        actor=by.user if by is not None else None,
        target=lesson,
        video=lesson.video_id,
        pieces=job["total"],
    )
    lesson_id, job_id = lesson.pk, job["job"]
    transaction.on_commit(lambda: tasks.transcribe_lesson.delay(lesson_id, job_id, 0))
    transaction.on_commit(lambda: pulse.bump(lesson.company_id, PULSE_KEY))
    return job


def stop(lesson: Lesson, *, by: Membership | None) -> None:
    """Stop a running job (the piece in flight is dropped), or forget a failed one."""
    ensure_manager(by)
    cache.delete(_key(lesson.pk))
    transaction.on_commit(lambda: pulse.bump(lesson.company_id, PULSE_KEY))


def _current(lesson_id: int, job_id: str) -> dict | None:
    job = job_of(lesson_id)
    if not job or job.get("job") != job_id or job.get("state") != WORKING:
        return None
    return job


def _fail(lesson_id: int, job: dict, code: str) -> str:
    cache.set(_key(lesson_id), {**job, "state": FAILED, "error": code, "parts": []}, FAILED_TTL)
    return "failed"


def run_piece(lesson_id: int, job_id: str, piece: int, *, last_try: bool = False) -> str:
    """Write down one piece and queue the next: "next", "done", "failed", "stale" (stopped,
    replaced or already taken) or "busy" (the service is loading its models: try again; on the
    last try that fails the job)."""
    from apps.learning import tasks

    job = _current(lesson_id, job_id)
    if job is None or job.get("done") != piece:
        return "stale"
    lesson = Lesson.objects.select_related("company", "video").filter(pk=lesson_id).first()
    if lesson is None or not conf.is_on(lesson.company):
        cache.delete(_key(lesson_id))
        return "stale"
    reason = unavailable(lesson)
    if reason or lesson.video_id != job["video"]:
        return _fail(lesson_id, job, reason or NO_VIDEO)
    path = Path(lesson.video.file.path)
    try:
        if piece == 0 and not media.has_sound(path):
            return _fail(lesson_id, job, NO_SOUND)
        audio = media.audio_piece(path, start=piece * PIECE_SECONDS, seconds=PIECE_SECONDS)
    except media.ProcessingFailed:
        logger.warning("The sound of video %s couldn't be cut (piece %s)", job["video"], piece)
        return _fail(lesson_id, job, UNREADABLE)
    if len(audio) > MAX_PIECE_BYTES:
        return _fail(lesson_id, job, UNREADABLE)
    text = ""
    if len(audio) >= MIN_PIECE_BYTES:
        language = lesson.company.default_language
        try:
            heard = speech.transcribe(
                audio,
                filename=f"lesson-{lesson.pk}-{piece}.ogg",
                content_type="audio/ogg",
                language=language,
                prompt=speech.vocabulary(lesson.company.name, [], language),
            )
        except speech.SpeechBusy:
            if last_try:
                return _fail(lesson_id, job, SPEECH_UNAVAILABLE)
            return "busy"
        except speech.SpeechError as exc:
            return _fail(lesson_id, job, exc.code)
        text = heard.text.strip()
    # Stop, or a new job, while the service was listening wins.
    latest = _current(lesson_id, job_id)
    if latest is None or latest.get("done") != piece:
        return "stale"
    parts = [*latest.get("parts", []), text]
    done = piece + 1
    if done >= latest["total"] or len(audio) < MIN_PIECE_BYTES:
        return _finish(lesson, latest, parts)
    cache.set(_key(lesson_id), {**latest, "parts": parts, "done": done}, STATE_TTL)
    transaction.on_commit(lambda: tasks.transcribe_lesson.delay(lesson_id, job_id, done))
    return "next"


def _finish(lesson: Lesson, job: dict, parts: list[str]) -> str:
    text = "\n\n".join(part for part in parts if part)[:MAX_CHARACTERS].strip()
    if not text:
        return _fail(lesson.pk, job, NOTHING_HEARD)
    with transaction.atomic():
        locked = Lesson.objects.select_for_update(of=("self",)).filter(pk=lesson.pk).first()
        if locked is None or locked.video_id != job["video"]:
            return _fail(lesson.pk, job, NO_VIDEO)
        locked.transcript = text
        locked.save(update_fields=["transcript", "updated_at"])
        transaction.on_commit(lambda: pulse.bump(lesson.company_id, PULSE_KEY))
    cache.delete(_key(lesson.pk))
    return "done"
