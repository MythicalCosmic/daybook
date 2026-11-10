"""Audit action codes and labels of briefings (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class BriefingAction(models.TextChoices):
    SETTINGS_CHANGED = "briefings.settings_changed", _("Changed when the business reviews go out")
    REGENERATED = "briefings.regenerated", _("Had a business review written again")
