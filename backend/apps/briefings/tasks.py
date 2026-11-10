"""Celery tasks of briefings, queued with `transaction.on_commit`.

Thin wrappers: services import this module to queue jobs, so it never imports `services`;
the work itself lives in plain modules both can import (`apps.briefings.reviews`).
"""

from celery import shared_task


@shared_task
def send_due() -> int:
    """The beat: the weekly and monthly reviews that are due (from the templates; where
    Maslahatchi writes them, its own run on the ai queue sends them)."""
    from apps.briefings import reviews

    return reviews.tick()


@shared_task(queue="ai")
def regenerate(membership_id: int, kind: str) -> int | None:
    """ "Write it again" with Claude (the dashboard), on the ai queue."""
    from django.utils import timezone

    from apps.briefings import reviews
    from apps.core.exceptions import DomainError
    from apps.members.models import Membership

    member = (
        Membership.objects.select_related("user", "company", "role")
        .filter(pk=membership_id, status=Membership.Status.APPROVED)
        .first()
    )
    if member is None:
        return None
    try:
        return reviews.regenerate_for(member, kind, timezone.now(), use_ai=True).pk
    except DomainError:
        return None
