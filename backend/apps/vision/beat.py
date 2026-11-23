"""Celery beat entries of Ko‘z, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Boxes with no live report for 5 minutes: the managers hear about it.
    "vision-check-offline-boxes": {
        "task": "apps.vision.tasks.check_offline_boxes",
        "schedule": crontab(),  # every minute
    },
    # Clips offered 5 minutes ago without a video: offered again, or failed after three offers.
    "vision-offer-clips-again": {
        "task": "apps.vision.tasks.offer_clips_again",
        "schedule": crontab(),
    },
    # Open alerts with no news for 2 hours close.
    "vision-resolve-stale-alerts": {
        "task": "apps.vision.tasks.resolve_stale_alerts",
        "schedule": crontab(minute="*/5"),
    },
    # Minute stats, photos and clips past each company's keep days, every night.
    "vision-prune": {
        "task": "apps.vision.tasks.prune",
        "schedule": crontab(hour=3, minute=50),
    },
}
