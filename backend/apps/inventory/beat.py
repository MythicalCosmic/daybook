"""Celery beat entries of stock, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
"""

from celery.schedules import crontab

SCHEDULE = {
    # Expiry steps, the monthly shelf check, the mandatory list, destruction dates, the
    # controlled register's month: hourly, acting once per company day from 06:00 local.
    "inventory-daily-scan": {
        "task": "apps.inventory.tasks.daily_scan",
        "schedule": crontab(minute=7),
    },
    "inventory-recompute-low-stock": {
        "task": "apps.inventory.tasks.recompute_low_stock",
        "schedule": crontab(minute=37),
    },
    # Receipts waiting more than two days (10:23 in Tashkent).
    "inventory-remind-unposted": {
        "task": "apps.inventory.tasks.remind_unposted",
        "schedule": crontab(minute=23, hour=5),
    },
}
