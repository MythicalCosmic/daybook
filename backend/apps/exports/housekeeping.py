"""Daily clean-up of export files (`exports.tasks.prune_exports`)."""

import logging
from datetime import timedelta

from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.exports.models import Export

logger = logging.getLogger(__name__)

KEEP = timedelta(days=7)
# An export still "running" this long after it was asked for died with its worker.
STUCK_AFTER = timedelta(hours=6)


def prune_exports() -> int:
    """Delete exports (and their files) older than `KEEP`; mark stuck ones failed."""
    now = timezone.now()
    removed = 0
    for export in Export.objects.filter(created_at__lt=now - KEEP).iterator():
        if export.file:
            export.file.delete(save=False)
        export.delete()
        removed += 1
    stuck = Export.objects.filter(
        status__in=(Export.Status.PENDING, Export.Status.RUNNING),
        created_at__lt=now - STUCK_AFTER,
    ).select_related("requested_by__user")
    for export in stuck:
        with translation.override(export.requested_by.user.language):
            export.error = _("This export took too long. Please try again.")
        export.status = Export.Status.FAILED
        export.finished_at = now
        export.save(update_fields=["status", "error", "finished_at", "updated_at"])
    if removed:
        logger.info("Pruned %s old exports", removed)
    return removed
