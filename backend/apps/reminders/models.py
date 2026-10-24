from datetime import time

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.members.models import Membership
from apps.tasks.models import Task, Weekday


class ReminderPolicy(TenantModel):
    """How hard the bot chases late work. Every company has a default; templates and tasks
    can point at another one."""

    name = models.CharField(max_length=100, default="Default")
    is_default = models.BooleanField(default=False)
    heads_up_minutes = models.PositiveSmallIntegerField(
        default=0, help_text=_("A nudge this many minutes before the deadline. 0 = none.")
    )
    repeat_every_minutes = models.PositiveSmallIntegerField(
        default=20,
        validators=[MinValueValidator(5)],
        help_text=_("After the deadline, remind again this often until it's done."),
    )
    max_reminders = models.PositiveSmallIntegerField(
        default=8, help_text=_("Stop after this many reminders. 0 = until it's done.")
    )
    escalate_after = models.PositiveSmallIntegerField(
        default=3, help_text=_("Tell the manager after this many reminders. 0 = never.")
    )
    quiet_from = models.TimeField(
        default=time(22, 0), null=True, blank=True, help_text=_("No reminders from…")
    )
    quiet_until = models.TimeField(
        default=time(8, 0), null=True, blank=True, help_text=_("…until.")
    )
    quiet_days = ArrayField(
        models.PositiveSmallIntegerField(choices=Weekday.choices),
        default=list,
        blank=True,
        help_text=_("Days with no reminders at all."),
    )
    snooze_minutes = models.PositiveSmallIntegerField(default=30, validators=[MinValueValidator(5)])
    max_snoozes = models.PositiveSmallIntegerField(
        default=1, help_text=_("Snoozes allowed per task. 0 = none.")
    )
    # One live reminder per task (audit X-10, research R1 N2): the new one still rings.
    replace_previous = models.BooleanField(
        default=True,
        help_text=_("Delete the last reminder when sending the next, instead of stacking them."),
    )

    class Meta:
        verbose_name_plural = "reminder policies"
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(is_default=True),
                name="one_default_policy_per_company",
            ),
        ]

    def __str__(self):
        return self.name


class ReminderText(models.Model):
    """An owner's own wording, used from a given reminder on."""

    policy = models.ForeignKey(ReminderPolicy, on_delete=models.CASCADE, related_name="texts")
    from_step = models.PositiveSmallIntegerField(
        default=1, help_text=_("Used from this reminder on (1 = the first one).")
    )
    text = models.TextField(help_text=_("Placeholders: {name} {task} {due} {late}"))

    class Meta:
        ordering = ["from_step"]
        constraints = [
            models.UniqueConstraint(fields=["policy", "from_step"], name="one_text_per_step"),
        ]

    def __str__(self):
        return f"#{self.from_step}: {self.text[:40]}"


class ReminderLog(models.Model):
    class Kind(models.TextChoices):
        HEADS_UP = "heads_up", _("Heads-up")
        REMINDER = "reminder", _("Reminder")
        ESCALATION = "escalation", _("Escalation")
        BLOCKED = "blocked", _("Blocked the bot")

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reminder_log")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    step = models.PositiveSmallIntegerField(default=0)
    recipient = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    delivered = models.BooleanField(default=True)
    error = models.CharField(max_length=200, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.step} for {self.task}"
