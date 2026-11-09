"""Celery tasks of Face ID (run by beat)."""

from celery import shared_task


@shared_task
def cleanup_photos() -> int:
    """Snapshots older than each company's `photo_days` are deleted."""
    from apps.faceid import services

    return services.cleanup_photos()
