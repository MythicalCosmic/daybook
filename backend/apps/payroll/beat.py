"""Celery beat entries of payroll, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # On the 1st after 06:00 local: last month's draft run, calculated (once).
    "payroll-prepare-runs": {
        "task": "apps.payroll.tasks.prepare_runs",
        "schedule": crontab(minute=7),
    },
    # Pay day morning, the month not paid yet: the payers and owners hear (once a month).
    "payroll-pay-day-reminders": {
        "task": "apps.payroll.tasks.pay_day_reminders",
        "schedule": crontab(minute=12),
    },
    # Daily per-unit rules after attendance closed yesterday (idempotent rule keys).
    "payroll-evaluate-daily-rules": {
        "task": "apps.payroll.tasks.evaluate_daily_rules",
        "schedule": crontab(minute=17),
    },
}
