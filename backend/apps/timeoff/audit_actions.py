"""Audit action codes of time off added with the owner console (registered from hooks.py).
The original approve and reject codes are AuditLog.Action."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeOffAuditAction(models.TextChoices):
    RECORDED = "timeoff.recorded", _("Recorded time off for someone")
    REVOKED = "timeoff.revoked", _("Revoked approved time off")
    HOLIDAY_ADDED = "timeoff.holiday_added", _("Added a company holiday")
    HOLIDAY_CHANGED = "timeoff.holiday_changed", _("Changed a company holiday")
    HOLIDAY_REMOVED = "timeoff.holiday_removed", _("Removed a company holiday")
