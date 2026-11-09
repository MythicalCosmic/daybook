"""Lesson videos: uploads in pieces, processing with ffmpeg, cleanup (docs/PLAN-LEARNING.md §5).

**Upload.** A manager starts an upload with the file's name and size (`start_upload`), sends it
in pieces of at most `CHUNK_BYTES`, in order (`receive_chunk`: each reply says how much the
server has, so a dropped connection resumes from there), then `finish_upload` queues
`process_video` on the media worker. The pieces go into one file in the learning storage
(`uploads/<company>/<video>.part`), never served.

**Processing** (`process_video`, queue "media", one at a time): `ffprobe` must find a video
stream in an allowed container, at most three hours long; `ffmpeg` (under `nice`, two threads,
a timeout of four times the duration plus 5 minutes) makes a 720p H.264 MP4 with AAC stereo
sound and the moov atom first (it plays while it loads), without the original's metadata (a
phone video carries where it was shot); the poster is a frame at 10 % of the way, re-encoded by
`apps.core.uploads.sanitize_image`. Every external program runs from an argument list, never a
shell. The client's name and type are never trusted: the stored names are the server's.

**Cleanup** (`clean_uploads`, daily): uploads nobody finished within a day, and videos no lesson
has used for a week, go with their files.

**Sound for transcripts** (`audio_piece`, from `transcripts.py` on the ai queue): a stretch of our
own MP4's first sound stream as mono 16 kHz Opus, through the same hardened input as above.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.core.storage import learning_storage
from apps.core.uploads import InvalidUpload, sanitize_image
from apps.learning import conf
from apps.learning.audit_actions import CourseAction
from apps.learning.models import Lesson, Video
from apps.learning.services import ensure_manager
from apps.members.models import Membership

logger = logging.getLogger(__name__)

PULSE_KEY = "learning.lessons"
CHUNK_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_DURATION_SECONDS = 3 * 60 * 60
UPLOAD_TTL = timedelta(hours=24)
# A finished video no lesson took up (the editor uploads first, then saves the lesson).
ORPHAN_AFTER = timedelta(days=7)
# Signed links to a video and its poster stay valid this long (a lesson is watched in one go).
LINK_TTL = 6 * 60 * 60
MAX_HEIGHT = 720
MAX_FPS = 30
PROBE_TIMEOUT = 120
POSTER_TIMEOUT = 120
POSTER_MAX_SIDE = 1280


class OffsetMismatch(DomainError):
    """A piece that doesn't continue the upload; `received` is where it stands."""

    def __init__(self, message: str, received: int):
        super().__init__(message)
        self.received = received


class ProcessingFailed(Exception):
    """Why a video couldn't be made, in words for the owner."""


# Paths ----------------------------------------------------------------------------------


def part_name(video: Video) -> str:
    """Where the pieces of an upload are collected (learning storage, never served)."""
    return f"uploads/{video.company_id}/{video.pk}.part"


def _path(name: str) -> Path:
    return Path(learning_storage.path(name))


def _remove(name: str) -> None:
    if not name:
        return
    try:
        _path(name).unlink(missing_ok=True)
    except OSError:
        logger.warning("Couldn't delete the learning file %s", name, exc_info=True)


def remove_files(video: Video) -> None:
    """The video's stored files: the pieces, the MP4 and the poster."""
    _remove(part_name(video))
    _remove(video.file.name if video.file else "")
    _remove(video.poster.name if video.poster else "")


# Storage limit --------------------------------------------------------------------------


def used_bytes(company) -> int:
    """What the company's videos take: the kept MP4s and the uploads under way."""
    kept = (
        Video.objects.filter(company=company, state=Video.State.READY).aggregate(
            total=Sum("size_bytes")
        )["total"]
        or 0
    )
    pending = (
        Video.objects.filter(
            company=company, state__in=(Video.State.UPLOADING, Video.State.PROCESSING)
        ).aggregate(total=Sum("original_bytes"))["total"]
        or 0
    )
    return kept + pending


def limit_bytes(company) -> int:
    return conf.get_settings(company).storage_limit_mb * 1024 * 1024


