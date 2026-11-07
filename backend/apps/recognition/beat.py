"""Celery beat entries of recognition, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Points for the last two days' work done on time (idempotent: a missed run catches up).
    "recognition-task-points": {
        "task": "apps.recognition.tasks.task_points",
        "schedule": crontab(minute=23),
    },
    # The badge sweep and the monthly top three, in each company's small hours, once a night.
    "recognition-nightly": {
        "task": "apps.recognition.tasks.nightly",
        "schedule": crontab(minute=41),
    },
}
