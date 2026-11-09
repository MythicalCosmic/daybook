"""Models of the AI features (docs/PLAN-OWNER.md §3.14, narrowed by the v0.2 AI contract).

AISettings   the owner's consent, the budget, the data switches and limits (lazy, 1-1 Company)
AIDraft      a voice note or typed instruction on its way to tasks, and what became of it
AIUsage      one Claude call: tokens and money, never content
AgentState   one agent of a company: on/off, its settings, when it ran
AgentEvent   what an agent did, worded at read time in the reader's language
CustomAgent  an agent an owner made in their own words (apps.ai.agents.custom)
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, TenantModel
from apps.core.models import TimeStampedModel
from apps.core.storage import private_storage, private_upload_to


class AISettings(TimeStampedModel):
    """A company's AI switch and limits. AI runs only when an owner turned it on (`enabled`),
    "ai" is in `Company.features` and the platform hasn't blocked the company."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="ai_settings")
    enabled = models.BooleanField(default=False, help_text=_("An owner turned AI on."))
    enabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    enabled_at = models.DateTimeField(null=True, blank=True)
    platform_blocked = models.BooleanField(
        default=False, help_text=_("The platform switched AI off for this company.")
    )
    monthly_budget_usd = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("20"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    share_task_text = models.BooleanField(default=True)
    share_finance = models.BooleanField(default=True)
    share_salaries = models.BooleanField(default=False)
    voice_retention_days = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    member_daily_drafts = models.PositiveSmallIntegerField(
        default=60, validators=[MinValueValidator(1), MaxValueValidator(500)]
    )

    class Meta:
        verbose_name = _("AI settings")
        verbose_name_plural = _("AI settings")

    def __str__(self):
        return f"AI settings of {self.company}"


class AIDraft(TenantModel):
    """A voice note or a typed instruction, read into task drafts that a person creates."""

    class Kind(models.TextChoices):
        TASKS = "tasks", _("Tasks")

    class Source(models.TextChoices):
        BOT = "bot", _("Employee bot")
        OWNER_BOT = "owner_bot", _("Owner bot")
        MINIAPP = "miniapp", _("Mini app")
        DASHBOARD = "dashboard", _("Dashboard")

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        TRANSCRIBING = "transcribing", _("Listening")
        THINKING = "thinking", _("Understanding")
        READY = "ready", _("Ready")
        FAILED = "failed", _("Failed")
        APPLIED = "applied", _("Tasks created")
        DISCARDED = "discarded", _("Discarded")
        EXPIRED = "expired", _("Expired")

    class Engine(models.TextChoices):
        CLAUDE = "claude", "Claude"
        RULES = "rules", _("Rules")
        FAKE = "fake", _("Demo")

    WORKING = (Status.QUEUED, Status.TRANSCRIBING, Status.THINKING)

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TASKS)
    source = models.CharField(max_length=16, choices=Source.choices)
    created_by = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="ai_drafts"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    audio = models.FileField(
        storage=private_storage, upload_to=private_upload_to("ai-voice"), blank=True
    )
    audio_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    input_text = models.TextField(blank=True)
    transcript = models.TextField(blank=True)
    language = models.CharField(max_length=8, blank=True)
    engine = models.CharField(max_length=8, choices=Engine.choices, blank=True)
    # {"drafts": [{title, description, assignee_id, assignee_guess, due_at, priority, checklist,
    #   proof, problems}], "questions": [str]}
    payload = models.JSONField(default=dict, blank=True)
    applied_ids = ArrayField(models.BigIntegerField(), default=list, blank=True)
    applied_by = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    # Created at once by the voice agent's auto-create: the bot card offers Undo for a while.
    auto_applied = models.BooleanField(default=False)
    undone_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=32, blank=True)
    # The bot message to edit once the draft is ready ("employee" or "owner").
    tg_bot = models.CharField(max_length=16, blank=True)
    tg_chat_id = models.BigIntegerField(null=True, blank=True)
    tg_message_id = models.BigIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    transcribed_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "-created_at"], name="ai_draft_company_recent"),
            models.Index(fields=["created_by", "created_at"], name="ai_draft_author_day"),
            models.Index(fields=["status", "created_at"], name="ai_draft_status_age"),
        ]

    def __str__(self):
        return f"Draft #{self.pk}"

    @property
    def drafts(self) -> list[dict]:
        return list((self.payload or {}).get("drafts") or [])

    @property
    def questions(self) -> list[str]:
        return list((self.payload or {}).get("questions") or [])


