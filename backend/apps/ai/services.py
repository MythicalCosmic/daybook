"""Business logic of the AI features: every write, shared by the API, the bots and Celery.

Each service takes `by: Membership` (`None` means the system), audits its changes with
`apps.audit.services.record` and queues jobs with `transaction.on_commit`.

    draft = services.start_draft(member, audio=data, seconds=14, source="bot", tg={...})
    services.apply_draft(draft, member)            # apps.ai.drafts
    services.enable_ai(company, by=owner)          # the owner's consent; default agents on
    services.create_custom_agent(company, by=owner, data={...})   # an agent in their own words
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai import agents, availability, conf, speech
from apps.ai import instructions as owner_instructions
from apps.ai import tasks as jobs
from apps.ai.agents import custom, runner, voice_tasks
from apps.ai.audit_actions import AIAction
from apps.ai.drafts import apply_draft, discard_draft, undo_draft
from apps.ai.models import AgentState, AIDraft, AISettings, CustomAgent
from apps.audit import services as audit
from apps.companies.models import Feature
from apps.core.exceptions import DomainError
from apps.core.uploads import InvalidUpload, accept_audio
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.tasks import dates

__all__ = [
    "DraftRefused",
    "agent_unavailable",
    "apply_draft",
    "create_custom_agent",
    "delete_custom_agent",
    "disable_ai",
    "discard_draft",
    "enable_ai",
    "run_agent_now",
    "start_draft",
    "undo_draft",
    "update_agent",
    "update_custom_agent",
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
    switch_on_default_agents(company)
    return row


def switch_on_default_agents(company, *, new_only: bool = False) -> None:
    """Every agent that is on by default and can work here (its module on, Claude when it
    needs it) switched on; with `new_only`, only those never set up in the company yet (no
    state row): an agent added in a later release, or one whose module just came on."""
    claude = availability.configured()
    known = (
        set(AgentState.objects.filter(company=company).values_list("key", flat=True))
        if new_only
        else set()
    )
    for agent in agents.all_agents():
        if agent.key in known or not agent.default_enabled or not agent.works_in(company):
            continue
        if agent.needs_claude and not claude:
            continue
        state = agents.state_of(company, agent.key)
        if not state.enabled:
            state.enabled = True
            runner.schedule_first_run(state)
            state.save(update_fields=["enabled", "next_run_at", "updated_at"])


@transaction.atomic
def disable_ai(company, *, by: Membership) -> AISettings:
    _ensure_may_configure(by)
    row = AISettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    if row.enabled:
        row.enabled = False
        row.save()
        audit.record(AIAction.DISABLED, company_id=company.pk, actor=by.user, target=row)
    return row


def agent_unavailable(company, agent) -> str:
    """Why an agent can't work here now: "", "ai_off", "needs_claude" or "needs_speech"."""
    if not conf.ai_on(company):
        return "ai_off"
    if agent.needs_claude and not (availability.fake() or availability.status(company).available):
        return "needs_claude"
    if agent.needs_speech and speech.status() == "not_configured":
        return "needs_speech"
    return ""


