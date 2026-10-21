"""Celery tasks of attendance, queued with `transaction.on_commit` or run by beat.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import (`jobs`, imported when a task runs).
"""

from celery import shared_task


@shared_task
def generate_shifts() -> int:
    """Today + 14 days from schedules; skips holidays; leave for approved time off; never
    touches manual or swapped shifts."""
    from apps.attendance import jobs

    return jobs.generate_shifts()


@shared_task
def shift_nudges() -> int:
    """Pre-shift reminder, "your shift started", no-show alert, "still working?", morning post."""
    from apps.attendance import jobs

    return jobs.shift_nudges()


@shared_task
def auto_close() -> int:
    """Forgotten check-outs closed at the shift's end, flagged, person asked."""
    from apps.attendance import jobs

    return jobs.auto_close()


@shared_task
def close_days() -> int:
    """Past shifts without a check-in become absences (after 03:00 local)."""
    from apps.attendance import jobs

    return jobs.close_days()


@shared_task
def expire_swaps() -> int:
    """Swap requests whose shift has started expire; people are told."""
    from apps.attendance import jobs

    return jobs.expire_swaps()
