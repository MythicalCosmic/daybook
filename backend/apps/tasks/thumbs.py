"""Proof photo previews: a 400 px WebP next to each proof (docs/PLAN-OWNER.md §1.3, §2.8), so
lists, the photo wall and the mini app load small images. Public `/media`, unguessable names."""

import logging

from apps.core import uploads
from apps.tasks.models import Task

logger = logging.getLogger(__name__)

THUMB_SIDE = 400


def make_proof_thumb(task_id: int) -> bool:
    """Make the preview of the task's proof photo. True when one was saved.

    Idempotent: a task that already has its preview is left alone (a new photo clears the old
    preview in `services.complete_task`), so a retried or duplicated job writes no second file.
    """
    task = (
        Task.objects.filter(pk=task_id)
        .only("pk", "company_id", "proof_photo", "proof_thumb")
        .first()
    )
    if task is None or not task.proof_photo or task.proof_thumb:
        return False
    photo_name = task.proof_photo.name
    try:
        with task.proof_photo.open("rb") as photo:
            thumb = uploads.make_thumb(photo, side=THUMB_SIDE)
    except (OSError, uploads.InvalidUpload) as exc:
        logger.warning("No thumbnail for the proof of task %s: %s", task_id, exc)
        return False
    task.proof_thumb.save(thumb.name, thumb, save=False)
    # Only onto the photo it was made from, and only if no other job got there first.
    saved = Task.objects.filter(pk=task.pk, proof_photo=photo_name, proof_thumb="").update(
        proof_thumb=task.proof_thumb.name
    )
    if not saved:
        task.proof_thumb.delete(save=False)
    return bool(saved)


def missing_thumbs(limit: int = 500) -> int:
    """Previews for proofs uploaded before thumbnails existed (`manage.py`-free backfill)."""
    ids = list(
        Task.objects.exclude(proof_photo="")
        .filter(proof_thumb="")
        .order_by("-completed_at")
        .values_list("pk", flat=True)[:limit]
    )
    return sum(make_proof_thumb(task_id) for task_id in ids)
