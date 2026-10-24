import logging
from zoneinfo import ZoneInfo

from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from celery import shared_task
from django.utils import timezone

from apps.companies.models import Company
from apps.tasks import generation, notifications

logger = logging.getLogger(__name__)


@shared_task
def generate_daily_tasks() -> None:
    for company in Company.objects.filter(is_active=True):
        today = timezone.localdate(timezone=ZoneInfo(company.timezone))
        generation.generate_daily_tasks(company, today)


@shared_task
def notify_task_assigned(task_id: int) -> None:
    notifications.send_task_assigned(task_id)


@shared_task
def notify_task_completed(task_id: int, completed_at: str | None = None) -> None:
    """Queued after the undo window; `completed_at` is the completion it was queued for."""
    notifications.send_task_completed(task_id, completed_at)


@shared_task(
    bind=True,
    autoretry_for=(TelegramNetworkError, TelegramServerError),
    retry_backoff=True,
    max_retries=5,
)
def send_task_message(self, task_id, member_id, kind, chat_id, text, reply_markup=None, photo=None):
    """One task message, its id kept so every copy can be drawn again later (research R1 C5)."""
    try:
        notifications.deliver(task_id, member_id, kind, chat_id, text, reply_markup, photo)
    except TelegramRetryAfter as exc:
        raise self.retry(countdown=exc.retry_after) from exc
    except TelegramForbiddenError:
        logger.info("Chat %s blocked the employee bot or never started it", chat_id)


@shared_task
def refresh_task_messages(task_id: int) -> None:
    """The task changed: its copies in people's chats follow."""
    notifications.refresh_messages(task_id)


@shared_task
def refresh_card(task_id: int, member_id: int, chat_id: int, message_id: int) -> None:
    """Draw a task card again where it is, e.g. once its Undo button's minute is over."""
    notifications.refresh_card(task_id, member_id, chat_id, message_id)


@shared_task
def notify_comment(comment_id: int, mentioned_ids: list[int]) -> None:
    notifications.send_comment(comment_id, mentioned_ids)


@shared_task
def notify_due_changed(task_id: int, old_due: str | None, by_id: int) -> None:
    notifications.send_due_changed(task_id, old_due, by_id)


@shared_task
def notify_task_cancelled(task_id: int, by_id: int) -> None:
    notifications.send_task_cancelled(task_id, by_id)


@shared_task
def notify_task_taken_away(task_id: int, previous_id: int, by_id: int) -> None:
    notifications.send_task_taken_away(task_id, previous_id, by_id)


@shared_task
def notify_blocked(task_id: int, giver_ids: list[int]) -> None:
    notifications.send_blocked(task_id, giver_ids)


@shared_task
def notify_blocker_resolved(task_id: int, action: str, by_id: int, reporter_id: int) -> None:
    notifications.send_blocker_resolved(task_id, action, by_id, reporter_id)


@shared_task
def notify_extension_decided(task_id: int, approved: bool, by_id: int, until: str) -> None:
    notifications.send_extension_decided(task_id, approved, by_id, until)


@shared_task
def notify_task_reviewed(task_id: int) -> None:
    notifications.send_task_reviewed(task_id)


@shared_task
def notify_work_handed_back(member_id: int, handed_back: list) -> None:
    notifications.send_work_handed_back(member_id, handed_back)


@shared_task
def notify_nudge(task_id: int, by_id: int) -> None:
    notifications.send_nudge(task_id, by_id)


@shared_task
def notify_onboarding(member_id: int, task_ids: list[int]) -> None:
    notifications.send_onboarding(member_id, task_ids)


@shared_task
def make_proof_thumb(task_id: int) -> None:
    """The 400 px WebP preview of a task's proof photo (docs/PLAN-OWNER.md §10.1)."""
    from apps.tasks import thumbs

    thumbs.make_proof_thumb(task_id)


@shared_task
def backfill_proof_thumbs() -> int:
    """Previews for older proofs (and any whose job was lost), a batch at a time."""
    from apps.tasks import thumbs

    return thumbs.missing_thumbs()


@shared_task
def assign_onboarding(membership_id: int) -> None:
    """A new person's onboarding tasks, on `member_approved` (docs/PLAN-OWNER.md §10.1)."""
    from apps.members.models import Membership
    from apps.tasks import onboarding

    membership = Membership.objects.filter(pk=membership_id).first()
    if membership is not None:
        onboarding.assign_onboarding(membership)
