"""Celery beat entries of announcements, merged into CELERY_BEAT_SCHEDULE (read by file path)."""

SCHEDULE = {
    # Scheduled announcements go out within a minute of their time.
    "announcements-send-scheduled": {
        "task": "apps.announcements.tasks.send_scheduled",
        "schedule": 60.0,
    },
}
