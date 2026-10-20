"""Audit action codes and labels of sales and cash (`apps.audit.registry.register`)."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class SalesAction(models.TextChoices):
    SETTINGS_CHANGED = "sales.settings_changed", _("Changed the sales settings")
    METHOD_CREATED = "sales.method_created", _("Added a payment method")
    METHOD_CHANGED = "sales.method_changed", _("Changed a payment method")
    METHODS_REORDERED = "sales.methods_reordered", _("Reordered the payment methods")
    REGISTER_CREATED = "sales.register_created", _("Added a till")
    REGISTER_CHANGED = "sales.register_changed", _("Changed a till")
    TARGET_SET = "sales.target_set", _("Set a sales target")
    TARGET_DELETED = "sales.target_deleted", _("Removed a sales target")
    SHIFT_OPENED = "sales.shift_opened", _("Opened a shift")
    SHIFT_CLOSED = "sales.shift_closed", _("Closed a shift")
    SHIFT_FORCE_CLOSED = "sales.shift_force_closed", _("Force-closed a shift")
    SHIFT_VERIFIED = "sales.shift_verified", _("Verified a shift")
    SHIFT_DISPUTED = "sales.shift_disputed", _("Disputed a shift")
    SHIFT_CORRECTED = "sales.shift_corrected", _("Corrected a shift")
    SHIFT_AI_READING = "sales.shift_ai_reading", _("Read a shift's photos with AI")
    MOVEMENT_RECORDED = "sales.movement_recorded", _("Recorded a cash movement")
    MOVEMENT_VOIDED = "sales.movement_voided", _("Voided a cash movement")
    HANDOVER_CONFIRMED = "sales.handover_confirmed", _("Confirmed a cash handover")
    HANDOVER_DECLINED = "sales.handover_declined", _("Said a cash handover never arrived")
    SALE_RECORDED = "sales.sale_recorded", _("Recorded a receipt")
    SALE_VOIDED = "sales.sale_voided", _("Voided a receipt")
