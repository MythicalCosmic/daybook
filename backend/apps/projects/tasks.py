"""Celery tasks of projects, queued with `transaction.on_commit` or run by beat.

Thin wrappers: services import this module to queue jobs, so it never imports
`services`; the work itself lives in plain modules both can import.
"""

from celery import shared_task


@shared_task
def watch_health() -> int:
    """Hourly: projects that went off track and missed milestones, told once."""
    from apps.projects import jobs

    return jobs.watch_health()


@shared_task
def nudge_leads() -> int:
    """Hourly: acts once a week per company, on its nudge day after 10:00 local time."""
    from apps.projects import jobs

    return jobs.nudge_leads()
