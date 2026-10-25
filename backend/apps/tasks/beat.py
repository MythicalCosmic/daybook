"""Celery beat entries of tasks, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # "If nobody reviews it within N hours, accept it automatically": checked every 10 minutes.
    "tasks-accept-overdue-reviews": {
        "task": "apps.tasks.tasks.accept_overdue_reviews",
        "schedule": crontab(minute="*/10"),
    },
    # Each proof gets its preview right after upload; this picks up older proofs and lost jobs.
    "tasks-backfill-proof-thumbs": {
        "task": "apps.tasks.tasks.backfill_proof_thumbs",
        "schedule": crontab(minute=17),
    },
}
