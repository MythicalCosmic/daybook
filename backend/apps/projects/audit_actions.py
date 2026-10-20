"""Audit action codes and labels of projects (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ProjectsAction(models.TextChoices):
    PROJECT_CREATED = "projects.project_created", _("Created a project")
    PROJECT_CHANGED = "projects.project_changed", _("Changed a project")
    PROJECT_ARCHIVED = "projects.project_archived", _("Archived a project")
    PROJECT_RESTORED = "projects.project_restored", _("Restored a project")
    MEMBER_ADDED = "projects.member_added", _("Added someone to a project")
    MEMBER_REMOVED = "projects.member_removed", _("Removed someone from a project")
    MEMBER_ROLE_CHANGED = "projects.member_role_changed", _("Changed a project role")
    LIST_CREATED = "projects.list_created", _("Added a board list")
    LIST_CHANGED = "projects.list_changed", _("Changed a board list")
    LIST_DELETED = "projects.list_deleted", _("Deleted a board list")
    LISTS_REORDERED = "projects.lists_reordered", _("Reordered board lists")
    CARD_CREATED = "projects.card_created", _("Added a card")
    CARD_CHANGED = "projects.card_changed", _("Changed a card")
    CARD_MOVED = "projects.card_moved", _("Moved a card")
    MILESTONE_CREATED = "projects.milestone_created", _("Added a milestone")
    MILESTONE_CHANGED = "projects.milestone_changed", _("Changed a milestone")
    MILESTONE_DELETED = "projects.milestone_deleted", _("Deleted a milestone")
    LABEL_CREATED = "projects.label_created", _("Added a label")
    LABEL_CHANGED = "projects.label_changed", _("Changed a label")
    LABEL_DELETED = "projects.label_deleted", _("Deleted a label")
    TIME_LOGGED = "projects.time_logged", _("Logged time")
    TIME_CHANGED = "projects.time_changed", _("Changed logged time")
    TIME_DELETED = "projects.time_deleted", _("Deleted logged time")
    UPDATE_POSTED = "projects.update_posted", _("Posted a project update")
    FILE_ADDED = "projects.file_added", _("Added a project file")
    FILE_DELETED = "projects.file_deleted", _("Deleted a project file")
    LINK_ADDED = "projects.link_added", _("Added a project link")
    LINK_DELETED = "projects.link_deleted", _("Deleted a project link")
    SETTINGS_CHANGED = "projects.settings_changed", _("Changed project settings")
