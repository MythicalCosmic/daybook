"""Celery beat entries of the company calendar, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

SCHEDULE = {
    "agenda-send-event-reminders": {
        "task": "apps.agenda.tasks.send_event_reminders",
        "schedule": 60.0,
    },
}
