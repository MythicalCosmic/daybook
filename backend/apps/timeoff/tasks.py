from celery import shared_task

from apps.timeoff import notifications


@shared_task
def notify_time_off_requested(time_off_id: int) -> None:
    notifications.send_request(time_off_id)


@shared_task
def notify_time_off_decided(time_off_id: int) -> None:
    notifications.send_decision(time_off_id)


@shared_task
def notify_time_off_recorded(time_off_id: int) -> None:
    notifications.send_recorded(time_off_id)


@shared_task
def notify_time_off_revoked(time_off_id: int) -> None:
    notifications.send_revoked(time_off_id)
