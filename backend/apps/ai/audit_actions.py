"""Audit action codes and labels of the AI features (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AIAction(models.TextChoices):
    ENABLED = "ai.enabled", _("Turned AI on")
    DISABLED = "ai.disabled", _("Turned AI off")
    SETTINGS_CHANGED = "ai.settings_changed", _("Changed the AI settings")
    AGENT_CHANGED = "ai.agent_changed", _("Changed an AI agent")
    AGENT_CREATED = "ai.agent_created", _("Created an AI agent")
    AGENT_DELETED = "ai.agent_deleted", _("Deleted an AI agent")
