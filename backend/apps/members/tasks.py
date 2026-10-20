from celery import shared_task

from apps.members import notifications


@shared_task
def notify_join_request(membership_id: int) -> None:
    notifications.send_join_request(membership_id)


@shared_task
def notify_join_decision(membership_id: int) -> None:
    notifications.send_join_decision(membership_id)


@shared_task
def notify_onboarding_complete(membership_id: int) -> None:
    notifications.send_onboarding_complete(membership_id)


@shared_task
def notify_offboarded(membership_id: int) -> None:
    notifications.send_offboarded(membership_id)