class AIUsage(TenantModel):
    """One call to Claude: what it cost and how long it took. Never a prompt or an answer."""

    feature = models.CharField(max_length=32)
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    model = models.CharField(max_length=64, help_text=_("The model that answered."))
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    cost_micro_usd = models.BigIntegerField(default=0)
    request_id = models.CharField(max_length=64, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    stop_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        indexes = [models.Index(fields=["company", "created_at"], name="ai_usage_company_day")]

    def __str__(self):
        return f"{self.feature} · {self.model}"


class AgentState(TenantModel):
    """One agent of one company (apps.ai.agents): on or off, its settings and its runs."""

    key = models.CharField(max_length=32)
    enabled = models.BooleanField(default=False)
    config = models.JSONField(default=dict, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    # Set while a run is queued or going ("Run now", a tick), cleared when it ends.
    running_since = models.DateTimeField(null=True, blank=True)
    # The owner's own instructions for its Claude calls, after its own (apps.ai.instructions).
    instructions = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "key"], name="ai_agent_state_unique"),
        ]

    def __str__(self):
        return f"{self.key} of {self.company}"


class AgentRun(TenantModel):
    """One run of a scheduled agent (apps.ai.agents.runner): when, how it ended, what it did
    and what its Claude calls cost. The newest RUNS_KEPT of each agent are kept."""

    class Status(models.TextChoices):
        RUNNING = "running", _("Running")
        OK = "ok", _("Done")
        ERROR = "error", _("Failed")

    key = models.CharField(max_length=32)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.RUNNING)
    # "Run now" from the dashboard, not the schedule.
    forced = models.BooleanField(default=False)
    # What the run returned: how many things the agent did.
    done = models.IntegerField(default=0)
    # The same short text AgentState.last_error gets.
    error = models.CharField(max_length=200, blank=True)
    # The AIUsage rows of the agent's usage features made during the run, summed.
    calls = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_micro_usd = models.BigIntegerField(default=0)

    RUNS_KEPT = 200

    class Meta:
        indexes = [
            models.Index(fields=["company", "key", "-started_at"], name="ai_run_agent_recent"),
        ]

    def __str__(self):
        return f"{self.key} run #{self.pk}"


