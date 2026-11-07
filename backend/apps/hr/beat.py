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
    # A pharmacy without a qualified pharmacist checked in, a till opened by someone who isn't
    # one (docs/PLAN-OWNER.md §14.9).
    "hr-watch-coverage": {
        "task": "apps.hr.tasks.watch_coverage",
        "schedule": crontab(minute="*/5"),
    },
    # Gaps in the published roster of the next days.
    "hr-watch-planned-coverage": {
        "task": "apps.hr.tasks.watch_planned_coverage",
        "schedule": crontab(minute=23),
    },
}
