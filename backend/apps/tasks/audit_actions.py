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
    REOPENED = "tasks.reopened", _("Undid finishing a task")
    BLOCKED = "tasks.blocked", _("Said they can't do a task")
    UNBLOCKED = "tasks.unblocked", _("Decided about a task someone couldn't do")
    EXTENSION_ASKED = "tasks.extension_asked", _("Asked for more time")
    EXTENSION_DECIDED = "tasks.extension_decided", _("Decided about more time for a task")
    AUTO_ACCEPTED = "tasks.auto_accepted", _("Accepted automatically: nobody reviewed it in time")
    SETTINGS_CHANGED = "tasks.settings_changed", _("Changed the rules for finished tasks")
