"""Audit action codes and labels of the people lifecycle (`apps.audit.registry.register`).

Recorded against the person's membership, so Person 360's history shows them; the record's
id, kind and category are in the details, never its text or the person's explanation.
Suspensions are audited by `members.services` itself.
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