def _megabytes(size: int) -> str:
    return f"{math.ceil(size / (1024 * 1024))} MB"


# Upload ---------------------------------------------------------------------------------


def ensure_on(company) -> None:
    if not conf.is_on(company):
        raise PermissionDenied(_("Training isn't switched on for this company."))


@transaction.atomic
def start_upload(company, *, by: Membership | None, name: str, size: int) -> Video:
    """A new upload of `size` bytes; the pieces follow (`receive_chunk`)."""
    ensure_on(company)
    ensure_manager(by)
    size = int(size or 0)
    if size <= 0:
        raise DomainError(_("This file is empty."))
    if size > MAX_VIDEO_BYTES:
        raise DomainError(_("A video can be at most 2 GB."))
    # One upload at a time decides the space: lock the company's settings row.
    row = conf.get_settings(company)
    type(row).objects.select_for_update().filter(pk=row.pk).first()
    used, limit = used_bytes(company), row.storage_limit_mb * 1024 * 1024
    if used + size > limit:
        raise DomainError(
            _(
                "There isn't room for this video: %(used)s of %(limit)s are used. Delete videos "
                "you don't need or raise the limit in the training settings."
            )
            % {"used": _megabytes(used), "limit": _megabytes(limit)}
        )
    video = Video.objects.create(
        company=company,
        state=Video.State.UPLOADING,
        original_name=" ".join((name or "").split())[:200],
        original_bytes=size,
        received_bytes=0,
        upload_expires_at=timezone.now() + UPLOAD_TTL,
        uploaded_by=by,
    )
    path = _path(part_name(video))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return video


def receive_chunk(video: Video, *, by: Membership | None, offset: int, data: bytes) -> Video:
    """Write one piece at `offset`. A piece may repeat the end of what arrived (its reply was
    lost), never leave a gap: `OffsetMismatch` says where to continue."""
    ensure_manager(by)
    if not data:
        raise DomainError(_("This piece is empty."))
    if len(data) > CHUNK_BYTES:
        raise DomainError(_("Send at most 8 MB at a time."))
    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=video.pk)
        if video.state != Video.State.UPLOADING:
            raise DomainError(_("This upload is finished."))
        if video.upload_expires_at is not None and video.upload_expires_at < timezone.now():
            raise DomainError(_("This upload has expired. Start it again."))
        offset = int(offset)
        if offset < 0 or offset > video.received_bytes:
            raise OffsetMismatch(
                _("Continue the upload from byte %(offset)d.") % {"offset": video.received_bytes},
                video.received_bytes,
            )
        end = offset + len(data)
        if end > video.original_bytes:
            raise DomainError(_("This is more than the size given when the upload started."))
        path = _path(part_name(video))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "r+b" if path.exists() else "w+b") as handle:
            handle.seek(offset)
            handle.write(data)
            handle.truncate(end)
        video.received_bytes = end
        video.save(update_fields=["received_bytes", "updated_at"])
    return video


@transaction.atomic
def finish_upload(video: Video, *, by: Membership | None) -> Video:
    """Every piece is in: queue the processing."""
    ensure_manager(by)
    video = Video.objects.select_for_update().get(pk=video.pk)
    if video.state != Video.State.UPLOADING:
        return video
    if video.received_bytes != video.original_bytes:
        raise DomainError(
            _("The upload isn't complete: %(received)s of %(size)s arrived.")
            % {
                "received": _megabytes(video.received_bytes),
                "size": _megabytes(video.original_bytes),
            }
        )
    video.state = Video.State.PROCESSING
    video.upload_expires_at = None
    video.save(update_fields=["state", "upload_expires_at", "updated_at"])
    audit.record(
        CourseAction.VIDEO_UPLOADED,
        company_id=video.company_id,
        actor=by.user if by is not None else None,
        target=video,
        name=video.original_name,
        size=video.original_bytes,
    )
    from apps.learning import tasks

    transaction.on_commit(lambda: tasks.process_video.delay(video.pk))
    transaction.on_commit(lambda: pulse.bump(video.company_id, PULSE_KEY))
    return video


