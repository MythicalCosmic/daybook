"""Models of briefings (docs/PLAN-OWNER.md §3.15): the weekly and monthly business reviews
Maslahatchi (the advisor agent, apps.ai.agents.advisor) writes for the owners.

BriefingSettings   when the reviews go out and to whom (lazy, 1-1 Company)
Briefing           one review: the facts (the only source of every number) and the words
BriefingDelivery   who got which review, through which channel, and when they opened it

A review is written for one reading scope: the domains its readers may see (finance, sales,
stock…) and their branches, hashed into `scope_key`, so a manager who sees two pharmacies and
no money never reads the owner's review (apps.briefings.scope).
"""

from datetime import time

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, TenantModel
from apps.core.models import TimeStampedModel


class BriefingSettings(TimeStampedModel):
    """When the reviews go out and to whom. Briefings work without AI: without Claude the
    words come from templates over the same facts."""

    class Recipients(models.TextChoices):
        OWNERS = "owners", _("Owners")
        REPORTS = "reports", _("Everyone who sees reports")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="briefing_settings"
    )
    weekly_enabled = models.BooleanField(
        default=True, help_text=_("The weekly business review, for the week before.")
    )
    monthly_enabled = models.BooleanField(
        default=True, help_text=_("The monthly business review, on the first day of the month.")
    )
    # 0 is Monday, as Python counts weekdays.
    weekday = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        help_text=_("The day the weekly review goes out."),
    )
    send_at = models.TimeField(
        default=time(8, 0), help_text=_("When the reviews go out, in the company's time.")
    )
    recipients = models.CharField(
        max_length=10, choices=Recipients.choices, default=Recipients.OWNERS
    )
    # The first day of the last period whose scheduled review went out: the job sends each
    # period's review once, then waits for the next period.
    weekly_sent_for = models.DateField(null=True, blank=True)
    monthly_sent_for = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Briefing settings of {self.company}"


class Briefing(TenantModel):
    """One business review for one reading scope in one language."""

    class Kind(models.TextChoices):
        WEEKLY = "weekly", _("Weekly review")
        MONTHLY = "monthly", _("Monthly review")

    class WrittenBy(models.TextChoices):
        AI = "ai", _("Claude")
        TEMPLATE = "template", _("Template")

    # The first day of the period it reviews (a Monday, or the first of a month).
    day = models.DateField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    language = models.CharField(max_length=8)
    # The domains its readers may see, sorted ("finance", "sales"…), and their branches
    # (null: every branch); `scope_key` hashes both.
    domains = ArrayField(models.CharField(max_length=16), default=list, blank=True)
    branch_ids = ArrayField(models.IntegerField(), null=True, blank=True)
    scope_key = models.CharField(max_length=16)
    # Every number the review says, computed in SQL (apps.briefings.facts).
    facts = models.JSONField(default=dict)
    # {headline, sections: [{key, title, bullets, facts}], actions: [{text, fact, label, url}]}
    content = models.JSONField(default=dict)
    written_by = models.CharField(
        max_length=8, choices=WrittenBy.choices, default=WrittenBy.TEMPLATE
    )
    # The model that wrote it ("" for a template); when it was last written.
    model = models.CharField(max_length=64, blank=True)
    written_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "day", "kind", "language", "scope_key"],
                name="briefings_one_per_scope",
            )
        ]
        indexes = [
            models.Index(fields=["company", "scope_key", "-day"], name="briefings_scope_recent")
        ]
        ordering = ["-day", "-pk"]

    def __str__(self):
        return f"{self.kind} review from {self.day}"


class BriefingDelivery(models.Model):
    """One review given to one person: once each (the unique pair), however often the job runs."""

    class Via(models.TextChoices):
        BOT = "bot", _("Telegram")
        DASHBOARD = "dashboard", _("Dashboard")

    briefing = models.ForeignKey(Briefing, on_delete=models.CASCADE, related_name="deliveries")
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="briefing_deliveries"
    )
    via = models.CharField(max_length=10, choices=Via.choices, default=Via.BOT)
    sent_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["briefing", "membership"], name="briefings_delivered_once"
            )
        ]

    def __str__(self):
        return f"{self.briefing} to {self.membership_id}"
