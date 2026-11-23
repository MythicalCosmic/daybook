"""Audit action codes and labels of Ko‘z (`apps.audit.registry.register`), docs/KOZ.md §8: pairing
and revoking boxes, settings and zone changes, every clip request and the first live view of a
camera per person per 10 minutes. What the boxes send (numbers, alerts) is the record itself."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class VisionAction(models.TextChoices):
    SETTINGS_CHANGED = "vision.settings_changed", _("Changed the Ko‘z settings")
    BOX_ADDED = "vision.box_added", _("Added a Ko‘z box")
    PAIRING_CODE = "vision.pairing_code", _("Made a pairing code for a Ko‘z box")
    BOX_PAIRED = "vision.box_paired", _("Paired a Ko‘z box")
    BOX_REMOVED = "vision.box_removed", _("Removed a Ko‘z box")
    CAMERA_CHANGED = "vision.camera_changed", _("Changed a Ko‘z camera")
    ZONES_CHANGED = "vision.zones_changed", _("Changed the zones of a Ko‘z camera")
    CLIP_REQUESTED = "vision.clip_requested", _("Asked for a video receipt")
    LIVE_VIEWED = "vision.live_viewed", _("Watched a camera live")
