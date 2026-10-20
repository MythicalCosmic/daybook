from celery import shared_task
from django.utils import timezone

from apps.announcements import notifications


@shared_task
def deliver_announcement(announcement_id: int) -> None:
    notifications.deliver(announcement_id)


@shared_task
def follow_up_announcements() -> None:
    notifications.follow_up(timezone.now())
