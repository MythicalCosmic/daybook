import uuid
from datetime import date, datetime

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.companies.models import Branch, TenantModel
from apps.core.models import TimeStampedModel
from apps.core.money import MoneyField
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


class Repeat(models.TextChoices):
    NONE = "none", _("Doesn't repeat")
    DAILY = "daily", _("Every day")
    WEEKDAYS = "weekdays", _("Weekdays")
    WEEKLY = "weekly", _("Every week")


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
    starts_on = models.DateField(
        null=True, blank=True, help_text=_("No tasks are made for days before this.")
    )
    assignees = models.ManyToManyField(Membership, blank=True, related_name="task_templates")
    positions = models.ManyToManyField(
        Position,
        blank=True,
        related_name="task_templates",
        help_text=_("Everyone holding one of these positions gets the task."),
    )
    proof = models.CharField(max_length=8, choices=Proof.choices, default=Proof.NONE)
    needs_confirmation = models.BooleanField(default=False)
    accept_with_proof = models.BooleanField(
        default=False,
        help_text=_(
            "With needs_confirmation: a run finished with a photo or text proof is accepted "
            "automatically; without one, someone checks it."
        ),
    )
    is_active = models.BooleanField(default=True)
    personal = models.BooleanField(
        default=False,
        help_text=_("Made by an employee for themselves; it repeats a personal task."),
    )
    created_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reminder_policy = models.ForeignKey(
        "reminders.ReminderPolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Leave empty for the company's default."),
    )
    escalate_to = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Who hears when it's late. Empty: everyone who can confirm tasks."),
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_templates",
        help_text=_("Only people whose home branch this is get it. Empty: everyone it names."),
    )
    checklist = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        help_text=_("Steps copied into every task it makes."),
    )
    onboarding = models.BooleanField(
        default=False,
        help_text=_(
            "An onboarding task: given once to each new person it names when they are approved, "
            "instead of every day."
        ),
    )
    due_after_days = models.PositiveSmallIntegerField(
        default=1, help_text=_("Onboarding tasks: due this many days after the approval.")
    )

    class Meta:
        ordering = ["due_time", "title"]

    def __str__(self):
        return self.title

    def is_due_on(self, day: date) -> bool:
        return day.weekday() in self.weekdays


def proof_upload_to(task: Task, filename: str) -> str:
    """Unguessable names, because proof photos are company-internal. The client's file name is
    never used: every proof is re-encoded as a JPEG (apps.core.uploads.sanitize_image)."""
    return f"proofs/{task.company_id}/{uuid.uuid4().hex}.jpg"


def proof_thumb_upload_to(task: Task, filename: str) -> str:
    """The 400 px WebP preview of a proof photo, at an unguessable name (PLAN-OWNER §2.8)."""
    return f"proofs/thumbs/{task.company_id}/{uuid.uuid4().hex}.webp"


