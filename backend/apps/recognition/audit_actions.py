"""Audit action codes and labels of recognition (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class RecognitionAction(models.TextChoices):
    SETTINGS_CHANGED = "recognition.settings_changed", _("Changed the recognition settings")
    POINTS_ADJUSTED = "recognition.points_adjusted", _("Corrected someone's points")
    KUDOS_HIDDEN = "recognition.kudos_hidden", _("Hid a thank-you")
