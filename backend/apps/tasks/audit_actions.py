"""Audit action codes and labels the tasks app adds for the owner console
(`apps.audit.registry.register`). The older task codes ("task.assigned", "task.confirmed", …)
stay in `AuditLog.Action`."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class TasksAction(models.TextChoices):
    REASSIGNED = "tasks.reassigned", _("Gave a task to someone else")
    NUDGED = "tasks.nudged", _("Nudged someone about a task")
    ONBOARDING_ASSIGNED = "tasks.onboarding_assigned", _("Gave a new person their onboarding tasks")
    BULK = "tasks.bulk", _("Changed several tasks at once")
