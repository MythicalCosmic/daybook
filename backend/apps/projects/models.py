"""Projects: boards of tasks with lists and milestones.

Wave 0 ships the three models `tasks.Task` links to (project, list, milestone); Package T adds
members, labels, time, updates, files and links in its own migrations.
"""

from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, TenantModel
from apps.core.models import TimeStampedModel
from apps.core.money import CurrencyField, MoneyField
from apps.members.models import Membership

KEY_PATTERN = r"^[A-Z]{2,6}$"


class Project(TenantModel):
    class Status(models.TextChoices):
        PLANNING = "planning", _("Planning")
        ACTIVE = "active", _("Active")
        ON_HOLD = "on_hold", _("On hold")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")

    class Visibility(models.TextChoices):
        MEMBERS = "members", _("Project members")
        COMPANY = "company", _("Everyone in the company")

    name = models.CharField(max_length=120)
    key = models.CharField(
        max_length=6,
        validators=[RegexValidator(KEY_PATTERN, _("2 to 6 capital letters, e.g. RENO."))],
        help_text=_("Cards show it with their number, e.g. RENO-14."),
    )
    description = models.TextField(blank=True, help_text=_("Markdown."))
    color = models.CharField(max_length=16, blank=True)
    icon = models.CharField(max_length=40, blank=True, help_text=_("A lucide icon name."))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNING)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    lead = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="led_projects"
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects"
    )
    start_on = models.DateField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    budget = MoneyField(null=True, blank=True)
    budget_currency = CurrencyField()
    visibility = models.CharField(
        max_length=8, choices=Visibility.choices, default=Visibility.MEMBERS
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    position = models.FloatField(default=0)

    class Meta:
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "key"], name="unique_project_key_per_company"
            ),
            models.CheckConstraint(condition=Q(key__regex=KEY_PATTERN), name="project_key_format"),
        ]

    def __str__(self):
        return f"{self.key} {self.name}"


class ProjectList(TimeStampedModel):
    """A column of the project board. At most one per project is the done list."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="lists")
    name = models.CharField(max_length=60)
    position = models.FloatField(default=0)
    is_done = models.BooleanField(default=False)
    wip_limit = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["project"], condition=Q(is_done=True), name="one_done_list_per_project"
            ),
        ]

    def __str__(self):
        return self.name


class Milestone(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        DONE = "done", _("Done")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    due_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=4, choices=Status.choices, default=Status.OPEN)
    completed_at = models.DateTimeField(null=True, blank=True)
    position = models.FloatField(default=0)

    class Meta:
        ordering = ["position", "due_on", "pk"]

    def __str__(self):
        return self.name
