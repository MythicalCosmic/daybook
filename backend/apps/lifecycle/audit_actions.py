"""Audit action codes and labels of the people lifecycle (`apps.audit.registry.register`).

Recorded against the person's membership, so Person 360's history shows them; the record's
id, kind and category are in the details, never its text or the person's explanation.
Suspensions are audited by `members.services` itself. Leaving and job changes name the days
and what changed (field names, positions, branches), never a pay amount: payroll audits the
pay setup itself for payroll.view.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class LifecycleAction(models.TextChoices):
    RECORD_ISSUED = "lifecycle.record_issued", _("Gave a disciplinary record")
    RECORD_CHANGED = "lifecycle.record_changed", _("Changed a disciplinary record")
    RECORD_WITHDRAWN = "lifecycle.record_withdrawn", _("Withdrew a disciplinary record")
    RECORD_REMOVED = "lifecycle.record_removed", _("Removed a disciplinary record")
    RECORD_ACKNOWLEDGED = "lifecycle.record_acknowledged", _("Confirmed being told of a record")
    RECORD_EXPLAINED = "lifecycle.record_explained", _("Wrote an explanation")
    FINE_PROPOSED = "lifecycle.fine_proposed", _("Proposed a fine with a record")
    # Leaving.
    LEAVE_REQUESTED = "lifecycle.leave_requested", _("Asked to leave")
    LEAVE_STARTED = "lifecycle.leave_started", _("Started someone's leaving")
    LEAVE_AGREED = "lifecycle.leave_agreed", _("Agreed a last working day")
    LEAVE_DECLINED = "lifecycle.leave_declined", _("Declined a request to leave")
    LEAVE_WITHDRAWN = "lifecycle.leave_withdrawn", _("Withdrew a leaving")
    LEAVE_CHANGED = "lifecycle.leave_changed", _("Changed the details of a leaving")
    LEAVE_COMPLETED = "lifecycle.leave_completed", _("Left on the agreed last day")
    HANDOVER_CHANGED = "lifecycle.handover_changed", _("Changed the handover list")
    EXIT_INTERVIEW = "lifecycle.exit_interview", _("Answered the exit questions")
    # Job changes.
    CHANGE_PROPOSED = "lifecycle.change_proposed", _("Proposed a job change")
    CHANGE_APPROVED = "lifecycle.change_approved", _("Approved a job change")
    CHANGE_REJECTED = "lifecycle.change_rejected", _("Rejected a job change")
    CHANGE_CANCELLED = "lifecycle.change_cancelled", _("Cancelled a job change")
    CHANGE_APPLIED = "lifecycle.change_applied", _("A job change took effect")
    CHANGE_FAILED = "lifecycle.change_failed", _("A job change couldn't take effect")
