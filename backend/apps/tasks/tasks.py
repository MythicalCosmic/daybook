from zoneinfo import ZoneInfo

from celery import shared_task
from django.utils import timezone

from apps.companies.models import Company
from apps.tasks import generation, notifications


@shared_task
def generate_daily_tasks() -> None:
    for company in Company.objects.filter(is_active=True):
        today = timezone.localdate(timezone=ZoneInfo(company.timezone))
        generation.generate_daily_tasks(company, today)


@shared_task
def notify_task_assigned(task_id: int) -> None:
    notifications.send_task_assigned(task_id)


@shared_task
def notify_task_completed(task_id: int) -> None:
    notifications.send_task_completed(task_id)


@shared_task
def notify_task_reviewed(task_id: int) -> None:
    notifications.send_task_reviewed(task_id)
