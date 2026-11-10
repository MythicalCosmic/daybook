"""Celery beat entries of business goals, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
Times are in `CELERY_TIMEZONE` (Asia/Tashkent).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Each goal's weekly point, before the owners' Monday briefing.
    "goals-weekly": {
        "task": "apps.goals.tasks.weekly_goals",
        "schedule": crontab(hour=7, minute=10, day_of_week="mon"),
    },
}
