"""Audit action codes and labels of exports (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ExportAction(models.TextChoices):
    DATA_EXPORTED = "data.exported", _("Exported data")
