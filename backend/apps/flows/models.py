"""Flows (v0.3 AI contract §4): automations an owner builds from blocks, "when this happens, an AI
step reads it and acts".

Flow      a trigger and up to six steps, switched on or off, acting with its owner's rights
FlowRun   one run of a flow (a real one, or a test that sends and creates nothing): what started
          it and every step's result
"""

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel


class Flow(TenantModel):
    """`trigger` = {"type": str, "config": {}}; `steps` = [{"id": "s1", "type": str, "config":
    {}, "when": None | {"step", "output", "op", "value"}}], checked against the registry
    (apps.flows.validation) whenever they are written."""

    MAX_PER_COMPANY = 20
    MAX_STEPS = 6

    class Paused(models.TextChoices):
        NONE = "", _("Not paused")
        OWNER_GONE = "owner_gone", _("Its owner left or can't configure AI any more")
        TOO_MANY_RUNS = "too_many_runs", _("Too many runs today")

    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True)
    enabled = models.BooleanField(default=False)
    template = models.CharField(max_length=40, blank=True)
    trigger = models.JSONField(default=dict)
    steps = models.JSONField(default=list)
    # The flow acts with this person's rights (they held ai.configure when they made it).
    owner = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="owned_flows"
    )
    updated_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    version = models.PositiveIntegerField(default=1)
    paused_reason = models.CharField(max_length=24, choices=Paused.choices, blank=True)

    class Meta:
        indexes = [models.Index(fields=["company", "enabled"], name="flow_company_enabled")]

    def __str__(self):
        return self.name

    @property
    def trigger_type(self) -> str:
        return str((self.trigger or {}).get("type", ""))

    @property
    def trigger_config(self) -> dict:
        config = (self.trigger or {}).get("config")
        return config if isinstance(config, dict) else {}


class FlowRun(TenantModel):
    """One run. `event` holds the trigger's variables (scrubbed), `steps` the results in order
    ({"id", "type", "status", "output", "engine", "model", "ms", "error", "note"}; the API words
    each one's summary in the reader's language)."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        SKIPPED = "skipped", _("Skipped")
        FAILED = "failed", _("Failed")

    class Subject(models.TextChoices):
        NONE = "", _("Nothing in particular")
        TASK = "task", _("Task")
        MEMBER = "member", _("Person")
        DRAFT = "draft", _("Voice note")
        SHIFT = "shift", _("Cash shift")
        TIME_OFF = "time_off", _("Time off")

    FINISHED = (Status.DONE, Status.SKIPPED, Status.FAILED)

    flow = models.ForeignKey(Flow, on_delete=models.CASCADE, related_name="runs")
    flow_version = models.PositiveIntegerField()
    test = models.BooleanField(default=False)
    # Who started a test run (None for real runs).
    started_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED)
    trigger_type = models.CharField(max_length=24)
    subject_type = models.CharField(max_length=8, choices=Subject.choices, blank=True)
    subject_id = models.BigIntegerField(null=True, blank=True)
    # Where the subject happens, for branch scope (None: nowhere in particular).
    branch_id = models.BigIntegerField(null=True, blank=True)
    event = models.JSONField(default=dict, blank=True)
    steps = models.JSONField(default=list, blank=True)
    cost_micro_usd = models.BigIntegerField(default=0)
    # One run per flow and key ("overdue:<task>:<due>"); "" for runs that may repeat.
    dedupe_key = models.CharField(max_length=96, blank=True)
    # A run waiting out the quiet hours goes on from this step at `resume_at`.
    resume_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "flow", "-created_at"], name="flow_run_recent"),
            models.Index(fields=["status", "created_at"], name="flow_run_status_age"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["flow", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="flow_run_dedupe",
            ),
        ]

    def __str__(self):
        return f"Run #{self.pk} of {self.flow_id}"
