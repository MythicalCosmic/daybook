from celery import shared_task
from django.core.cache import cache

from apps.members import notifications, schedule

# A note about people joining through a team link waits this long after the first join, so
# everyone who scans the code at a meeting is in one message.
LINK_REPORT_DELAY = 90


@shared_task
def notify_join_request(membership_id: int) -> None:
    notifications.send_join_request(membership_id)


@shared_task
def notify_join_decision(membership_id: int) -> None:
    notifications.send_join_decision(membership_id)


@shared_task
def notify_joined(membership_id: int) -> None:
    notifications.send_joined(membership_id)


def queue_link_report(link_id: int) -> None:
    """The first join of a burst queues the note; joins within the delay ride along with it."""
    if cache.add(f"members:link-report:{link_id}", 1, timeout=LINK_REPORT_DELAY):
        report_link_joins.apply_async((link_id,), countdown=LINK_REPORT_DELAY)


@shared_task
def report_link_joins(link_id: int) -> None:
    schedule.report_link_joins(link_id)


@shared_task
def notify_onboarding_complete(membership_id: int) -> None:
    notifications.send_onboarding_complete(membership_id)


@shared_task
def notify_offboarded(membership_id: int) -> None:
    notifications.send_offboarded(membership_id)


@shared_task
def notify_suspended(membership_id: int) -> None:
    notifications.send_suspended(membership_id)


@shared_task
def notify_reinstated(membership_id: int) -> None:
    notifications.send_reinstated(membership_id)


@shared_task
def reinstate_finished_suspensions() -> None:
    schedule.reinstate_finished_suspensions()