class Task(TenantModel):
    class Kind(models.TextChoices):
        DAILY = "daily", _("Daily")
        ASSIGNED = "assigned", _("Assigned")
        PERSONAL = "personal", _("Personal")

    class Status(models.TextChoices):
        TODO = "todo", _("To do")
        IN_PROGRESS = "in_progress", _("In progress")
        REVIEW = "review", _("Waiting for check")
        RETURNED = "returned", _("Sent back")
        # Its own context: the projects board's "Done" column is another word in Russian.
        DONE = "done", pgettext_lazy("task status", "Done")
        CANCELLED = "cancelled", _("Cancelled")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        NORMAL = "normal", _("Normal")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    class Blocker(models.TextChoices):
        """Why the assignee can't do it ("Can't do it", `services.report_blocker`)."""

        NO_STOCK = "no_stock", _("Out of stock")
        NO_ACCESS = "no_access", _("No access")
        BROKEN = "broken", _("Equipment broken")
        NOT_MINE = "not_mine", _("Not my task")
        OTHER = "other", _("Another reason")

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
    accept_with_proof = models.BooleanField(
        default=False,
        help_text=_(
            "With needs_confirmation: finished with a photo or text proof, it is accepted "
            "automatically; without one, someone checks it."
        ),
    )
    proof_text = models.TextField(blank=True)
    proof_photo = models.FileField(upload_to=proof_upload_to, blank=True)
    proof_thumb = models.FileField(
        upload_to=proof_thumb_upload_to,
        blank=True,
        help_text=_("A small preview of the proof photo, made after it's uploaded."),
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Reminders (see apps.reminders).
    reminder_policy = models.ForeignKey(
        "reminders.ReminderPolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    escalate_to = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    next_reminder_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reminders_sent = models.PositiveSmallIntegerField(default=0)
    escalated_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    snooze_count = models.PositiveSmallIntegerField(default=0)
    last_reminder_message_id = models.BigIntegerField(null=True, blank=True)
    last_nudged_at = models.DateTimeField(
        null=True, blank=True, help_text=_('When a manager last pressed "Nudge now".')
    )
    seen_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the assignee first opened it.")
    )

    # "Can't do it": the assignee's reason; reminders pause until the giver decides.
    blocker = models.CharField(max_length=10, choices=Blocker.choices, blank=True)
    blocker_note = models.CharField(max_length=300, blank=True)
    blocked_at = models.DateTimeField(null=True, blank=True)
    # "Need more time": the deadline the assignee asked for, until the giver decides.
    extension_until = models.DateTimeField(null=True, blank=True)
    extension_note = models.CharField(max_length=300, blank=True)
    extension_asked_at = models.DateTimeField(null=True, blank=True)

    reward = MoneyField(null=True, blank=True)
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        help_text=_("The assignee's home branch when the task was made; never moves after."),
    )

    # Projects (see apps.projects): the card of a task on its project's board.
    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, null=True, blank=True, related_name="tasks"
    )
    project_list = models.ForeignKey(
        "projects.ProjectList",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    milestone = models.ForeignKey(
        "projects.Milestone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    list_position = models.FloatField(default=0)

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
            models.Index(fields=["project", "project_list", "list_position"]),
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


class Activity(TenantModel):
    """An entry in someone's in-app feed ("New for you")."""

    class Kind(models.TextChoices):
        ASSIGNED = "assigned", _("Gave you a task")
        REVIEW = "review", _("Asked you to check a task")
        COMPLETED = "completed", _("Completed a task you gave")
        CONFIRMED = "confirmed", _("Checked your task")
        RETURNED = "returned", _("Sent a task back")
        COMMENTED = "commented", _("Commented on a task")

    recipient = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    text = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "activity"
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["recipient", "read_at"])]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.task}"


class TaskMessage(models.Model):
    """A bot message about a task in someone's chat (research R1 C5): when the task changes,
    every copy is drawn again, so nobody taps a stale button. The card someone taps is edited
    by the bot itself."""

    class Kind(models.TextChoices):
        CARD = "card", _("Task card")
        REVIEW = "review", _("Check request")
        BLOCKED = "blocked", _("Can't do it")
        ESCALATION = "escalation", _("Late alert")

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="messages")
    member = models.ForeignKey(
        Membership, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    chat_id = models.BigIntegerField()
    message_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["chat_id", "message_id"], name="one_row_per_message")
        ]
        indexes = [models.Index(fields=["task", "created_at"])]

    def __str__(self):
        return f"{self.kind} of {self.task_id} in {self.chat_id}"


class OnFinish(models.TextChoices):
    """What happens when someone finishes work someone else gave them (PLAN-OWNER §15.3)."""

    AUTO = "auto", _("Accept it automatically")
    PROOF = "proof", _("Accept automatically only with a photo or text proof, otherwise ask")
    ASK = "ask", _("Always ask the person who gave it")


class TasksSettings(models.Model):
    """The company's rules for finished work (`apps.tasks.conf.get_settings`). `on_finish` is
    the default of new tasks and routines; a task's or routine's own choice wins."""

    AUTO_ACCEPT_HOURS = (4, 72)

    company = models.OneToOneField(
        "companies.Company", on_delete=models.CASCADE, related_name="tasks_settings"
    )
    on_finish = models.CharField(
        max_length=8,
        choices=OnFinish.choices,
        default=OnFinish.AUTO,
        help_text=_("When someone finishes a task."),
    )
    auto_accept_after_hours = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(AUTO_ACCEPT_HOURS[0]),
            MaxValueValidator(AUTO_ACCEPT_HOURS[1]),
        ],
        help_text=_("If nobody reviews it within this many hours, accept it automatically."),
    )

    class Meta:
        verbose_name_plural = "tasks settings"

    def __str__(self):
        return f"Task settings of {self.company_id}"
