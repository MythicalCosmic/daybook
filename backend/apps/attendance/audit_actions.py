"""Audit action codes and labels of attendance (`apps.audit.registry.register`).

Check-ins themselves are the record, so they aren't audited; every change a person makes to
someone else's attendance, schedule or roster is.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AttendanceAction(models.TextChoices):
    SETTINGS_CHANGED = "attendance.settings_changed", _("Changed attendance settings")
    TEMPLATE_SAVED = "attendance.template_saved", _("Saved a shift template")
    TEMPLATE_REMOVED = "attendance.template_removed", _("Removed a shift template")
    SCHEDULE_CREATED = "attendance.schedule_created", _("Created a work schedule")
    SCHEDULE_CHANGED = "attendance.schedule_changed", _("Changed a work schedule")
    SCHEDULE_ARCHIVED = "attendance.schedule_archived", _("Archived a work schedule")
    SCHEDULE_ASSIGNED = "attendance.schedule_assigned", _("Assigned a work schedule")
    SHIFT_CREATED = "attendance.shift_created", _("Added a shift")
    SHIFT_CHANGED = "attendance.shift_changed", _("Changed a shift")
    SHIFT_CANCELLED = "attendance.shift_cancelled", _("Removed a shift")
    ROSTER_BULK = "attendance.roster_bulk", _("Changed the roster in bulk")
    ROSTER_PUBLISHED = "attendance.roster_published", _("Published the roster")
    RECORD_CREATED = "attendance.record_created", _("Recorded attendance by hand")
    RECORD_EDITED = "attendance.record_edited", _("Corrected attendance")
    RECORD_EXCUSED = "attendance.record_excused", _("Excused an absence")
    OVERTIME_APPROVED = "attendance.overtime_approved", _("Approved overtime")
    OVERTIME_REJECTED = "attendance.overtime_rejected", _("Rejected overtime")
    CORRECTION_APPROVED = "attendance.correction_approved", _("Approved an attendance correction")
    CORRECTION_REJECTED = "attendance.correction_rejected", _("Rejected an attendance correction")
    SWAP_APPROVED = "attendance.swap_approved", _("Approved a shift swap")
    SWAP_REJECTED = "attendance.swap_rejected", _("Rejected a shift swap")
