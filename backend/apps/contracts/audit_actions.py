"""Audit action codes and labels of business contracts (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class ContractsAction(models.TextChoices):
    CONTRACT_CREATED = "contracts.created", _("Added a contract")
    CONTRACT_UPDATED = "contracts.updated", _("Changed a contract")
    CONTRACT_RENEWED = "contracts.renewed", _("Renewed a contract")
    CONTRACT_TERMINATED = "contracts.terminated", _("Terminated a contract")
    CONTRACT_STATUS = "contracts.status", _("A contract's status changed")
    CONTRACT_DELETED = "contracts.deleted", _("Deleted a contract")
    FILE_ADDED = "contracts.file_added", _("Added a contract file")
    FILE_REMOVED = "contracts.file_removed", _("Removed a contract file")
    SETTINGS_CHANGED = "contracts.settings", _("Changed the contract reminders")
