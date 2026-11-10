"""Models of insights (docs/PLAN-OWNER.md §3.15): what the detection jobs noticed in a company's
numbers, the company's settings for them, and the daily figures they compare over time.

An `Insight` is one finding with the numbers behind it (`metrics`): a cash low point under the
buffer, a branch whose margin fell, an expense category that jumped. The jobs keep it current:
the same finding (`dedupe_key`) updates the row instead of adding one, and a finding that no
longer holds is resolved. Its words are rendered from `kind` and `metrics` in the reader's
language (`apps.insights.texts`); `title`, `explanation` and `suggested_action` keep them in
the company's language as the jobs last wrote them.
"""

from datetime import time
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField


class InsightSettings(TimeStampedModel):
    """One row per company, made on first read by `apps.insights.conf.get_settings`."""

    class Sensitivity(models.TextChoices):
        LOW = "low", _("Only big changes")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("Small changes too")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="insight_settings"
    )
    disabled_kinds = ArrayField(
        models.CharField(max_length=32),
        default=list,
        blank=True,
        help_text=_("Kinds of insight the company doesn't want."),
    )
    sensitivity = models.CharField(
        max_length=8, choices=Sensitivity.choices, default=Sensitivity.NORMAL
    )
    quiet_from = models.TimeField(
        default=time(22, 0), help_text=_("No Telegram messages from this time…")
    )
    quiet_to = models.TimeField(default=time(8, 0), help_text=_("…until this time."))
    notify_critical_via_bot = models.BooleanField(
        default=True, help_text=_("Send urgent insights to the owner bot.")
    )
    min_cash_buffer = MoneyField(
        null=True,
        blank=True,
        help_text=_(
            "The least cash to keep on hand. Empty: a week of the usual spending and supplier "
            "payments."
        ),
    )
    expense_alert_min_amount = MoneyField(
        default=Decimal("1000000"),
        help_text=_("An expense jump smaller than this isn't worth a word."),
    )
    # When the detection jobs last ran for the company (one run per slot of the day).
    last_run_at = models.DateTimeField(null=True, blank=True, editable=False)

    def __str__(self):
        return f"Insight settings of {self.company_id}"


class Insight(TenantModel):
    """One finding of the detection jobs, kept current while it holds (§3.15)."""

    class Kind(models.TextChoices):
        CASH_LOW = "cash_low", _("Cash low point under the buffer")
        BRANCH_MARGIN = "branch_margin", _("A branch's profit or margin falling")
        EXPENSE_SPIKE = "expense_spike", _("An expense category jumping")
        OVERDUE_RECEIVABLES = "overdue_receivables", _("Overdue money owed to us piling up")
        OVERDUE_PAYABLES = "overdue_payables", _("Overdue bills to suppliers piling up")
        STOCK_BUILD = "stock_build", _("Stock growing while sales fall")
        STAFF_COST = "staff_cost", _("Staff cost share rising")

    class Domain(models.TextChoices):
        TASKS = "tasks", _("Tasks")
        PEOPLE = "people", _("People")
        FINANCE = "finance", _("Finance")
        SALES = "sales", _("Sales")
        HR = "hr", _("HR")
        PAYROLL = "payroll", _("Payroll")

    class Severity(models.TextChoices):
        INFO = "info", _("Information")
        WARNING = "warning", _("Warning")
        CRITICAL = "critical", _("Urgent")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        ACKNOWLEDGED = "acknowledged", _("Seen")
        DISMISSED = "dismissed", _("Dismissed")
        RESOLVED = "resolved", _("Resolved")

    class ExplainedBy(models.TextChoices):
        TEMPLATE = "template", _("Template")
        AI = "ai", _("AI")

    # Still true: shown in the cockpit and in Telegram.
    LIVE = (Status.OPEN, Status.ACKNOWLEDGED)

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="insights")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    domain = models.CharField(max_length=16, choices=Domain.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)
    # Branch scope (§2.6): an insight without a branch is company-wide.
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, null=True, blank=True, related_name="insights"
    )
    dedupe_key = models.CharField(max_length=120)
    subject_type = models.CharField(max_length=32, blank=True)
    subject_id = models.PositiveBigIntegerField(null=True, blank=True)
    subject_label = models.CharField(max_length=200, blank=True)
    window_start = models.DateField(null=True, blank=True)
    window_end = models.DateField(null=True, blank=True)
    # {"value", "baseline", "threshold", "unit", "series", ...}: money as strings.
    metrics = models.JSONField(default=dict, blank=True)
    title = models.CharField(max_length=200)
    explanation = models.TextField(blank=True)
    suggested_action = models.CharField(max_length=300, blank=True)
    explained_by = models.CharField(
        max_length=8, choices=ExplainedBy.choices, default=ExplainedBy.TEMPLATE
    )
    detected_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    notified_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    dismissed_at = models.DateTimeField(null=True, blank=True)
    dismissed_reason = models.CharField(max_length=300, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-detected_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "dedupe_key"], name="insights_insight_dedupe"
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "kind", "status"]),
        ]

    def __str__(self):
        return f"{self.kind} #{self.pk}: {self.title}"

    @property
    def is_live(self) -> bool:
        return self.status in self.LIVE


class Snapshot(TenantModel):
    """A daily figure the detectors compare over time that no other app keeps a history of
    (the stock value at cost): one row per company, day, metric and branch (none: the whole
    company). Written by the detection jobs only."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="insight_snapshots")
    day = models.DateField()
    metric = models.CharField(max_length=32)
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    value = MoneyField()

    class Meta:
        ordering = ["day", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "day", "metric", "branch"],
                name="insights_snapshot_once",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        return f"{self.metric} {self.day} {self.branch_id or '-'}: {self.value}"
