"""Membership changes that happen on their own, run by Celery beat (apps/members/beat.py).

A plain module, so `apps.members.tasks` stays free of the services it is queued from: the
services import `tasks`, so the service is looked up only when the job runs.
"""


def reinstate_finished_suspensions() -> int:
    """Give access back to everyone whose suspension's last day has passed."""
    from apps.members import services  # services import apps.members.tasks, which imports us

    return services.reinstate_finished_suspensions()
