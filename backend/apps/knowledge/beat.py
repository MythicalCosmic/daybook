"""Celery beat entries of the knowledge base, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    "knowledge-remind-unread": {
        "task": "apps.knowledge.tasks.remind_unread",
        "schedule": crontab(minute=25),
    },
}
