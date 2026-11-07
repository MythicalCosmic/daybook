"""Celery beat entries of learning, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
Each job works out per company what is due in the company's own time, so they run often and
do nothing twice (docs/PLAN-LEARNING.md §9).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Q1: mandatory courses reach everyone in their audience (new people, new positions).
    "learning-sync-audiences": {
        "task": "apps.learning.tasks.sync_audiences",
        "schedule": crontab(minute=7),
    },
    # Q1: deadlines (soon, late, the manager), at the company's morning hour.
    "learning-reminders": {
        "task": "apps.learning.tasks.send_reminders",
        "schedule": crontab(minute=17),
    },
    # Q1: courses that renew start their next cycle.
    "learning-renewals": {
        "task": "apps.learning.tasks.renew_due",
        "schedule": crontab(minute=40, hour=2),
    },
    # Q1: uploads nobody finished, and their pieces.
    "learning-clean-uploads": {
        "task": "apps.learning.tasks.clean_uploads",
        "schedule": crontab(minute=10, hour=3),
    },
    # Q2: the question of the day, at each company's time.
    "learning-daily-questions": {
        "task": "apps.learning.tasks.send_daily_questions",
        "schedule": crontab(minute="*/10"),
    },
    # Q2: regular checks start, remind and close.
    "learning-checks": {
        "task": "apps.learning.tasks.run_checks",
        "schedule": crontab(minute="3-59/10"),
    },
    # Q2: attempts whose time ran out are graded with what was answered.
    "learning-expire-attempts": {
        "task": "apps.learning.tasks.expire_attempts",
        "schedule": crontab(minute="*/5"),
    },
}
