"""Audit actions of fixed assets (apps.audit.registry)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AssetAction(models.TextChoices):
    SETTINGS_CHANGED = "assets.settings_changed", _("Changed the asset policy")
    CATEGORY_CREATED = "assets.category_created", _("Added an asset category")
    CATEGORY_CHANGED = "assets.category_changed", _("Changed an asset category")
    CATEGORY_DELETED = "assets.category_deleted", _("Deleted an asset category")
    CREATED = "assets.created", _("Added an asset")
    CHANGED = "assets.changed", _("Changed an asset")
    DELETED = "assets.deleted", _("Deleted an asset")
    EVENT = "assets.event", _("Recorded something on an asset")
    ISSUED = "assets.issued", _("Gave an asset to someone")
    RETURNED = "assets.returned", _("Took an asset back")
    DISPOSED = "assets.disposed", _("Disposed of an asset")
    FILE_ADDED = "assets.file_added", _("Added a photo or document to an asset")
    FILE_REMOVED = "assets.file_removed", _("Removed a photo or document of an asset")
    COUNT_STARTED = "assets.count_started", _("Started an asset count")
    COUNT_CLOSED = "assets.count_closed", _("Closed an asset count")
    PERMIT_SAVED = "assets.permit_saved", _("Saved a licence or permit")
    PERMIT_DELETED = "assets.permit_deleted", _("Deleted a licence or permit")
