"""The life of a task draft after `services.start_draft` (v0.2 AI contract §1, §3, §4).

    process(draft_id)         queued → transcribing (audio) → thinking → ready | failed; the
                              Celery job `apps.ai.tasks.process_draft` runs it on the ai queue
    apply_draft(draft, by)    the drafts become tasks through `tasks.services.create_task`
    discard_draft / undo_draft / expire_stale / purge_audio

A plain module the services and the Celery jobs both use (a jobs module never imports the
services). When the draft came from a bot message ("Eshitayapman…"), that message is edited
into the draft's card at every step that changes what it should say (`refresh_card`).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from pathlib import PurePosixPath

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.ai import agents, bot_messages, conf, drafting, events, speech
from apps.ai.agents import voice_tasks
from apps.ai.models import AIDraft
from apps.core.exceptions import DomainError
from apps.core.uploads import AUDIO_CONTENT_TYPES
from apps.members.models import Membership
from apps.notifications import tasks as telegram_jobs
from apps.notifications.telegram import serialize_markup
from apps.tasks import dates
from apps.tasks import services as task_services
from apps.tasks.models import Task

logger = logging.getLogger(__name__)

# A ready draft nobody created within this long is expired.
READY_FOR = timedelta(hours=24)
# A draft still "working" after this long lost its job (a worker restart): it fails.
STUCK_AFTER = timedelta(minutes=15)
PURGE_BATCH = 500
AUTHOR_RELATIONS = (
    "created_by__user",
    "created_by__company",
    "created_by__role",
    "created_by__position",
)


@dataclass
class Applied:
    draft: AIDraft
    created: list[int]
    failed: list[dict]


def get_for_update(draft_id: int) -> AIDraft:
    return (
        AIDraft.objects.select_for_update(of=("self",))
        .select_related(*AUTHOR_RELATIONS)
        .get(pk=draft_id)
    )


# Listening and understanding ----------------------------------------------------------------


def process(draft_id: int) -> None:
    """Turn the draft's audio or text into task drafts. Idempotent: a draft that is no longer
    working is left alone. `speech.SpeechBusy` is let through, for the job to try again."""
    draft = AIDraft.objects.select_related(*AUTHOR_RELATIONS).filter(pk=draft_id).first()
    if draft is None or draft.status not in AIDraft.WORKING:
        return
    author = draft.created_by
    if author.status != Membership.Status.APPROVED or not conf.ai_on(author.company):
        _fail(draft, "ai_unavailable")
        return
    with translation.override(author.user.language):
        _process(draft, author)


def _process(draft: AIDraft, author: Membership) -> None:
    draft.started_at = draft.started_at or timezone.now()
    language = draft.language or dates.language(author.user.language)
    people = drafting.candidates(author)
    if draft.audio and not draft.transcript:
        _set_status(draft, AIDraft.Status.TRANSCRIBING)
        try:
            heard = speech.transcribe(
                _read_audio(draft),
                filename=PurePosixPath(draft.audio.name).name,
                content_type=_content_type(draft.audio.name),
                language=language,
                prompt=speech.vocabulary(
                    author.company.name, [(c.name, c.position) for c in people], language
                ),
                names=[c.first_name for c in people if not c.is_author],
                seconds=draft.audio_seconds,
            )
        except speech.SpeechBusy:
            raise
        except speech.SpeechError as exc:
            _fail(draft, exc.code)
            return
        if not heard.text.strip():
            _fail(draft, "nothing_heard")
            return
        draft.transcript = heard.text.strip()[:5000]
        draft.language = language or heard.language
        draft.transcribed_at = timezone.now()
    elif not draft.transcript:
        draft.transcript = draft.input_text
        draft.language = language
    _set_status(draft, AIDraft.Status.THINKING)
    try:
        found = drafting.understand(
            author, draft.transcript, language=draft.language, people=people
        )
    except Exception:
        logger.exception("Draft %s could not be understood", draft.pk)
        _fail(draft, "ai_unavailable")
        return
    draft.engine = found.engine
    draft.payload = {"drafts": found.drafts, "questions": found.questions}
    draft.status = AIDraft.Status.READY
    draft.finished_at = timezone.now()
    draft.save()
    events.log(
        author.company,
        voice_tasks.KEY,
        "draft_ready",
        params={"count": len(found.drafts), "author": str(author)},
        actor=author,
        subject=("draft", draft.pk),
        branch_id=author.home_branch_id,
    )
    if found.drafts and auto_create(draft):
        if apply_draft(draft, author, auto=True).created:
            return
        draft.refresh_from_db()
    refresh_card(draft)


def auto_create(draft: AIDraft) -> bool:
    """Whether the voice agent creates this draft's tasks without asking: it is switched on,
    and every draft names someone the author may give work to (or the author) and a time to
    come."""
    company = draft.company
    state = agents.state_of(company, voice_tasks.KEY)
    if not state.enabled or not agents.config_of(voice_tasks.AGENT, state).get("auto_create"):
        return False
    allowed = allowed_ids(draft.created_by)
    now = timezone.now()
    for item in draft.drafts:
        if item.get("problems") or item.get("assignee_guess"):
            return False
        if item.get("assignee_id") is not None and item["assignee_id"] not in allowed:
            return False
        due = moment(item.get("due_at"))
        if due is None or due <= now:
            return False
    return True


def allowed_ids(author: Membership) -> set[int]:
    """Whom `author` may give work to, themselves included."""
    from apps.members import departments

    return {*departments.assignable(author).values_list("pk", flat=True), author.pk}


def moment(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _set_status(draft: AIDraft, status: str) -> None:
    draft.status = status
    draft.save()


def _fail(draft: AIDraft, code: str) -> None:
    draft.status = AIDraft.Status.FAILED
    draft.error_code = code
    draft.finished_at = timezone.now()
    draft.save()
    events.log(
        draft.company,
        voice_tasks.KEY,
        "draft_failed",
        params={"author": str(draft.created_by)},
        actor=draft.created_by,
        subject=("draft", draft.pk),
        branch_id=draft.created_by.home_branch_id,
    )
    refresh_card(draft)


def fail(draft_id: int, code: str) -> None:
    """Give up on a draft that is still working (the job ran out of tries)."""
    draft = AIDraft.objects.select_related(*AUTHOR_RELATIONS).filter(pk=draft_id).first()
    if draft is not None and draft.status in AIDraft.WORKING:
        _fail(draft, code)


def _read_audio(draft: AIDraft) -> bytes:
    with draft.audio.open("rb") as file:
        return file.read()


def _content_type(name: str) -> str:
    return AUDIO_CONTENT_TYPES.get(PurePosixPath(name).suffix.lower().lstrip("."), "audio/ogg")


# Creating the tasks ---------------------------------------------------------------------------


@transaction.atomic
def apply_draft(
    draft: AIDraft,
    by: Membership,
    drafts: list[dict] | None = None,
    *,
    auto: bool = False,
    refresh: bool = True,
) -> Applied:
    """Create the draft's tasks, each through `tasks.services.create_task` (its rights checks,
    reminders, notifications and audit as usual). `drafts`, when given, replaces the stored
    ones (edited in an app). One that fails doesn't stop the others; applying twice is a no-op.
    `refresh` edits the bot card the draft came from (the bot passes False and edits it
    itself)."""
    draft = get_for_update(draft.pk)
    _ensure_author(draft, by)
    if draft.status == AIDraft.Status.APPLIED:
        return Applied(draft, list(draft.applied_ids), [])
    if draft.status != AIDraft.Status.READY:
        raise DomainError(not_ready_message(draft))
    if drafts is not None:
        draft.payload = {**(draft.payload or {}), "drafts": [_edited(item) for item in drafts]}
    items = draft.drafts[: drafting.MAX_DRAFTS]
    if not items:
        raise DomainError(_("There is nothing to create."))
    people = {
        person.pk: person
        for person in Membership.objects.for_company(by.company_id)
        .filter(pk__in=[item["assignee_id"] for item in items if item.get("assignee_id")])
        .select_related("user", "role", "company", "home_branch")
    }
    created, failed = [], []
    for index, item in enumerate(items):
        try:
            with transaction.atomic():
                task = _create(item, by, people)
        except (PermissionDenied, DomainError, ValidationError) as exc:
            failed.append({"index": index, "detail": _message(exc)})
        else:
            created.append(task.pk)
    if created:
        draft.status = AIDraft.Status.APPLIED
        draft.applied_ids = created
        draft.applied_by = by
        draft.applied_at = timezone.now()
        draft.auto_applied = auto
    draft.save()
    if created:
        events.log(
            draft.company,
            voice_tasks.KEY,
            "draft_auto_applied" if auto else "draft_applied",
            params={"count": len(created), "actor": str(by), "author": str(draft.created_by)},
            actor=by,
            subject=("draft", draft.pk),
            branch_id=by.home_branch_id,
        )
    if refresh:
        refresh_card(draft)
    return Applied(draft, created, failed)


def _create(item: dict, by: Membership, people: dict[int, Membership]) -> Task:
    assignee_id = item.get("assignee_id")
    assignee = people.get(assignee_id) if assignee_id else None
    if assignee_id and assignee is None:
        raise DomainError(_("Tasks can only go to registered members of your company."))
    return task_services.create_task(
        by=by,
        title=(item.get("title") or "").strip(),
        description=item.get("description") or "",
        assignee=assignee,
        due_at=moment(item.get("due_at")),
        priority=Task.Priority.URGENT if item.get("priority") == "urgent" else Task.Priority.NORMAL,
        proof="photo" if item.get("proof") == "photo" else "none",
        checklist=list(item.get("checklist") or []),
    )


def _edited(item: dict) -> dict:
    """A draft as an app sent it back: what the person decided, so no problems remain to
    show except those the clock or the rights bring (worked out when read)."""
    due = item.get("due_at")
    return drafting.stored_draft(
        title=str(item.get("title") or ""),
        description=str(item.get("description") or ""),
        assignee_id=item.get("assignee_id"),
        due_at=due if isinstance(due, datetime) else moment(due),
        priority=item.get("priority") or "normal",
        checklist=item.get("checklist") or [],
        proof=item.get("proof") or "none",
    )


def _message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc) or _("This task couldn't be created.")


def _ensure_author(draft: AIDraft, by: Membership) -> None:
    if draft.created_by_id != by.pk:
        raise PermissionDenied(_("Only the person who dictated this can use it."))


def not_ready_message(draft: AIDraft) -> str:
    match draft.status:
        case AIDraft.Status.DISCARDED:
            return _("This voice note was cancelled.")
        case AIDraft.Status.EXPIRED:
            return _("This voice note is too old. Send it again.")
        case AIDraft.Status.FAILED:
            return _("This voice note couldn't be understood. Send it again.")
        case _:
            return _("Still listening. Try again in a moment.")


@transaction.atomic
def discard_draft(draft: AIDraft, by: Membership, *, refresh: bool = True) -> AIDraft:
    draft = get_for_update(draft.pk)
    _ensure_author(draft, by)
    if draft.status == AIDraft.Status.APPLIED:
        raise DomainError(_("The tasks were already created."))
    if draft.status in (AIDraft.Status.DISCARDED, AIDraft.Status.EXPIRED):
        return draft
    draft.status = AIDraft.Status.DISCARDED
    draft.finished_at = draft.finished_at or timezone.now()
    draft.save()
    if refresh:
        refresh_card(draft)
    return draft


def can_undo(draft: AIDraft, now: datetime | None = None) -> bool:
    """Tasks the voice agent created by itself can be taken back for a few minutes."""
    now = now or timezone.now()
    return (
        draft.status == AIDraft.Status.APPLIED
        and draft.auto_applied
        and draft.applied_at is not None
        and now - draft.applied_at <= timedelta(minutes=voice_tasks.UNDO_MINUTES)
    )


@transaction.atomic
def undo_draft(draft: AIDraft, by: Membership, *, refresh: bool = True) -> AIDraft:
    """Cancel the tasks an automatic create made (through `tasks.services.cancel_task`)."""
    draft = get_for_update(draft.pk)
    _ensure_author(draft, by)
    if not can_undo(draft):
        raise DomainError(_("Too late to undo. Cancel the tasks one by one instead."))
    for task in Task.objects.filter(company_id=draft.company_id, pk__in=draft.applied_ids):
        if task.status in (Task.Status.DONE, Task.Status.CANCELLED):
            continue
        try:
            with transaction.atomic():
                task_services.cancel_task(task, by=by)
        except PermissionDenied, DomainError:
            logger.info("Task %s of draft %s was not cancelled on undo", task.pk, draft.pk)
    draft.status = AIDraft.Status.DISCARDED
    draft.undone_at = timezone.now()
    draft.save()
    events.log(
        draft.company,
        voice_tasks.KEY,
        "draft_undone",
        params={"actor": str(by)},
        actor=by,
        subject=("draft", draft.pk),
        branch_id=by.home_branch_id,
    )
    if refresh:
        refresh_card(draft)
    return draft


# Housekeeping --------------------------------------------------------------------------------


def expire_stale(now: datetime | None = None) -> int:
    """Ready drafts nobody used within a day expire; drafts whose job died fail."""
    now = now or timezone.now()
    changed = 0
    stale = AIDraft.objects.filter(
        status=AIDraft.Status.READY, finished_at__lt=now - READY_FOR
    ).select_related(*AUTHOR_RELATIONS)
    for draft in stale[:PURGE_BATCH]:
        draft.status = AIDraft.Status.EXPIRED
        draft.error_code = "expired"
        draft.save(update_fields=["status", "error_code", "updated_at"])
        refresh_card(draft)
        changed += 1
    stuck = AIDraft.objects.filter(
        status__in=AIDraft.WORKING, created_at__lt=now - STUCK_AFTER
    ).select_related(*AUTHOR_RELATIONS)
    for draft in stuck[:PURGE_BATCH]:
        _fail(draft, "ai_unavailable")
        changed += 1
    return changed


def purge_audio(now: datetime | None = None) -> int:
    """Delete the recordings older than each company's `voice_retention_days`; the transcript
    and the drafts stay."""
    now = now or timezone.now()
    removed = 0
    companies = AIDraft.objects.exclude(audio="").values_list("company_id", flat=True).distinct()
    for company_id in companies:
        from apps.companies.models import Company

        company = Company.objects.get(pk=company_id)
        days = conf.get_settings(company).voice_retention_days
        old = AIDraft.objects.filter(company=company, created_at__lt=now - timedelta(days=days))
        for draft in old.exclude(audio="")[:PURGE_BATCH]:
            draft.audio.delete(save=False)
            draft.audio = ""
            draft.save(update_fields=["audio", "updated_at"])
            removed += 1
    return removed


# The bot card ---------------------------------------------------------------------------------


def refresh_card(draft: AIDraft) -> None:
    """Edit the bot message the draft came from into what it should say now (after commit)."""
    if not (draft.tg_bot and draft.tg_chat_id and draft.tg_message_id):
        return
    with translation.override(draft.created_by.user.language):
        text, markup = bot_messages.draft_card(draft)
    transaction.on_commit(
        partial(
            telegram_jobs.edit_telegram_message.delay,
            draft.tg_bot,
            draft.tg_chat_id,
            draft.tg_message_id,
            text,
            serialize_markup(markup),
        )
    )
