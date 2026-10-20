"""Audit action codes and labels of the knowledge base (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class KnowledgeAction(models.TextChoices):
    SPACE_CREATED = "knowledge.space_created", _("Created a knowledge base space")
    SPACE_CHANGED = "knowledge.space_changed", _("Changed a knowledge base space")
    SPACE_ARCHIVED = "knowledge.space_archived", _("Archived a knowledge base space")
    PAGE_CREATED = "knowledge.page_created", _("Created a page")
    PAGE_SAVED = "knowledge.page_saved", _("Edited a page")
    PAGE_PUBLISHED = "knowledge.page_published", _("Published a page")
    PAGE_UNPUBLISHED = "knowledge.page_unpublished", _("Unpublished a page")
    PAGE_MOVED = "knowledge.page_moved", _("Moved a page")
    PAGE_ARCHIVED = "knowledge.page_archived", _("Archived a page")
    PAGE_RESTORED = "knowledge.page_restored", _("Restored a page")
    VERSION_RESTORED = "knowledge.version_restored", _("Restored an earlier version of a page")
    PAGE_LINKED = "knowledge.page_linked", _("Linked a page to a task or routine")
    PAGE_UNLINKED = "knowledge.page_unlinked", _("Unlinked a page from a task or routine")
    READERS_REMINDED = "knowledge.readers_reminded", _("Reminded people to read a page")
    SETTINGS_CHANGED = "knowledge.settings_changed", _("Changed the knowledge base settings")
