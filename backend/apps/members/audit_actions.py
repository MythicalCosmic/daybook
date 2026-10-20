"""Audit action codes and labels of memberships added with the owner console
(`apps.audit.registry.register`, from hooks.py). The original ones are AuditLog.Action."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class MemberAction(models.TextChoices):
    SUSPENDED = "member.suspended", _("Suspended a member")
    REINSTATED = "member.reinstated", _("Reinstated a member")
