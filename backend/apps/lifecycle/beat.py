"""Celery beat entries of the people lifecycle, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # A last day's morning note (09:00) and its evening (20:00, or after the last shift): the
    # person leaves and payroll prepares the final payslip, in each company's time.
    "lifecycle-leaving": {
        "task": "apps.lifecycle.tasks.run_leaving",
        "schedule": crontab(minute="*/15"),
    },
    # Approved job changes take effect on their day, in each company's time.
    "lifecycle-job-changes": {
        "task": "apps.lifecycle.tasks.apply_job_changes",
        "schedule": crontab(minute="2-59/15"),
    },
}
