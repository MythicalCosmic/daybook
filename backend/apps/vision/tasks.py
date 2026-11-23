"""Celery tasks of Ko‘z: Telegram after a change commits (`apps.vision.notify`) and the scheduled
jobs (beat.py). Services queue these; this module never imports `services` at its top (the jobs
import it when they run)."""

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from celery import shared_task

from apps.vision import notify

RETRYING = {
    "bind": True,
    "autoretry_for": (TelegramNetworkError, TelegramServerError),
    "retry_backoff": True,
    "max_retries": 5,
}


@shared_task
def announce_alert(alert_id: int) -> int:
    """One job per person, so one slow chat never holds the others back."""
    people = notify.recipients_of(alert_id)
    for member_id, reason in people:
        send_alert_copy.delay(alert_id, member_id, reason)
    return len(people)


@shared_task(**RETRYING)
def send_alert_copy(self, alert_id: int, member_id: int, reason: str) -> None:
    try:
        notify.send_copy(alert_id, member_id, reason)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc


@shared_task
def refresh_alert(alert_id: int) -> int:
    return notify.refresh(alert_id)


@shared_task
def resolve_stale_alerts() -> int:
    from apps.vision import services

    return services.resolve_stale()


@shared_task
def check_offline_boxes() -> int:
    from apps.vision import services

    return services.check_offline()


@shared_task
def offer_clips_again() -> int:
    from apps.vision import services

    return services.expire_offers()


@shared_task
def prune() -> dict:
    from apps.vision import services

    return services.prune()
