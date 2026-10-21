"""Celery beat entries of projects, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    "projects-watch-health": {
        "task": "apps.projects.tasks.watch_health",
        "schedule": crontab(minute=7),
    },
    "projects-nudge-leads": {
        "task": "apps.projects.tasks.nudge_leads",
        "schedule": crontab(minute=12),
    },
}
