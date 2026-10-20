"""Celery tasks of exports, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from celery import shared_task

from apps.exports import build, housekeeping


@shared_task
def build_export(export_id: int) -> None:
    """Build the xlsx/csv file; send it to Telegram only when the requester opted in."""
    build.build(export_id)


@shared_task
def prune_exports() -> None:
    """Daily: exports older than 7 days, files included."""
    housekeeping.prune_exports()
