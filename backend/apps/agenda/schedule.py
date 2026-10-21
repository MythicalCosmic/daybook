"""Calendar jobs that run on their own, from Celery beat (apps/agenda/beat.py).

A plain module, so `apps.agenda.tasks` stays free of the services: the service is looked up
only when the job runs.
"""


def send_event_reminders() -> int:
    """Reminders to attendees whose event is coming up (one per person and occurrence)."""
    from apps.agenda import services

    return services.send_due_reminders()
