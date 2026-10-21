"""Celery beat entries of accounts, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Sundays at 04:00: profile photos for avatars (one batch per run).
    "accounts-refresh-telegram-photos": {
        "task": "apps.accounts.tasks.refresh_telegram_photos",
        "schedule": crontab(hour=4, minute=0, day_of_week="sun"),
    },
}
