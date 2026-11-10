"""Audit action codes and labels of insights (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class InsightAction(models.TextChoices):
    ACKNOWLEDGED = "insights.acknowledged", _("Marked an insight as seen")
    DISMISSED = "insights.dismissed", _("Dismissed an insight")
    RESOLVED = "insights.resolved", _("Marked an insight as resolved")
    TASK_MADE = "insights.task_made", _("Made a task from an insight")
    SETTINGS_CHANGED = "insights.settings_changed", _("Changed the insight settings")
    CHECKED = "insights.checked", _("Ran the insight checks now")
