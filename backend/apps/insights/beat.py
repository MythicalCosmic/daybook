"""Celery beat entries of insights, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Each company's rules run in its own morning, noon and evening (07:00, 13:00, 19:00 company
    # time, `engine.RUN_HOURS`); in between, urgent insights wait for the quiet hours to end.
    "insights-detect": {
        "task": "apps.insights.tasks.detect",
        "schedule": crontab(minute="5,35"),
    },
}
