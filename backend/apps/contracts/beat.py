"""Celery beat entries of business contracts, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps.
"""

from celery.schedules import crontab

SCHEDULE = {
    # Hourly: statuses follow the dates, auto-renewing contracts move on after their last day,
    # and from each company's morning report time the reminders go out (each once).
    "contracts-watch": {
        "task": "apps.contracts.tasks.watch_contracts",
        "schedule": crontab(minute=23),
    },
}
