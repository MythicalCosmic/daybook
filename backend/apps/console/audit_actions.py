"""Audit action codes and labels of the owner console (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ConsoleAction(models.TextChoices):
    # Personal saved views are preferences, not company data; only shared ones are audited.
    SAVED_VIEW_SHARED = "console.saved_view_shared", _("Shared a saved view")
    SAVED_VIEW_CHANGED = "console.saved_view_changed", _("Changed a shared saved view")
    SAVED_VIEW_UNSHARED = "console.saved_view_unshared", _("Stopped sharing a saved view")
    SAVED_VIEW_DELETED = "console.saved_view_deleted", _("Deleted a shared saved view")
