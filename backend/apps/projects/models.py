"""Projects: boards of tasks with lists, milestones, labels, time, updates, files and money.

Wave 0 shipped the three models `tasks.Task` links to (project, list, milestone); Package T adds
the rest (docs/PLAN-OWNER.md §13.3). A card is a `tasks.Task` with `project` set: the task app
owns the task itself, this app owns where it sits on the board (`project_list`,
`list_position`), its labels (`TaskLabel`), its number and its planned start (`Card`).

Colours are palette keys (`chart-1` … `chart-8`), never hex: the dashboard and the mini app map
them to their own theme-aware colours.
"""

from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.models import TimeStampedModel
from apps.core.money import CurrencyField, MoneyField
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership

KEY_PATTERN = r"^[A-Z]{2,6}$"
COLOR_KEYS = tuple(f"chart-{n}" for n in range(1, 9))
COLOR_PATTERN = r"^(chart-[1-8])?$"


def color_field(**kwargs) -> models.CharField:
    return models.CharField(
        max_length=16,
        blank=True,
        validators=[
            RegexValidator(COLOR_PATTERN, _("One of the palette colours chart-1 … chart-8."))
        ],
        **kwargs,
    )


class Health(models.TextChoices):
    ON_TRACK = "on_track", _("On track")
    AT_RISK = "at_risk", _("At risk")
    OFF_TRACK = "off_track", _("Off track")


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

    # Statuses whose work is still going on: health, nudges and alerts only look at these.
    LIVE_STATUSES = (Status.PLANNING, Status.ACTIVE, Status.ON_HOLD)

    name = models.CharField(max_length=120)
    key = models.CharField(
        max_length=6,
        validators=[RegexValidator(KEY_PATTERN, _("2 to 6 capital letters, e.g. RENO."))],
        help_text=_("Cards show it with their number, e.g. RENO-14."),
    )
    description = models.TextField(blank=True, help_text=_("Markdown."))
    color = color_field()
    icon = models.CharField(max_length=40, blank=True, help_text=_("A lucide icon name."))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNING)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    lead = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="led_projects"
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="projects"
    )
    client = models.ForeignKey(
        "finance.Counterparty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects",
        help_text=_("Who the project is for, when it is client work."),
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
    # Bookkeeping for the alerts and the weekly nudge (apps.projects.jobs).
    health = models.CharField(
        max_length=10,
        choices=Health.choices,
        blank=True,
        help_text=_("The health owners were last told about."),
    )
    update_nudged_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "key"], name="unique_project_key_per_company"
            ),
            models.CheckConstraint(condition=Q(key__regex=KEY_PATTERN), name="project_key_format"),
            models.CheckConstraint(
                condition=Q(budget__isnull=True) | Q(budget__gte=0),
                name="project_budget_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(start_on__isnull=True)
                | Q(due_on__isnull=True)
                | Q(due_on__gte=models.F("start_on")),
                name="project_due_after_start",
            ),
        ]
        indexes = [models.Index(fields=["company", "status"])]

    def __str__(self):
        return f"{self.key} {self.name}"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class ProjectMember(TimeStampedModel):
    """Who works on a project. The lead is a member with the role `lead`."""

    class Role(models.TextChoices):
        LEAD = "lead", _("Lead")
        MEMBER = "member", _("Member")
        VIEWER = "viewer", _("Viewer")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="project_memberships"
    )
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.MEMBER)
    added_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["project", "membership"], name="unique_project_member"),
        ]

    def __str__(self):
        return f"{self.membership} · {self.project.key}"


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
    missed_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "due_on", "pk"]

    def __str__(self):
        return self.name


class Label(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=30)
    color = color_field()
    position = models.FloatField(default=0)

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="unique_label_per_project"),
        ]

    def __str__(self):
        return self.name


class TaskLabel(models.Model):
    """A label on a card (the through table belongs to projects, not tasks)."""

    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="label_links")
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="task_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "label"], name="unique_task_label"),
        ]

    def __str__(self):
        return f"{self.label} · {self.task_id}"


class Card(models.Model):
    """What the board adds to a task: its number in the project (`RENO-14`) and when work is
    planned to start (the timeline bar's left end; the end is the task's own deadline)."""

    task = models.OneToOneField("tasks.Task", on_delete=models.CASCADE, related_name="card")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="cards")
    number = models.PositiveIntegerField()
    start_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="unique_card_number"),
        ]

    def __str__(self):
        return f"{self.project.key}-{self.number}"


class TimeEntry(TenantModel):
    class Source(models.TextChoices):
        MANUAL = "manual", _("Logged by hand")
        TIMER = "timer", _("Timer")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="time_entries")
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="time_entries"
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True, related_name="time_entries"
    )
    task = models.ForeignKey(
        "tasks.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    day = models.DateField(help_text=_("Company-local day the work happened."))
    minutes = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(1440)]
    )
    note = models.CharField(max_length=300, blank=True)
    billable = models.BooleanField(default=False)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name_plural = "time entries"
        ordering = ["-day", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(minutes__gte=1) & Q(minutes__lte=1440),
                name="time_entry_minutes_in_a_day",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "membership", "day"]),
            models.Index(fields=["project", "day"]),
        ]

    def __str__(self):
        return f"{self.membership} {self.day} {self.minutes} min"


class RunningTimer(TenantModel):
    """A timer someone started; stopping it logs a time entry. One per person."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="running_timers")
    membership = models.OneToOneField(
        Membership, on_delete=models.CASCADE, related_name="running_timer"
    )
    task = models.ForeignKey(
        "tasks.Task",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="running_timers",
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True, related_name="running_timers"
    )
    started_at = models.DateTimeField()
    note = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"{self.membership} since {self.started_at:%H:%M}"


class ProjectUpdate(TimeStampedModel):
    """A status post on a project: how it's going, in the lead's words."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    health = models.CharField(max_length=10, choices=Health.choices)
    text = models.TextField(blank=True, help_text=_("Markdown."))

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.project.key} {self.get_health_display()}"


class ProjectFile(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="files")
    name = models.CharField(max_length=200)
    file = models.FileField(
        storage=private_storage,
        upload_to=private_upload_to("projects", company_attr="project.company_id"),
    )
    size = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=8, help_text=_("pdf, xlsx, csv or image."))
    uploaded_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.name


class ProjectLink(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="links")
    title = models.CharField(max_length=120)
    url = models.URLField(max_length=500)
    added_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.title


class ProjectSettings(models.Model):
    """A company's project defaults (`conf.get_settings`)."""

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="project_settings"
    )
    default_lists = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Names of the lists a new project starts with; the last one is Done."),
    )
    weekly_nudge = models.BooleanField(
        default=True, help_text=_("Remind leads every week to post an update.")
    )
    nudge_weekday = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(6)], help_text=_("0 is Monday.")
    )
    at_risk_days = models.PositiveSmallIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        help_text=_("A project due within this many days is at risk when too little is done."),
    )
    at_risk_percent = models.PositiveSmallIntegerField(
        default=70,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text=_("Below this share of done cards a project close to its due date is at risk."),
    )

    class Meta:
        verbose_name_plural = "project settings"

    def __str__(self):
        return f"Project settings of {self.company}"