@transaction.atomic
def delete_video(video: Video, *, by: Membership | None) -> None:
    """Delete a video no lesson uses, with its files."""
    ensure_manager(by)
    video = Video.objects.select_for_update().get(pk=video.pk)
    if Lesson.objects.filter(video=video).exists():
        raise DomainError(_("A lesson uses this video. Pick another video for it first."))
    audit.record(
        CourseAction.VIDEO_DELETED,
        company_id=video.company_id,
        actor=by.user if by is not None else None,
        target=video,
        name=video.original_name,
    )
    _drop(video)
    transaction.on_commit(lambda: pulse.bump(video.company_id, PULSE_KEY))


def _drop(video: Video) -> None:
    """Delete the row now and the files once that is committed."""
    names = [part_name(video), video.file.name or "", video.poster.name or ""]
    video.delete()

    def remove():
        for name in names:
            _remove(name)

    transaction.on_commit(remove)


# Processing -----------------------------------------------------------------------------
#
# Uploads are hostile until proven otherwise. ffmpeg picks a demuxer from a file's contents,
# and some demuxers open other files: a "video" that is really an HLS or concat playlist (or
# carries one) would have ffmpeg read local files, the worker's own environment included, into
# the MP4 the uploader then watches. So the first bytes decide the demuxer here (ISO BMFF:
# MP4, MOV, M4V, 3GP; EBML: MKV, WebM) and anything else is refused before a program reads
# it; ffprobe and ffmpeg get that demuxer explicitly, may open nothing but the local file, run
# with an empty environment, and only the first picture and sound streams reach the output.


@dataclass(frozen=True)
class Source:
    """What ffprobe found in an upload: its length and the streams to keep."""

    duration: float
    video: dict
    audio: dict | None


# A file's first bytes decide the only demuxer ffmpeg may use on it.
ISO_BOXES = {b"ftyp", b"moov", b"mdat", b"wide", b"free"}
EBML = b"\x1a\x45\xdf\xa3"
# Streams a source may carry: the picture, the sound, and data tracks (timecodes, a phone's
# motion data) that are left out. Subtitles and attached files are refused.
ALLOWED_STREAMS = {"video", "audio", "data"}
CHILD_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
# The mov demuxer never follows references to other files (its default, said out loud).
DEMUXER_OPTIONS = {"mov": ["-enable_drefs", "0"], "matroska": []}


