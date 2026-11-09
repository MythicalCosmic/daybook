"""Celery beat entries of Face ID, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Snapshots past each company's photo_days, every night.
    "faceid-cleanup-photos": {
        "task": "apps.faceid.tasks.cleanup_photos",
        "schedule": crontab(hour=3, minute=40),
    },
}
