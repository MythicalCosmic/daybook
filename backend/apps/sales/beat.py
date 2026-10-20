"""Celery beat entries of sales and cash, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Safety net for the per-close rebuilds of DailySales.
    "sales-rollup-yesterday": {
        "task": "apps.sales.tasks.rollup_yesterday",
        "schedule": crontab(minute=30, hour=4),
    },
    # Branch not opened, till left open, handover unconfirmed, cash over the limit.
    "sales-scan-operational": {
        "task": "apps.sales.tasks.scan_operational",
        "schedule": crontab(minute="*/5"),
    },
    # The day's sales in the groups that want them, once per company and business day.
    "sales-post-evening": {
        "task": "apps.sales.tasks.post_evening_sales",
        "schedule": crontab(minute="*/15"),
    },
}
