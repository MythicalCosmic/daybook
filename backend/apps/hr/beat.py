"""Celery beat entries of HR records, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Documents, contracts and probations reaching a warning step (from the morning on).
    "hr-watch-expiries": {
        "task": "apps.hr.tasks.watch_expiries",
        "schedule": crontab(minute=7),
    },
    # Birthdays and work anniversaries at the morning report time, once each.
    "hr-post-celebrations": {
        "task": "apps.hr.tasks.post_celebrations",
        "schedule": crontab(minute="*/15"),
    },
}
