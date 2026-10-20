from celery import shared_task
from django.utils import timezone

from apps.announcements import notifications


@shared_task
def deliver_announcement(announcement_id: int) -> None:
    notifications.deliver(announcement_id)


@shared_task
def follow_up_announcements() -> None:
    notifications.follow_up(timezone.now())


@shared_task
def remind_announcement(announcement_id: int, receipt_ids: list[int]) -> None:
    notifications.remind(announcement_id, receipt_ids)


@shared_task
def send_scheduled() -> None:
    """Every minute: send the scheduled announcements whose time has come."""
    from apps.announcements import services

    services.send_due()