@transaction.atomic
def update_agent(
    company,
    key: str,
    *,
    by: Membership,
    enabled: bool | None = None,
    config: dict | None = None,
    instructions: str | None = None,
):
    """Switch an agent on or off, change its settings (checked against its fields) and the
    owner's own instructions for its Claude calls (apps.ai.instructions; only for an agent that
    asks Claude). An agent an owner made takes no instructions (its job says what it does);
    switched back on after it paused itself, it reads with the rights of who switched it on."""
    _ensure_may_configure(by)
    agent = agents.resolve(company, key)
    if agent is None:
        raise DomainError(_("There is no such agent."))
    state = AgentState.objects.select_for_update().get(pk=agents.state_of(company, key).pk)
    before = {
        "enabled": state.enabled,
        "config": dict(state.config or {}),
        "instructions": state.instructions,
    }
    if config is not None:
        state.config = agents.clean_config(agent, config, agents.config_of(agent, state))
    if instructions is not None:
        text = instructions.strip()
        if text and not agent.prompts:
            raise DomainError(_("This agent works by fixed rules: it has no instructions."))
        if text and agent.custom is not None:
            raise DomainError(_("Change what this agent does in its job."))
        if len(text) > owner_instructions.MAX_LENGTH:
            raise DomainError(
                _("At most %(max)d characters.") % {"max": owner_instructions.MAX_LENGTH}
            )
        state.instructions = text
    if enabled is not None and enabled != state.enabled:
        if enabled and agent.needs_claude and not availability.configured():
            raise DomainError(_("This agent needs Claude: add ANTHROPIC_API_KEY on the server."))
        if enabled and agent.custom is not None:
            _resume_custom(agent.custom, by)
        state.enabled = enabled
    if state.enabled and agent.scheduled and (config is not None or not before["enabled"]):
        runner.schedule_first_run(state)
    state.save()
    after = {
        "enabled": state.enabled,
        "config": dict(state.config or {}),
        "instructions": state.instructions,
    }
    if changed := audit.diff(before, after):
        audit.record(
            AIAction.AGENT_CHANGED,
            company_id=company.pk,
            actor=by.user,
            target=state,
            agent=key,
            changes=changed,
        )
    return state


def give_an_hour(task_id: int, *, by: Membership):
    """The deadline watcher's "+1 hour": the late task's new deadline is an hour from now (on
    the next five minutes), through `tasks.services.update_task` (its rights, reminders and
    notice to the assignee). The id comes from a button and may be forged: only a task the
    tapper may see is found."""
    from apps.tasks import queries as task_queries
    from apps.tasks import services as task_services

    task = task_queries.visible_tasks(by).filter(pk=task_id).first()
    if task is None:
        raise DomainError(_("This task is no longer here."))
    later = timezone.now() + timedelta(hours=1)
    later = later.replace(second=0, microsecond=0) + timedelta(minutes=-later.minute % 5)
    return task_services.update_task(task, by=by, due_at=later)


def run_agent_now(company, key: str, *, by: Membership) -> AgentState:
    """ "Run now": the scheduled agent runs at once on the ai queue. The agents an owner made
    may do it `custom.RUN_NOW_PER_DAY` times a day in all, one run at a time each."""
    _ensure_may_configure(by)
    agent = agents.resolve(company, key)
    if agent is None or not agent.scheduled:
        raise DomainError(_("This agent works by itself when something happens."))
    if not conf.ai_on(company):
        raise DomainError(_("Turn AI on first."))
    state = agents.state_of(company, key)
    if agent.custom is not None:
        now = timezone.now()
        if state.running_since is not None and now - state.running_since < custom.RUNNING_FOR:
            raise DomainError(_("It is already at work: its report is on the way."))
        if custom.run_now_left(company, now) <= 0:
            raise DomainError(
                _("That's all the runs for today (%(limit)s). The schedule goes on as usual.")
                % {"limit": custom.RUN_NOW_PER_DAY}
            )
    AgentState.objects.filter(pk=state.pk).update(running_since=timezone.now())
    transaction.on_commit(partial(jobs.run_agent.delay, state.pk))
    return state


# The agents an owner makes in their own words (apps.ai.agents.custom) ------------------------


def _ensure_may_read_for(by: Membership) -> None:
    if not by.has_perm(Perm.AI_USE):
        raise PermissionDenied(_("You can't use AI, so an agent can't read for you."))


@transaction.atomic
def create_custom_agent(company, *, by: Membership, data: dict) -> CustomAgent:
    """A new agent in `by`'s own words, reading with their rights, switched on at its first
    time (off on a server without Claude). At most CustomAgent.MAX_LIVE live ones a company."""
    _ensure_may_configure(by)
    _ensure_may_read_for(by)
    if not conf.ai_on(company):
        raise DomainError(_("Turn AI on first."))
    # One at a time per company, so two at once can't both be the tenth.
    AISettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
    if custom.live(company).count() >= CustomAgent.MAX_LIVE:
        raise DomainError(
            _("You can have %(max)s agents of your own. Delete one to make another.")
            % {"max": CustomAgent.MAX_LIVE}
        )
    fields, people = custom.clean(company, by, data)
    row = CustomAgent.objects.create(company=company, run_as=by, created_by=by, **fields)
    row.people.set(people)
    state = AgentState.objects.create(
        company=company, key=row.key, enabled=availability.configured(), config={}
    )
    if state.enabled:
        runner.schedule_first_run(state)
        state.save(update_fields=["next_run_at", "updated_at"])
    audit.record(
        AIAction.AGENT_CREATED,
        company_id=company.pk,
        actor=by.user,
        target=row,
        agent=row.key,
        name=row.name,
    )
    return row


