"""Celery tasks of HR records, queued with `transaction.on_commit` or run by beat.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import (`notify`, `watch`).
"""

from celery import shared_task


@shared_task
def notify_contract_ready(contract_id: int) -> None:
    """The person hears their contract is in force and can be read in the app."""
    from apps.hr import notify

    notify.contract_ready(contract_id)


@shared_task
def watch_expiries() -> int:
    """Documents, contracts and probations reaching a warning step → HR (once per step)."""
    from apps.hr import watch

    return watch.watch_expiries()


@shared_task
def watch_coverage() -> int:
    """Pharmacies open with nobody qualified checked in, and tills opened by someone who isn't
    a qualified pharmacist → the branch manager and the owners (once each)."""
    from apps.hr import watch

    return watch.watch_coverage()


@shared_task
def watch_planned_coverage() -> int:
    """Gaps in the published roster of the coming days → who runs the roster (once per gap)."""
    from apps.hr import watch

    return watch.watch_planned_coverage()


@shared_task
def post_celebrations() -> int:
    """Today's birthdays and work anniversaries → the groups and the person (once each)."""
    from apps.hr import watch

    return watch.post_celebrations()
