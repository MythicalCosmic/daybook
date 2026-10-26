"""Membership changes that happen on their own, run by Celery beat (apps/members/beat.py).

A plain module, so `apps.members.tasks` stays free of the services it is queued from: the
services import `tasks`, so the service is looked up only when the job runs.
"""


def reinstate_finished_suspensions() -> int:
    """Give access back to everyone whose suspension's last day has passed."""
    from apps.members import services  # services import apps.members.tasks, which imports us

    return services.reinstate_finished_suspensions()


def report_link_joins(link_id: int) -> int:
    """The note to approvers about a burst of people joining through a team link."""
    from apps.members import join_links  # it imports the services, which import us

    return join_links.report_joins(link_id)
