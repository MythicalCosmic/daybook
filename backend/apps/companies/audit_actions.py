"""Audit action codes and labels of company setup (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class CompanyAction(models.TextChoices):
    CREATED = "companies.created", _("Created the company")
    SETTINGS_CHANGED = "companies.settings_changed", _("Changed company settings")
    LOGO_CHANGED = "companies.logo_changed", _("Changed the company logo")
    FEATURES_CHANGED = "companies.features_changed", _("Switched modules on or off")
    SETUP_DISMISSED = "companies.setup_dismissed", _("Dismissed Get started")
    SETUP_RESUMED = "companies.setup_resumed", _("Brought Get started back")
    INVITE_REGENERATED = "companies.invite_regenerated", _("Made a new invite link")
    SETUP_COPIED = "companies.setup_copied", _("Copied setup from another company")
    BRANCH_CREATED = "companies.branch_created", _("Added a branch")
    BRANCH_CHANGED = "companies.branch_changed", _("Changed a branch")
    BRANCH_DEACTIVATED = "companies.branch_deactivated", _("Closed a branch")
    BRANCH_ACTIVATED = "companies.branch_activated", _("Reopened a branch")
    BRANCHES_REORDERED = "companies.branches_reordered", _("Reordered branches")
