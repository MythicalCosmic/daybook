"""Celery beat entries of briefings, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # The weekly and monthly business reviews, in the first run after their time in each
    # company's own clock (BriefingSettings), once per period.
    "briefings-send-due": {
        "task": "apps.briefings.tasks.send_due",
        "schedule": crontab(minute="*/10"),
    },
}
