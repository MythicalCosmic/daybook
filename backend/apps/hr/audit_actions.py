"""Audit action codes and labels of HR records (`apps.audit.registry.register`).

What happens to a person's file is recorded against their membership (target "membership"),
so Person 360's history shows one timeline; the record's own id is in the details. Values of
secret fields (IDs, card numbers, notes) never reach a row, only their names.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class HRAction(models.TextChoices):
    SETTINGS_CHANGED = "hr.settings_changed", _("Changed HR settings")
    PHARMACISTS_CHANGED = "hr.pharmacists_changed", _("Chose who counts as a pharmacist")
    PROFILE_CHANGED = "hr.profile_changed", _("Changed an employee profile")
    SENSITIVE_VIEWED = "hr.sensitive_viewed", _("Viewed ID and card numbers")
    CONTACT_ADDED = "hr.contact_added", _("Added an emergency contact")
    CONTACT_CHANGED = "hr.contact_changed", _("Changed an emergency contact")
    CONTACT_REMOVED = "hr.contact_removed", _("Removed an emergency contact")
    DOCUMENT_ADDED = "hr.document_added", _("Added a document")
    DOCUMENT_CHANGED = "hr.document_changed", _("Changed a document")
    DOCUMENT_REMOVED = "hr.document_removed", _("Removed a document")
    DOCUMENT_VERIFIED = "hr.document_verified", _("Verified a document")
    DOCUMENT_OPENED = "hr.document_opened", _("Opened a document file")
    REQUIRED_SAVED = "hr.required_saved", _("Changed the required documents")
    REQUIRED_REMOVED = "hr.required_removed", _("Removed a required document")
    TEMPLATE_SAVED = "hr.template_saved", _("Saved a contract template")
    TEMPLATE_REMOVED = "hr.template_removed", _("Removed a contract template")
    CONTRACT_CREATED = "hr.contract_created", _("Drew up a contract")
    CONTRACT_CHANGED = "hr.contract_changed", _("Changed a contract")
    CONTRACT_REMOVED = "hr.contract_removed", _("Removed a draft contract")
    CONTRACT_ACTIVATED = "hr.contract_activated", _("Signed a contract")
    CONTRACT_AMENDED = "hr.contract_amended", _("Amended a contract")
    CONTRACT_ENDED = "hr.contract_ended", _("Ended a contract")
    CONTRACT_TERMINATED = "hr.contract_terminated", _("Terminated a contract")
    CONTRACT_RENEWED = "hr.contract_renewed", _("Renewed a contract")
    PROBATION_PASSED = "hr.probation_passed", _("Confirmed a passed probation")
    PROBATION_EXTENDED = "hr.probation_extended", _("Extended a probation")
    CONTRACT_PRINTED = "hr.contract_printed", _("Made a contract PDF")
    CONTRACT_ACKNOWLEDGED = "hr.contract_acknowledged", _("Read their contract")
