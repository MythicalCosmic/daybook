"""Audit action codes and labels of business goals (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class GoalsAction(models.TextChoices):
    GOAL_CREATED = "goals.goal_created", _("Set a business goal")
    GOAL_UPDATED = "goals.goal_updated", _("Changed a business goal")
    GOAL_ARCHIVED = "goals.goal_archived", _("Archived a business goal")
    GOAL_RESTORED = "goals.goal_restored", _("Brought back a business goal")
    GOAL_DELETED = "goals.goal_deleted", _("Deleted a business goal")
