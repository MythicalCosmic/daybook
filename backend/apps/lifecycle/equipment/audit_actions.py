"""Audit actions of equipment, recorded on the person (their history in Person 360). The
assets services audit the asset itself; these name the items' numbers, never a value or a
deduction's amount."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class EquipmentAction(models.TextChoices):
    ISSUED = "lifecycle.equipment_issued", _("Gave equipment")
    RETURNED = "lifecycle.equipment_returned", _("Took equipment back")
    LOST = "lifecycle.equipment_lost", _("Wrote off equipment that wasn't handed back")
    WRITTEN_OFF = "lifecycle.equipment_written_off", _("Wrote off damaged equipment")
    DEDUCTION = "lifecycle.equipment_deduction", _("Proposed a deduction for equipment")
    ADDED = "lifecycle.equipment_added", _("Added equipment to give out")