@transaction.atomic
def update_custom_agent(row: CustomAgent, *, by: Membership, data: dict) -> CustomAgent:
    """Change what the agent does, when, who gets it and what it may read (`data`: the fields
    that change, or the whole form). Whoever changes what it does, reads or who gets it becomes
    its owner: it reads with their rights from then on."""
    _ensure_may_configure(by)
    row = CustomAgent.objects.select_for_update().get(pk=row.pk, deleted_at__isnull=True)
    current_people = list(row.people.all())
    before = custom.snapshot(row, current_people)
    current = {
        "name": row.name,
        "job": row.job,
        "color": row.color,
        "frequency": row.frequency,
        "at": row.at,
        "weekday": row.weekday,
        "month_day": row.month_day,
        "recipients": row.recipients,
        "people": [person.pk for person in current_people],
        "group": row.group_id,
        "domains": list(row.domains),
        "template": row.template,
    }
    merged = current | {key: value for key, value in data.items() if key in current}
    reads = custom.reads_of(merged) != custom.reads_of(current)
    if reads:
        _ensure_may_read_for(by)
    fields, people = custom.clean(row.company, by, merged, reads=reads)
    fields.pop("template", None)
    schedule = (row.frequency, row.at, row.weekday, row.month_day)
    for name, value in fields.items():
        setattr(row, name, value)
    if reads:
        row.run_as = by
    row.save()
    if people is not None:
        row.people.set(people)
    after = custom.snapshot(row, people if people is not None else current_people)
    state = AgentState.objects.select_for_update().get(pk=agents.state_of(row.company, row.key).pk)
    if state.enabled and schedule != (row.frequency, row.at, row.weekday, row.month_day):
        runner.schedule_first_run(state)
        state.save(update_fields=["next_run_at", "updated_at"])
    if changed := audit.diff(before, after):
        audit.record(
            AIAction.AGENT_CHANGED,
            company_id=row.company_id,
            actor=by.user,
            target=row,
            agent=row.key,
            changes=changed,
        )
    return row


@transaction.atomic
def delete_custom_agent(row: CustomAgent, *, by: Membership) -> None:
    """Gone from the list and its page, and it never runs again; its runs and what it did stay
    in the activity."""
    _ensure_may_configure(by)
    row = CustomAgent.objects.select_for_update().get(pk=row.pk)
    if row.deleted_at is not None:
        return
    row.deleted_at = timezone.now()
    row.save(update_fields=["deleted_at", "updated_at"])
    AgentState.objects.filter(company_id=row.company_id, key=row.key).update(
        enabled=False, next_run_at=None, running_since=None
    )
    audit.record(
        AIAction.AGENT_DELETED,
        company_id=row.company_id,
        actor=by.user,
        target=row,
        agent=row.key,
        name=row.name,
    )


def _resume_custom(row: CustomAgent, by: Membership) -> None:
    """A custom agent switched back on: when it paused itself (its owner left or lost the
    right to use AI), `by` becomes its owner and it reads with their rights."""
    if not row.paused_reason and not custom.why_paused(row.run_as):
        return
    _ensure_may_read_for(by)
    before = row.run_as_id
    CustomAgent.objects.filter(pk=row.pk).update(run_as=by, paused_reason="")
    row.run_as, row.paused_reason = by, ""
    if before != by.pk:
        audit.record(
            AIAction.AGENT_CHANGED,
            company_id=row.company_id,
            actor=by.user,
            target=row,
            agent=row.key,
            changes={"run_as": [before, by.pk]},
        )


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