def sniff(path: Path) -> str:
    """The demuxer for an upload from its first bytes: "mov" or "matroska". Everything else
    is refused here, before ffprobe or ffmpeg read a byte of it."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(200)
    except OSError:
        raise ProcessingFailed(_("The upload isn't complete. Upload the video again.")) from None
    if len(head) >= 8 and head[4:8] in ISO_BOXES:
        return "mov"
    if head[:4] == EBML:
        return "matroska"
    known = (
        (head[:4] == b"RIFF" and head[8:12] == b"AVI ")  # AVI
        or head[:3] == b"FLV"
        or head[:4] == b"\x30\x26\xb2\x75"  # ASF, WMV
        or head[:4] == b"\x00\x00\x01\xba"  # MPEG program stream
        or (len(head) > 188 and head[0] == 0x47 and head[188] == 0x47)  # MPEG transport stream
    )
    if known:
        raise ProcessingFailed(
            _("Videos of this type can't be used. Upload an MP4, MOV, WebM or MKV file.")
        )
    raise ProcessingFailed(_("This file isn't a video we can read."))


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise ProcessingFailed(_("Videos can't be processed on this server yet."))
    return found


def _nice() -> list[str]:
    found = shutil.which("nice")
    return [found, "-n", "10"] if found else []


def _run(args: list[str], *, timeout: float) -> subprocess.CompletedProcess:
    """Run a program from an argument list (never a shell), with an empty environment (no
    secrets to read from /proc), killed after `timeout`."""
    return subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=dict(CHILD_ENV),
    )


def _input(demuxer: str, path: Path) -> list[str]:
    """How ffprobe and ffmpeg open a file: only as a local file, with the demuxer we chose."""
    return [
        "-protocol_whitelist",
        "file",
        *DEMUXER_OPTIONS[demuxer],
        "-f",
        demuxer,
        "-i",
        f"file:{path}",
    ]


def probe_args(path: Path, demuxer: str) -> list[str]:
    return [
        _binary("ffprobe"),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        *_input(demuxer, path),
    ]


def probe(path: Path, demuxer: str) -> dict:
    """ffprobe's JSON about a file: `{"format": {...}, "streams": [...]}`."""
    try:
        result = _run(probe_args(path, demuxer), timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ProcessingFailed(_("This file isn't a video we can read.")) from None
    if result.returncode != 0:
        raise ProcessingFailed(_("This file isn't a video we can read."))
    try:
        return json.loads(result.stdout or b"{}")
    except ValueError:
        raise ProcessingFailed(_("This file isn't a video we can read.")) from None


def _rate(value: str | None) -> float:
    """ "30000/1001" → 29.97; nonsense → 0."""
    try:
        top, _slash, bottom = (value or "").partition("/")
        return float(top) / float(bottom or 1)
    except ValueError, ZeroDivisionError:
        return 0.0


def check_source(info: dict, demuxer: str) -> Source:
    """The duration and the streams to keep of a probed upload, or why it can't be used."""
    names = set((info.get("format", {}).get("format_name") or "").split(","))
    if demuxer not in names:
        raise ProcessingFailed(_("This file isn't a video we can read."))
    streams = info.get("streams") or []
    if {stream.get("codec_type") for stream in streams} - ALLOWED_STREAMS:
        raise ProcessingFailed(
            _(
                "This video carries subtitles or attached files. Export it again with just "
                "the picture and the sound."
            )
        )
    video = next(
        (
            stream
            for stream in streams
            if stream.get("codec_type") == "video"
            and not (stream.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise ProcessingFailed(_("This file has no picture, only sound."))
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    try:
        duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    except TypeError, ValueError:
        duration = 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise ProcessingFailed(_("We couldn't tell how long this video is."))
    if duration > MAX_DURATION_SECONDS:
        raise ProcessingFailed(_("A video can be at most 3 hours long."))
    return Source(duration=duration, video=video, audio=audio)


def _filters(stream: dict) -> str:
    # At most 720 px high, both sides even (H.264 in yuv420p needs it), at most 30 frames a second.
    filters = [f"scale=-2:'trunc(min({MAX_HEIGHT},ih)/2)*2'"]
    rate = _rate(stream.get("avg_frame_rate")) or _rate(stream.get("r_frame_rate"))
    if rate > MAX_FPS:
        filters.append(f"fps={MAX_FPS}")
    return ",".join(filters)


def _maps(found: Source) -> list[str]:
    """Only the chosen picture stream and the first sound stream reach the output."""
    maps = ["-map", f"0:{int(found.video['index'])}"]
    if found.audio is not None:
        maps += ["-map", f"0:{int(found.audio['index'])}"]
    return maps


def transcode_args(source: Path, target: Path, *, demuxer: str, found: Source) -> list[str]:
    return [
        *_nice(),
        _binary("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-threads",
        "2",
        *_input(demuxer, source),
        *_maps(found),
        "-vf",
        _filters(found.video),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "26",
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-ac",
        "2",
        "-threads",
        "2",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-sn",
        "-dn",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        f"file:{target}",
    ]


def transcode(source: Path, target: Path, *, demuxer: str, found: Source) -> None:
    args = transcode_args(source, target, demuxer=demuxer, found=found)
    try:
        result = _run(args, timeout=4 * found.duration + 300)
    except subprocess.TimeoutExpired:
        raise ProcessingFailed(
            _("Making the video took too long. Try a shorter or smaller file.")
        ) from None
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        logger.warning(
            "ffmpeg failed (%s): %s",
            result.returncode,
            result.stderr[-2000:].decode(errors="replace"),
        )
        raise ProcessingFailed(_("The video couldn't be converted. Export it again as MP4."))


def poster_bytes(video_path: Path, *, at: float) -> bytes | None:
    """One frame of our own MP4 as JPEG bytes (`at` seconds in, else the first frame), or
    None."""
    target = video_path.with_name(f"{video_path.stem}.poster.jpg")
    for moment in (at, 0.0):
        args = [
            *_nice(),
            _binary("ffmpeg"),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{moment:.2f}",
            *_input("mov", video_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-update",
            "1",
            "-f",
            "image2",
            f"file:{target}",
        ]
        try:
            result = _run(args, timeout=POSTER_TIMEOUT)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            data = target.read_bytes()
            target.unlink(missing_ok=True)
            return data
    target.unlink(missing_ok=True)
    return None


# Sound for transcripts ------------------------------------------------------------------

PIECE_TIMEOUT = 120


def has_sound(video_path: Path) -> bool:
    """Whether our own MP4 carries a sound stream (ProcessingFailed when it can't be read)."""
    info = probe(video_path, "mov")
    return any(stream.get("codec_type") == "audio" for stream in info.get("streams") or [])


def audio_piece_args(video_path: Path, target: Path, *, start: int, seconds: int) -> list[str]:
    """`seconds` of the MP4's first sound stream from `start`, as mono 16 kHz Opus (speech
    needs no more): no picture, subtitles, data, metadata or chapters."""
    return [
        *_nice(),
        _binary("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(int(start)),
        "-t",
        str(int(seconds)),
        *_input("mov", video_path),
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libopus",
        "-b:a",
        "24k",
        "-application",
        "voip",
        "-f",
        "ogg",
        f"file:{target}",
    ]


def audio_piece(video_path: Path, *, start: int, seconds: int) -> bytes:
    """The stretch's Ogg/Opus bytes, written in a temporary folder and read back.
    ProcessingFailed when ffmpeg can't make it."""
    with tempfile.TemporaryDirectory(prefix="learning-sound-") as folder:
        target = Path(folder) / "piece.ogg"
        try:
            result = _run(
                audio_piece_args(video_path, target, start=start, seconds=seconds),
                timeout=PIECE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise ProcessingFailed(_("This file isn't a video we can read.")) from None
        if result.returncode != 0:
            raise ProcessingFailed(_("This file isn't a video we can read."))
        return target.read_bytes() if target.exists() else b""


def process_video(video_id: int) -> str:
    """The media worker's job: the MP4 and the poster from an uploaded video. Returns what
    happened ("ready", "failed", "skipped")."""
    video = Video.objects.select_related("company").filter(pk=video_id).first()
    if video is None or video.state != Video.State.PROCESSING:
        return "skipped"
    source = _path(part_name(video))
    name = Video._meta.get_field("file").generate_filename(video, "video.mp4")
    target = _path(name)
    working = target.with_name(f"{target.stem}.working.mp4")
    try:
        if not source.exists() or source.stat().st_size != video.original_bytes:
            raise ProcessingFailed(_("The upload isn't complete. Upload the video again."))
        demuxer = sniff(source)
        found = check_source(probe(source, demuxer), demuxer)
        working.parent.mkdir(parents=True, exist_ok=True)
        transcode(source, working, demuxer=demuxer, found=found)
        made = check_source(probe(working, "mov"), "mov")
        os.replace(working, target)
        poster = poster_bytes(target, at=made.duration * 0.1)
    except ProcessingFailed as failure:
        working.unlink(missing_ok=True)
        _fail(video, failure)
        return "failed"
    except Exception:
        working.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        logger.exception("Processing video %s failed", video.pk)
        _fail(
            video, ProcessingFailed(_("The video couldn't be converted. Export it again as MP4."))
        )
        return "failed"
    with transaction.atomic():
        locked = Video.objects.select_for_update().filter(pk=video.pk).first()
        if locked is None or locked.state != Video.State.PROCESSING:
            target.unlink(missing_ok=True)  # deleted or handled while we worked
            return "skipped"
        locked.file.name = name
        if poster:
            try:
                clean = sanitize_image(poster, max_side=POSTER_MAX_SIDE)
            except InvalidUpload:
                clean = None
            if clean is not None:
                locked.poster.save(clean.name, clean, save=False)
        locked.size_bytes = target.stat().st_size
        locked.duration_seconds = max(1, round(made.duration))
        locked.width = int(made.video.get("width") or 0)
        locked.height = int(made.video.get("height") or 0)
        locked.state = Video.State.READY
        locked.error = ""
        locked.processed_at = timezone.now()
        locked.save()
        Lesson.objects.filter(video=locked).update(duration_seconds=locked.duration_seconds)
        transaction.on_commit(lambda: _remove(part_name(locked)))
        transaction.on_commit(lambda: pulse.bump(locked.company_id, PULSE_KEY))
    return "ready"


def _fail(video: Video, failure: ProcessingFailed) -> None:
    with transaction.atomic():
        locked = Video.objects.select_for_update().filter(pk=video.pk).first()
        if locked is None:
            return
        locked.state = Video.State.FAILED
        locked.error = str(failure)[:300]
        locked.processed_at = timezone.now()
        locked.save(update_fields=["state", "error", "processed_at", "updated_at"])
        transaction.on_commit(lambda: _remove(part_name(locked)))
        transaction.on_commit(lambda: pulse.bump(locked.company_id, PULSE_KEY))


def process_video_job(video_id: int) -> str:
    """`process_video` in the company's language (its failure message is for the owner)."""
    video = Video.objects.select_related("company").filter(pk=video_id).first()
    if video is None:
        return "skipped"
    if not conf.is_on(video.company):
        return "skipped"
    with translation.override(video.company.default_language):
        return process_video(video_id)


# Serving --------------------------------------------------------------------------------


def may_open_video(user, company_id: int, video_id: int) -> bool:
    """The file check `learning.video` (the MP4 and its poster): a manager of learning, or
    someone who may open a lesson with this video, at the moment the link is used."""
    from apps.learning import queries
    from apps.members.permissions import Perm

    member = (
        Membership.objects.select_related("company", "role")
        .filter(user=user, company_id=company_id, status=Membership.Status.APPROVED)
        .first()
    )
    if member is None or not conf.is_on(member.company):
        return False
    video = Video.objects.filter(company_id=company_id, pk=video_id).first()
    if video is None:
        return False
    if member.has_perm(Perm.LEARNING_MANAGE):
        return True
    return any(queries.can_open_lesson(member, lesson) for lesson in video.lessons.all())


def links(video: Video | None, *, user) -> dict | None:
    """The player's `{url, poster_url, duration_seconds, width, height}` for a ready video,
    with links signed for `user` (valid `LINK_TTL`), or None."""
    from apps.core.files import signed_url

    if video is None or video.state != Video.State.READY or not video.file:
        return None
    check = f"learning.video:{video.pk}"
    return {
        "url": signed_url(
            video.file, user=user, company_id=video.company_id, check=check, ttl=LINK_TTL
        ),
        "poster_url": signed_url(
            video.poster, user=user, company_id=video.company_id, check=check, ttl=LINK_TTL
        )
        if video.poster
        else None,
        "duration_seconds": video.duration_seconds,
        "width": video.width,
        "height": video.height,
    }


# Cleanup --------------------------------------------------------------------------------


def clean_uploads(now=None) -> int:
    """Uploads past their day and videos no lesson took up within a week. Returns how many
    videos went."""
    now = now or timezone.now()
    expired = Video.objects.filter(
        state=Video.State.UPLOADING, upload_expires_at__lt=now
    ) | Video.objects.filter(state=Video.State.UPLOADING, upload_expires_at__isnull=True)
    orphans = Video.objects.filter(
        Q(state__in=(Video.State.READY, Video.State.FAILED)),
        lessons__isnull=True,
        updated_at__lt=now - ORPHAN_AFTER,
    )
    removed = 0
    for video in list(expired.distinct()) + list(orphans.distinct()):
        with transaction.atomic():
            locked = Video.objects.select_for_update(skip_locked=True).filter(pk=video.pk).first()
            if locked is None or Lesson.objects.filter(video=locked).exists():
                continue
            if locked.state == Video.State.UPLOADING and (
                locked.upload_expires_at is not None and locked.upload_expires_at >= now
            ):
                continue
            _drop(locked)
            removed += 1
    return removed
