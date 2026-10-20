from celery import shared_task

from apps.reminders import engine


@shared_task
def send_due_reminders() -> int:
    return engine.send_due_reminders()