class CustomAgent(TenantModel):
    """An agent an owner made in their own words (apps.ai.agents.custom): what it should do,
    when, who gets what it writes, and what it may read. It reads with the rights of `run_as`
    (their permissions and branches, at run time); its switch, schedule, runs and events live
    under the key `custom_<id>` like every other agent's (AgentState, AgentRun, AgentEvent)."""

    class Frequency(models.TextChoices):
        DAILY = "daily", _("Every day")
        WEEKDAYS = "weekdays", _("Workdays")
        WEEKLY = "weekly", _("Once a week")
        MONTHLY = "monthly", _("Once a month")

    class Recipients(models.TextChoices):
        ME = "me", _("Me")
        PEOPLE = "people", _("Chosen people")
        GROUP = "group", _("A Telegram group")

    class Color(models.TextChoices):
        SKY = "sky", _("Sky")
        ROSE = "rose", _("Rose")
        INDIGO = "indigo", _("Indigo")
        LIME = "lime", _("Lime")
        AMBER = "amber", _("Amber")
        PLUM = "plum", _("Plum")
        AQUA = "aqua", _("Aqua")
        SLATE = "slate", _("Slate")

    class Paused(models.TextChoices):
        """Why it switched itself off (its owner can't run it any more)."""

        NONE = "", _("Not paused")
        LEFT = "left", _("Its owner no longer works here")
        NO_ACCESS = "no_access", _("Its owner can't use AI or the dashboard any more")

    name = models.CharField(max_length=60)
    job = models.TextField(max_length=2000, help_text=_("What it should do, in the owner's words."))
    color = models.CharField(max_length=16, choices=Color.choices, default=Color.SKY)
    # The template it started from ("" = written from scratch).
    template = models.CharField(max_length=32, blank=True)
    frequency = models.CharField(max_length=16, choices=Frequency.choices, default=Frequency.DAILY)
    at = models.TimeField(help_text=_("When it runs, in the company's timezone."))
    weekday = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(6)],
        help_text=_("For weekly: 0 = Monday."),
    )
    month_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=_("For monthly: the day of the month."),
    )
    recipients = models.CharField(max_length=16, choices=Recipients.choices, default=Recipients.ME)
    people = models.ManyToManyField("members.Membership", blank=True, related_name="+")
    group = models.ForeignKey(
        "groups.TelegramGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # The tool domains it may read (apps.ai.tools.registry): only those whose module is on are
    # offered, and only the tools `run_as` may use.
    domains = ArrayField(models.CharField(max_length=32), default=list, blank=True)
    run_as = models.ForeignKey(
        "members.Membership",
        on_delete=models.CASCADE,
        related_name="+",
        help_text=_("Whose rights it reads with; who 'me' is."),
    )
    created_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    paused_reason = models.CharField(
        max_length=16, choices=Paused.choices, default=Paused.NONE, blank=True
    )
    # The last report it wrote, for its page (shown only to its owner and the people it goes to).
    last_report = models.TextField(blank=True, default="")
    last_report_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    MAX_LIVE = 10

    class Meta:
        indexes = [
            models.Index(fields=["company", "deleted_at"], name="ai_custom_agent_live"),
        ]

    def __str__(self):
        return self.name

    @property
    def key(self) -> str:
        return f"custom_{self.pk}"


class AIConversation(TenantModel):
    """An "Ask AI" conversation, private to its author."""

    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="ai_conversations"
    )
    title = models.CharField(max_length=120, blank=True)
    last_activity_at = models.DateTimeField(db_index=True)
    turn_count = models.PositiveIntegerField(default=0)
    # The agent it talks to ("tutor": "Ask the tutor"); empty for Ask AI itself.
    agent = models.CharField(max_length=32, blank=True, default="")

    def __str__(self):
        return self.title or f"Conversation #{self.pk}"


class AITurn(TenantModel):
    """One question and the work to answer it (tool calls, then the answer)."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="turns")
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    page = models.CharField(max_length=200, blank=True)
    # [{"label": str, "status": "done"|"error", "ms": int}]
    steps = models.JSONField(default=list, blank=True)
    text = models.TextField(blank=True)
    error_code = models.CharField(max_length=32, blank=True)
    message = models.ForeignKey(
        "AIMessage", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    model = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Turn #{self.pk}"


class AIMessage(models.Model):
    """One message of a conversation, its API content blocks exactly as sent or returned
    (thinking blocks included): history is replayed as stored, never edited."""

    class Role(models.TextChoices):
        USER = "user", _("Person")
        ASSISTANT = "assistant", "AI"

    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages"
    )
    turn = models.ForeignKey(
        AITurn, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    seq = models.PositiveIntegerField()
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.JSONField(default=list)
    # What the conversation shows ("" for the tool rounds in between).
    display_text = models.TextField(blank=True)
    in_context = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conversation", "seq"], name="ai_message_seq_unique")
        ]
        ordering = ["seq"]

    def __str__(self):
        return f"{self.role} #{self.seq}"


class AgentEvent(TenantModel):
    """Something an agent did. The text is rendered when it is read, in the reader's language,
    from `kind` and `params` (apps.ai.events)."""

    class Level(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")

    class Subject(models.TextChoices):
        TASK = "task", _("Task")
        MEMBER = "member", _("Person")
        DRAFT = "draft", _("Voice note")

    agent = models.CharField(max_length=32)
    kind = models.CharField(max_length=48)
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.INFO)
    params = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    subject_type = models.CharField(max_length=8, choices=Subject.choices, blank=True)
    subject_id = models.BigIntegerField(null=True, blank=True)
    # Where the subject happens, for branch scope (a task's branch, a person's home branch).
    branch_id = models.BigIntegerField(null=True, blank=True)
    # One event per key and company: what makes a repeated agent run do nothing twice.
    dedupe_key = models.CharField(max_length=96, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "-created_at"], name="ai_event_company_recent"),
            models.Index(fields=["company", "agent", "-created_at"], name="ai_event_agent_recent"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="ai_event_dedupe",
            ),
        ]

    def __str__(self):
        return f"{self.agent}: {self.kind}"
