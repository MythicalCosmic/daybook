"""Celery beat entries of memberships, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # A suspension ends at the start of the day after its last day, in the company's timezone.
    "members-reinstate-finished-suspensions": {
        "task": "apps.members.tasks.reinstate_finished_suspensions",
        "schedule": crontab(minute="*/15"),
    },
}
