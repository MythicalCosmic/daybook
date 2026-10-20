from collections.abc import Iterable
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.announcements import tasks as jobs
from apps.announcements.models import Announcement, Receipt
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.members import services as members
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

# Telegram allows 4096 characters; this leaves room for the header.
MAX_LENGTH = 3500


@transaction.atomic
def publish(author: Membership, text: str, position_ids: Iterable[int] = ()) -> Announcement:
    """Send an announcement to everyone, or to the given positions. Returns it with receipts."""
    if not author.has_perm(Perm.ANNOUNCE):
        raise PermissionDenied(_("Only managers can send announcements."))
    text = text.strip()
    if not text:
        raise DomainError(_("Write something to send."))
    if len(text) > MAX_LENGTH:
        raise DomainError(
            _("That's too long for one message: %(limit)d characters at most.")
            % {"limit": MAX_LENGTH}
        )
    positions = list(Position.objects.for_company(author.company_id).filter(pk__in=position_ids))
    announcement = Announcement.objects.create(
        company_id=author.company_id, author=author, text=text
    )
    announcement.positions.set(positions)
    recipients = list(audience(author.company_id, positions).exclude(pk=author.pk))
    Receipt.objects.bulk_create(
        Receipt(announcement=announcement, membership=person) for person in recipients
    )
    audit.record(
        AuditLog.Action.ANNOUNCEMENT_SENT,
        company_id=author.company_id,
        actor=author.user,
        target=announcement,
        recipients=len(recipients),
        positions=[position.name for position in positions],
    )
    transaction.on_commit(partial(jobs.deliver_announcement.delay, announcement.pk))
    return announcement


def audience(company_id: int, positions: list[Position]) -> QuerySet[Membership]:
    """Registered members, only of `positions` when any are given."""
    people = Membership.objects.filter(
        company_id=company_id, status=Membership.Status.APPROVED, onboarded_at__isnull=False
    )
    return people.filter(position__in=positions) if positions else people


def mark_read(announcement_id: int, user: User) -> Receipt | None:
    receipt = (
        Receipt.objects.select_related("announcement__author")
        .filter(announcement_id=announcement_id, membership__user=user)
        .first()
    )
    if receipt is not None and receipt.read_at is None:
        receipt.read_at = timezone.now()
        receipt.save(update_fields=["read_at"])
    return receipt


def readers(announcement_id: int, user: User) -> tuple[list[Membership], list[Membership]]:
    """Who has read the announcement and who hasn't, for its author or another announcer."""
    announcement = (
        Announcement.objects.select_related("company", "author").filter(pk=announcement_id).first()
    )
    if announcement is None:
        raise DomainError(_("This announcement no longer exists."))
    is_author = announcement.author is not None and announcement.author.user_id == user.pk
    if not is_author:
        members.ensure_can(user, announcement.company, Perm.ANNOUNCE)
    receipts = announcement.receipts.select_related("membership__user").order_by(
        "membership__first_name", "membership__last_name"
    )
    read = [receipt.membership for receipt in receipts if receipt.read_at]
    unread = [receipt.membership for receipt in receipts if receipt.read_at is None]
    return read, unread
