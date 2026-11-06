"""Celery beat entries of fixed assets, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps.
"""

from celery.schedules import crontab

SCHEDULE = {
    # The month that just ended, posted and booked (idempotent: hourly in the small hours, so a
    # missed run catches up the same night).
    "assets-post-depreciation": {
        "task": "apps.assets.tasks.post_depreciation",
        "schedule": crontab(minute=17, hour="0-5"),
    },
    # Warranties, services, instrument checks and insurance coming up (from 08:00 local).
    "assets-watch-upkeep": {
        "task": "apps.assets.tasks.watch_upkeep",
        "schedule": crontab(minute=11),
    },
}
