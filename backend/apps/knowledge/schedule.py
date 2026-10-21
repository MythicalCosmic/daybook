"""Knowledge base jobs that run on their own, from Celery beat (apps/knowledge/beat.py).

A plain module, so `apps.knowledge.tasks` stays free of the services: the service is looked up
only when the job runs.
"""


def remind_unread() -> int:
    """One reminder per page and version to the readers who haven't confirmed it."""
    from apps.knowledge import services

    return services.remind_due()
