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
