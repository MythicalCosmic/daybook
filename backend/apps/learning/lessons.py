"""Lessons: a video (uploaded, or a YouTube link) with notes (docs/PLAN-LEARNING.md §4.2, §5).

    lesson = lessons.create_lesson(company, by=manager, title="Sovuq zanjir", source="youtube",
                                   youtube="https://youtu.be/dQw4w9WgXcQ", topic_ids=[3])
    lessons.publish_lesson(lesson, by=manager)

Notes are rich text from the knowledge base's editor, cleaned by `apps.knowledge.sanitize`
(without pictures: those belong to pages). A lesson is a draft until published; archived
lessons are offered for nothing new, but a course that holds one keeps it (steps are
protected: a lesson a course uses is archived, never deleted).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.knowledge import sanitize, topics
from apps.learning import media
from apps.learning.audit_actions import CourseAction
from apps.learning.models import CourseStep, Lesson, Status, Video
from apps.learning.services import ensure_manager
from apps.members.models import Membership, Position

PULSE_KEY = media.PULSE_KEY
MAX_TITLE = 200
MAX_NOTES = 100_000
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
PICTURE = re.compile(r"<img\b[^>]*>")
CHANGEABLE = {
    "title",
    "emoji",
    "summary",
    "notes",
    "source",
    "video_id",
    "youtube",
    "topic_ids",
    "audience_all",
    "position_ids",
    "transcript",
}


def youtube_id(value: str) -> str:
    """The 11-character id of a YouTube video from a link (watch, youtu.be, shorts, embed,
    live) or the id itself; anything else is refused."""
    value = (value or "").strip()
    if YOUTUBE_ID.match(value):
        return value
    parts = urlsplit(value if "://" in value else f"https://{value}")
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
    found = ""
    if parts.scheme in ("http", "https"):
        if host in SHORT_HOSTS and segments:
            found = segments[0]
        elif host in YOUTUBE_HOSTS:
            if segments == ["watch"]:
                found = (parse_qs(parts.query).get("v") or [""])[0]
            elif len(segments) >= 2 and segments[0] in ("shorts", "embed", "live", "v"):
                found = segments[1]
    if YOUTUBE_ID.match(found):
        return found
    raise DomainError(_("Paste a YouTube link: a watch, youtu.be, shorts or embed address."))


def _clean_title(title: str) -> str:
    title = " ".join((title or "").split())
    if not title:
        raise DomainError(_("Give it a title."))
    if len(title) > MAX_TITLE:
        raise DomainError(_("Keep the title under %(n)d characters.") % {"n": MAX_TITLE})
    return title


def _clean_emoji(emoji: str) -> str:
    emoji = (emoji or "").strip()
    if len(emoji) > 16:
        raise DomainError(_("Pick one emoji."))
    return emoji


def clean_notes(notes: str) -> tuple[str, str]:
    """The notes as stored (cleaned HTML, no pictures) and as plain text."""
    if notes and len(notes) > MAX_NOTES:
        raise DomainError(_("These notes are too long. Put the text on a knowledge base page."))
    html = PICTURE.sub("", sanitize.clean(notes or ""))
    return html, sanitize.to_text(html)


def _video(company_id: int, video_id) -> Video | None:
    if video_id in (None, ""):
        return None
    video = Video.objects.filter(company_id=company_id, pk=int(video_id)).first()
    if video is None:
        raise DomainError(_("Pick a video of this company."))
    if video.state == Video.State.FAILED:
        raise DomainError(_("This video couldn't be processed. Upload it again."))
    return video


def _positions(company_id: int, position_ids) -> list[Position]:
    ids = {int(pk) for pk in position_ids or ()}
    found = list(Position.objects.filter(company_id=company_id, pk__in=ids))
    if len(found) != len(ids):
        raise DomainError(_("Pick positions of this company."))
    return found


def _topic_ids(company_id: int, ids, keep=()) -> list[int]:
    """Live topics of the company; topics a lesson already has may stay even when archived."""
    wanted = [int(pk) for pk in ids or ()]
    kept = set(keep)
    live = topics.live_ids(company_id, [pk for pk in wanted if pk not in kept])
    return list(dict.fromkeys([pk for pk in wanted if pk in kept or pk in live]))


def _record(action: str, lesson: Lesson, by: Membership | None, **details) -> None:
    audit.record(
        action,
        company_id=lesson.company_id,
        actor=by.user if by is not None else None,
        target=lesson,
        **details,
    )
    transaction.on_commit(lambda: pulse.bump(lesson.company_id, PULSE_KEY))


def _apply_video(lesson: Lesson, source: str, video: Video | None, youtube: str) -> None:
    if source not in Lesson.Source.values:
        raise DomainError(_("Pick an uploaded video or a YouTube link."))
    lesson.source = source
    if source == Lesson.Source.UPLOAD:
        lesson.video = video
        lesson.youtube_id = ""
        lesson.duration_seconds = (
            video.duration_seconds if video and video.state == Video.State.READY else 0
        )
    else:
        new_id = youtube_id(youtube) if youtube else ""
        if new_id != lesson.youtube_id:
            lesson.duration_seconds = 0  # the player's first report tells it
        lesson.youtube_id = new_id
        lesson.video = None


@transaction.atomic
def create_lesson(
    company,
    *,
    by: Membership | None,
    title: str,
    emoji: str = "",
    summary: str = "",
    notes: str = "",
    source: str = Lesson.Source.UPLOAD,
    video_id: int | None = None,
    youtube: str = "",
    topic_ids=(),
    audience_all: bool = True,
    position_ids=(),
    transcript: str = "",
) -> Lesson:
    media.ensure_on(company)
    ensure_manager(by)
    html, text = clean_notes(notes)
    lesson = Lesson(
        company=company,
        title=_clean_title(title),
        emoji=_clean_emoji(emoji),
        summary=" ".join((summary or "").split())[:300],
        notes=html,
        notes_text=text,
        transcript=(transcript or "").strip()[:200_000],
        audience_all=bool(audience_all),
        status=Status.DRAFT,
        created_by=by,
        updated_by=by,
    )
    _apply_video(lesson, source, _video(company.pk, video_id), youtube)
    positions = _positions(company.pk, position_ids)
    if not lesson.audience_all and not positions:
        raise DomainError(_("Pick who the lesson is for: everyone or some positions."))
    lesson.save()
    lesson.topics.set(_topic_ids(company.pk, topic_ids))
    lesson.positions.set(positions)
    _record(CourseAction.LESSON_CREATED, lesson, by, title=lesson.title)
    return lesson


@transaction.atomic
def update_lesson(lesson: Lesson, *, by: Membership | None, **changes) -> Lesson:
    """Change any of `CHANGEABLE`; a published lesson stays published."""
    ensure_manager(by)
    unknown = set(changes) - CHANGEABLE
    if unknown:
        raise ValueError(f"Can't change {sorted(unknown)} on a lesson.")
    lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
    if "title" in changes:
        lesson.title = _clean_title(changes["title"])
    if "emoji" in changes:
        lesson.emoji = _clean_emoji(changes["emoji"])
    if "summary" in changes:
        lesson.summary = " ".join((changes["summary"] or "").split())[:300]
    if "notes" in changes:
        lesson.notes, lesson.notes_text = clean_notes(changes["notes"])
    if "transcript" in changes:
        lesson.transcript = (changes["transcript"] or "").strip()[:200_000]
    if {"source", "video_id", "youtube"} & set(changes):
        source = changes.get("source", lesson.source)
        video = (
            _video(lesson.company_id, changes["video_id"])
            if "video_id" in changes
            else lesson.video
        )
        youtube = changes.get("youtube", lesson.youtube_id)
        _apply_video(lesson, source, video, youtube)
        if lesson.status == Status.PUBLISHED:
            _check_playable(lesson)
    if "audience_all" in changes:
        lesson.audience_all = bool(changes["audience_all"])
    lesson.updated_by = by
    lesson.save()
    if "topic_ids" in changes:
        keep = list(lesson.topics.values_list("pk", flat=True))
        lesson.topics.set(_topic_ids(lesson.company_id, changes["topic_ids"], keep))
    if "position_ids" in changes:
        lesson.positions.set(_positions(lesson.company_id, changes["position_ids"]))
    if not lesson.audience_all and not lesson.positions.exists():
        raise DomainError(_("Pick who the lesson is for: everyone or some positions."))
    _record(CourseAction.LESSON_CHANGED, lesson, by, changed=sorted(changes))
    return lesson


def _check_playable(lesson: Lesson) -> None:
    if lesson.source == Lesson.Source.YOUTUBE and not lesson.youtube_id:
        raise DomainError(_("Add the YouTube link first."))
    if lesson.source == Lesson.Source.UPLOAD:
        if lesson.video is None:
            raise DomainError(_("Upload the video first."))
        if lesson.video.state == Video.State.FAILED:
            raise DomainError(_("This video couldn't be processed. Upload it again."))
        if lesson.video.state == Video.State.UPLOADING:
            raise DomainError(_("Wait until the video has finished uploading."))


@transaction.atomic
def publish_lesson(lesson: Lesson, *, by: Membership | None) -> Lesson:
    """Open the lesson to its audience (a video still processing shows as such meanwhile)."""
    ensure_manager(by)
    lesson = (
        Lesson.objects.select_for_update(of=("self",)).select_related("video").get(pk=lesson.pk)
    )
    if lesson.status == Status.PUBLISHED:
        return lesson
    if lesson.status == Status.ARCHIVED:
        raise DomainError(_("This lesson is archived. Restore it first."))
    _check_playable(lesson)
    lesson.status = Status.PUBLISHED
    lesson.published_at = timezone.now()
    lesson.updated_by = by
    lesson.save(update_fields=["status", "published_at", "updated_by", "updated_at"])
    _record(CourseAction.LESSON_PUBLISHED, lesson, by)
    return lesson


@transaction.atomic
def archive_lesson(lesson: Lesson, *, by: Membership | None) -> Lesson:
    """Offer the lesson for nothing new; courses that hold it keep it."""
    ensure_manager(by)
    lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
    if lesson.status != Status.ARCHIVED:
        lesson.status = Status.ARCHIVED
        lesson.archived_at = timezone.now()
        lesson.updated_by = by
        lesson.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
        _record(CourseAction.LESSON_ARCHIVED, lesson, by)
    return lesson


@transaction.atomic
def restore_lesson(lesson: Lesson, *, by: Membership | None) -> Lesson:
    """Back as it was: published when it had been, a draft otherwise."""
    ensure_manager(by)
    lesson = Lesson.objects.select_for_update().get(pk=lesson.pk)
    if lesson.status == Status.ARCHIVED:
        lesson.status = Status.PUBLISHED if lesson.published_at else Status.DRAFT
        lesson.archived_at = None
        lesson.updated_by = by
        lesson.save(update_fields=["status", "archived_at", "updated_by", "updated_at"])
        _record(CourseAction.LESSON_CHANGED, lesson, by, changed=["status"])
    return lesson


@transaction.atomic
def delete_lesson(lesson: Lesson, *, by: Membership | None) -> None:
    """Delete a lesson no course uses (with who watched it); its video goes too when no other
    lesson has it."""
    ensure_manager(by)
    lesson = (
        Lesson.objects.select_for_update(of=("self",)).select_related("video").get(pk=lesson.pk)
    )
    if CourseStep.objects.filter(lesson=lesson).exists():
        raise DomainError(_("A course uses this lesson. Archive it instead."))
    video = lesson.video
    audit.record(
        CourseAction.LESSON_DELETED,
        company_id=lesson.company_id,
        actor=by.user if by is not None else None,
        target=lesson,
        title=lesson.title,
    )
    lesson.delete()
    if video is not None and not Lesson.objects.filter(video=video).exists():
        media._drop(video)
    transaction.on_commit(lambda: pulse.bump(lesson.company_id, PULSE_KEY))


def ready_for_watching(lesson: Lesson) -> bool:
    """Whether the lesson's video can be played now."""
    if lesson.source == Lesson.Source.YOUTUBE:
        return bool(lesson.youtube_id)
    return lesson.video is not None and lesson.video.state == Video.State.READY


def processing(lesson: Lesson) -> bool:
    return (
        lesson.source == Lesson.Source.UPLOAD
        and lesson.video is not None
        and lesson.video.state in (Video.State.UPLOADING, Video.State.PROCESSING)
    )
