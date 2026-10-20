"""Celery beat entries of owner sign-in, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # simplejwt's flushexpiredtokens, plus device sessions that can never refresh again.
    "signin-flush-expired-tokens": {
        "task": "apps.signin.tasks.flush_expired_tokens",
        "schedule": crontab(hour=3, minute=20),
    },
}
