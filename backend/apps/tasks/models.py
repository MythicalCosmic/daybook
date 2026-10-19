import uuid
from datetime import date, datetime
from pathlib import Path

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.core.models import TimeStampedModel
from apps.members.models import Membership, Position


class Weekday(models.IntegerChoices):
    MONDAY = 0, _("Monday")
    TUESDAY = 1, _("Tuesday")
    WEDNESDAY = 2, _("Wednesday")
    THURSDAY = 3, _("Thursday")
    FRIDAY = 4, _("Friday")
    SATURDAY = 5, _("Saturday")
    SUNDAY = 6, _("Sunday")


class Proof(models.TextChoices):
    NONE = "none", _("Not needed")
    PHOTO = "photo", _("Photo")
    TEXT = "text", _("Text report")
    ANY = "any", _("Photo or text report")


def every_weekday() -> list[int]:
    return list(Weekday.values)


class TaskTemplate(TenantModel):
    """A recurring task. Each day it's due, everyone it applies to gets their own task."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    weekdays = ArrayField(
        models.PositiveSmallIntegerField(choices=Weekday.choices), default=every_weekday
    )
    due_time = models.TimeField(help_text=_("In the company's timezone."))
    assignees = models.ManyToManyField(Membership, blank=True, related_name="task_templates")
    positions = models.ManyToManyField(
        Position,
        blank=True,
        related_name="task_templates",
        help_text=_("Everyone holding one of these positions gets the task."),
    )
    proof = models.CharField(max_length=8, choices=Proof.choices, default=Proof.NONE)
    needs_confirmation = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["due_time", "title"]

    def __str__(self):
        return self.title

    def is_due_on(self, day: date) -> bool:
        return day.weekday() in self.weekdays


def proof_upload_to(task: Task, filename: str) -> str:
    # Unguessable names: proof photos are company-internal.
    return f"proofs/{task.company_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class Task(TenantModel):
    class Kind(models.TextChoices):
        DAILY = "daily", _("Daily")
        ASSIGNED = "assigned", _("Assigned")
        PERSONAL = "personal", _("Personal")

    class Status(models.TextChoices):
        TODO = "todo", _("To do")
        IN_PROGRESS = "in_progress", _("In progress")
        REVIEW = "review", _("Waiting for confirmation")
        RETURNED = "returned", _("Sent back")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    # Still the assignee's to do. A returned task is open again: it needs another go.
    OPEN_STATUSES = (Status.TODO, Status.IN_PROGRESS, Status.RETURNED)

    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assignee = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="tasks")
    created_by = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )
    template = models.ForeignKey(
        TaskTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    for_date = models.DateField(
        null=True, blank=True, help_text=_("For daily tasks: the local day it belongs to.")
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=8, choices=Priority.choices, default=Priority.NORMAL)
    due_at = models.DateTimeField(null=True, blank=True)
    proof = models.CharField(max_length=8, choices=Proof.choices, default=Proof.NONE)
    needs_confirmation = models.BooleanField(default=False)
    proof_text = models.TextField(blank=True)
    proof_photo = models.FileField(upload_to=proof_upload_to, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = [F("due_at").asc(nulls_last=True), "pk"]
        constraints = [
            # NULLs are distinct, so this only binds generated daily tasks.
            models.UniqueConstraint(
                fields=["template", "assignee", "for_date"],
                name="one_daily_task_per_person_per_day",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "assignee", "status"]),
            models.Index(fields=["company", "due_at"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    def is_overdue(self, now: datetime | None = None) -> bool:
        return self.is_open and self.due_at is not None and self.due_at < (now or timezone.now())


class ChecklistItem(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    text = models.CharField(max_length=200)
    is_done = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.text


class TaskComment(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    text = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.text[:50]
