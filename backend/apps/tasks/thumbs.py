"""Proof photo previews: a 400 px WebP next to each proof (docs/PLAN-OWNER.md §1.3, §2.8), so
lists, the photo wall and the mini app load small images. Public `/media`, unguessable names."""

import logging

from apps.core import uploads
from apps.tasks.models import Task

logger = logging.getLogger(__name__)

THUMB_SIDE = 400


def make_proof_thumb(task_id: int) -> bool:
    """Make (or remake) the preview of the task's proof photo. True when one was saved."""
    task = Task.objects.filter(pk=task_id).only("pk", "company_id", "proof_photo").first()
    if task is None or not task.proof_photo:
        return False
    try:
        with task.proof_photo.open("rb") as photo:
            thumb = uploads.make_thumb(photo, side=THUMB_SIDE)
    except (OSError, uploads.InvalidUpload) as exc:
        logger.warning("No thumbnail for the proof of task %s: %s", task_id, exc)
        return False
    task.proof_thumb.save(thumb.name, thumb, save=False)
    Task.objects.filter(pk=task.pk).update(proof_thumb=task.proof_thumb.name)
    return True


def missing_thumbs(limit: int = 500) -> int:
    """Previews for proofs uploaded before thumbnails existed (`manage.py`-free backfill)."""
    ids = list(
        Task.objects.exclude(proof_photo="")
        .filter(proof_thumb="")
        .order_by("-completed_at")
        .values_list("pk", flat=True)[:limit]
    )
    return sum(make_proof_thumb(task_id) for task_id in ids)
