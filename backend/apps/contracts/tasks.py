"""Celery tasks of business contracts: thin wrappers over `watch`."""

from celery import shared_task


@shared_task
def watch_contracts() -> int:
    from apps.contracts import watch

    return watch.watch_all()
