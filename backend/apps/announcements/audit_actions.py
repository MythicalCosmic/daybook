"""Audit action codes of announcements added with the owner console (registered from hooks.py).
Sending one stays AuditLog.Action.ANNOUNCEMENT_SENT."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AnnouncementAction(models.TextChoices):
    SCHEDULED = "announcements.scheduled", _("Scheduled an announcement")
    EDITED = "announcements.edited", _("Changed a scheduled announcement")
    CANCELLED = "announcements.cancelled", _("Cancelled a scheduled announcement")
    REMINDED = "announcements.reminded", _("Reminded people to read an announcement")
    PINNED = "announcements.pinned", _("Pinned an announcement")
    UNPINNED = "announcements.unpinned", _("Unpinned an announcement")
