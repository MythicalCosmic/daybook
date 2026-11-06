"""Celery beat entries of the finance ledger, merged into `CELERY_BEAT_SCHEDULE`.

Read by file path when the settings load: import only the standard library and
`celery.schedules`. Keys must be unique across apps (duplicates stop the settings).
Times are in `CELERY_TIMEZONE` (Asia/Tashkent).
"""

from celery.schedules import crontab

SCHEDULE = {
    # The Central Bank publishes the day's rates in the morning; try every hour of the working
    # day until they are stored (the job does nothing once they are).
    "finance-fetch-exchange-rates": {
        "task": "apps.finance.tasks.fetch_exchange_rates",
        "schedule": crontab(minute=5, hour="8-18"),
    },
    "finance-verify-balances": {
        "task": "apps.finance.tasks.verify_balances",
        "schedule": crontab(hour=3, minute=0),
    },
    # Package I: recurring payments, reminders and budgets.
    "finance-run-recurring": {
        "task": "apps.finance.tasks.run_recurring",
        "schedule": crontab(minute="*/30"),
    },
    "finance-remind-payments": {
        "task": "apps.finance.tasks.remind_payments",
        "schedule": crontab(minute="*/15"),
    },
    "finance-check-budgets": {
        "task": "apps.finance.tasks.check_all_budgets",
        "schedule": crontab(hour=3, minute=30),
    },
}
