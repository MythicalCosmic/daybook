"""Business logic of the AI features: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

    draft = services.start_draft(member, audio=data, seconds=14, source="bot", tg={...})
    services.apply_draft(draft, member)            # apps.ai.drafts
    services.enable_ai(company, by=owner)          # the owner's consent; default agents on
"""

from dataclasses import dataclass
from datetime import datetime, time
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai import agents, availability, conf, speech
from apps.ai import tasks as jobs
from apps.ai.agents import voice_tasks
from apps.ai.audit_actions import AIAction
from apps.ai.drafts import apply_draft, discard_draft, undo_draft
from apps.ai.models import AIDraft, AISettings
from apps.audit import services as audit
from apps.companies.models import Feature
from apps.core.exceptions import DomainError
from apps.core.uploads import InvalidUpload, accept_audio
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks import dates

__all__ = [
    "DraftRefused",
    "apply_draft",
    "disable_ai",
    "discard_draft",
    "enable_ai",
    "start_draft",
    "undo_draft",
    "update_settings",
    "voice_status",
]

TEXT_MAX = 2000
AUDIO_MAX_BYTES = 10 * 1024 * 1024


class DraftRefused(DomainError):
    """Why a draft can't be started: `code` for the apps, the message for the person."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class VoiceStatus:
    """What an app or a bot may offer the member right now (`GET ai/status/`)."""

    voice: bool
    smart_text: bool
    engine: str
    max_seconds: int
    auto_create: bool


def voice_status(member: Membership) -> VoiceStatus:
    company = member.company
    state = agents.state_of(company, voice_tasks.KEY)
    config = agents.config_of(voice_tasks.AGENT, state)
    on = conf.ai_on(company) and state.enabled
    claude = availability.status(company).available and not availability.fake()
    return VoiceStatus(
        voice=on and speech.status() != "not_configured",
        smart_text=on,
        engine="claude" if claude else "rules",
        max_seconds=int(config["max_seconds"]),
        auto_create=bool(config["auto_create"]),
    )


# Task drafts -----------------------------------------------------------------------------------


def start_draft(
    by: Membership,
    *,
    audio=None,
    seconds: float | None = None,
    text: str | None = None,
    source: str,
    tg: dict | None = None,
    language: str | None = None,
) -> AIDraft:
    """A new draft from a recording (bytes or an upload) or a typed `text`, read on the ai
    queue. `tg` = {"bot", "chat_id", "message_id"}: the bot message to edit when it is ready.
    `language` is what the person speaks (their app language when None)."""
    if source not in AIDraft.Source.values:
        raise ValueError(f"Unknown draft source {source!r}.")
    if (audio is None) == (text is None):
        raise ValueError("A draft starts from audio or from text.")
    status = voice_status(by)
    if not status.smart_text or (audio is not None and not status.voice):
        raise DraftRefused("ai_off", _("Voice tasks are switched off in this company."), 403)
    _check_daily_limit(by)
    draft = AIDraft(
        company_id=by.company_id,
        created_by=by,
        source=source,
        language=dates.language(language or by.user.language),
    )
    if text is not None:
        text = text.strip()
        if not text:
            raise DraftRefused("text_too_long", _("Write what needs to be done."))
        if len(text) > TEXT_MAX:
            raise DraftRefused(
                "text_too_long",
                _("That's too long: %(max)s characters at most.") % {"max": TEXT_MAX},
            )
        draft.input_text = text
    else:
        if seconds is not None and seconds > status.max_seconds:
            raise DraftRefused(
                "audio_too_long",
                _("The recording is too long: %(max)s seconds at most.")
                % {"max": status.max_seconds},
            )
        size = len(audio) if isinstance(audio, bytes | bytearray) else getattr(audio, "size", 0)
        if size and size > AUDIO_MAX_BYTES:
            raise DraftRefused("audio_too_big", _("The recording is too big: 10 MB at most."))
        try:
            recording = accept_audio(audio, max_bytes=AUDIO_MAX_BYTES)
        except InvalidUpload as exc:  # the size was checked above: what's left is the content
            raise DraftRefused("audio_unreadable", str(exc)) from exc
        draft.audio_seconds = round(seconds) if seconds else None
    if tg:
        draft.tg_bot = tg["bot"]
        draft.tg_chat_id = tg["chat_id"]
        draft.tg_message_id = tg["message_id"]
    with transaction.atomic():
        draft.save()
        if audio is not None:
            draft.audio.save(recording.name, recording, save=True)
        transaction.on_commit(partial(jobs.process_draft.delay, draft.pk))
    return draft


def _check_daily_limit(by: Membership) -> None:
    zone = ZoneInfo(by.company.timezone)
    today = timezone.localtime(timezone.now(), zone).date()
    since = datetime.combine(today, time.min, tzinfo=zone)
    limit = conf.get_settings(by.company).member_daily_drafts
    if AIDraft.objects.filter(created_by=by, created_at__gte=since).count() >= limit:
        raise DraftRefused(
            "limit_reached",
            _("That's all the voice tasks for today (%(limit)s). Try again tomorrow.")
            % {"limit": limit},
            429,
        )


# Settings ---------------------------------------------------------------------------------------

SETTINGS_FIELDS = frozenset(
    {
        "monthly_budget_usd",
        "share_task_text",
        "share_finance",
        "share_salaries",
        "voice_retention_days",
        "member_daily_drafts",
    }
)


def _ensure_may_configure(by: Membership) -> None:
    if not by.has_perm(Perm.AI_CONFIGURE):
        raise PermissionDenied(_("You can't change the AI settings."))


@transaction.atomic
def enable_ai(company, *, by: Membership) -> AISettings:
    """The owner's consent: AI on, the "ai" module added, and every agent that is on by default
    and can work here switched on."""
    _ensure_may_configure(by)
    row = AISettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    if row.platform_blocked:
        raise DomainError(_("AI is switched off for this company by the platform."))
    if not company.has_feature(Feature.AI):
        company.features = [*company.features, Feature.AI]
        company.save(update_fields=["features", "updated_at"])
    if not row.enabled:
        row.enabled = True
        row.enabled_by = by.user
        row.enabled_at = timezone.now()
        row.save()
        audit.record(AIAction.ENABLED, company_id=company.pk, actor=by.user, target=row)
    claude = availability.configured()
    for agent in agents.all_agents():
        if agent.default_enabled and (claude or not agent.needs_claude):
            state = agents.state_of(company, agent.key)
            if not state.enabled:
                state.enabled = True
                state.save(update_fields=["enabled", "updated_at"])
    return row


@transaction.atomic
def disable_ai(company, *, by: Membership) -> AISettings:
    _ensure_may_configure(by)
    row = AISettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    if row.enabled:
        row.enabled = False
        row.save()
        audit.record(AIAction.DISABLED, company_id=company.pk, actor=by.user, target=row)
    return row


@transaction.atomic
def update_settings(company, *, by: Membership, **changes) -> AISettings:
    _ensure_may_configure(by)
    if unknown := changes.keys() - SETTINGS_FIELDS:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    row = AISettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    before = {key: audit.plain(getattr(row, key)) for key in changes}
    for key, value in changes.items():
        setattr(row, key, value)
    row.full_clean()
    row.save()
    after = {key: audit.plain(getattr(row, key)) for key in changes}
    if changed := audit.diff(before, after):
        audit.record(
            AIAction.SETTINGS_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=row,
            changes=changed,
        )
    return row
