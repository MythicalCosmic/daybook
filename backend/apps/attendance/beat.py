"""Celery beat entries of attendance, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Shifts from schedules for today and the next 14 days (idempotent).
    "attendance-generate-shifts": {
        "task": "apps.attendance.tasks.generate_shifts",
        "schedule": crontab(minute="*/30"),
    },
    # Reminders, "your shift started", no-show alerts, "still working?", morning posts.
    "attendance-shift-nudges": {
        "task": "apps.attendance.tasks.shift_nudges",
        "schedule": crontab(minute="*/5"),
    },
    # Forgotten check-outs.
    "attendance-auto-close": {
        "task": "apps.attendance.tasks.auto_close",
        "schedule": crontab(minute="*/15"),
    },
    # Yesterday's shifts without a check-in become absences (acts after 03:00 local time).
    "attendance-close-days": {
        "task": "apps.attendance.tasks.close_days",
        "schedule": crontab(minute="*/30"),
    },
    # Swap requests whose shift has started.
    "attendance-expire-swaps": {
        "task": "apps.attendance.tasks.expire_swaps",
        "schedule": crontab(minute="*/15"),
    },
}
