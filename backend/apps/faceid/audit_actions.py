"""Audit action codes and labels of Face ID (`apps.audit.registry.register`). Scans themselves
are the record, so they aren't audited; every change a person makes to terminals, numbers and
settings is (an automatic link too, by the system)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class FaceIdAction(models.TextChoices):
    SETTINGS_CHANGED = "faceid.settings_changed", _("Changed Face ID settings")
    DEVICE_ADDED = "faceid.device_added", _("Added a Face ID terminal")
    DEVICE_CHANGED = "faceid.device_changed", _("Changed a Face ID terminal")
    CODE_CHANGED = "faceid.code_changed", _("Gave a Face ID terminal a new code")
    LINKED = "faceid.linked", _("Linked a Face ID number to a person")
    UNLINKED = "faceid.unlinked", _("Removed a Face ID number")
    IGNORED = "faceid.ignored", _("Set a Face ID number aside")
    SIMULATED = "faceid.simulated", _("Sent a test Face ID scan")
    BOT_CONNECTED = "faceid.bot_connected", _("Connected the Face ID bot")
    BOT_REMOVED = "faceid.bot_removed", _("Removed the Face ID bot")
