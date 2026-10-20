"""Celery beat entries of exports, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Export files live 7 days.
    "exports-prune": {
        "task": "apps.exports.tasks.prune_exports",
        "schedule": crontab(hour=3, minute=10),
    },
}
