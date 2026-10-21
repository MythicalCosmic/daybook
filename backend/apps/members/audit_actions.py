"""Audit action codes and labels of memberships added with the owner console
(`apps.audit.registry.register`, from hooks.py). The original ones are AuditLog.Action."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class MemberAction(models.TextChoices):
    SUSPENDED = "member.suspended", _("Suspended a member")
    REINSTATED = "member.reinstated", _("Reinstated a member")
    # Package C: the owner console.
    CHANGED = "members.changed", _("Changed a member's details")
    ROLE_CHANGED = "members.role_changed", _("Changed a member's role")
    UNBLOCKED = "members.unblocked", _("Unblocked a member")
    ROLE_CREATED = "members.role_created", _("Created a role")
    ROLE_SAVED = "members.role_saved", _("Changed a role")
    ROLE_DELETED = "members.role_deleted", _("Deleted a role")
    POSITION_CREATED = "members.position_created", _("Added a position")
    POSITION_SAVED = "members.position_saved", _("Changed a position")
    POSITION_DELETED = "members.position_deleted", _("Deleted a position")
    POSITIONS_REORDERED = "members.positions_reordered", _("Reordered positions")
