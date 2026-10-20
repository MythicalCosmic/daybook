"""Announcements: publish now or at a time, to positions and branches, pinned and expiring;
read receipts; reminding the people who haven't read one.

The text is Telegram HTML, kept to the tags Telegram allows (`telegram_html.clean`). Receipts
(who it went to) are made when it is sent, so a scheduled announcement reaches the people in
its audience at its time.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.announcements import tasks as jobs
from apps.announcements import telegram_html
from apps.announcements.audit_actions import AnnouncementAction
from apps.announcements.models import Announcement, Receipt
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Branch
from apps.core.exceptions import DomainError
from apps.members import scope
from apps.members import services as members
from apps.members.models import Membership, Position
from apps.members.permissions import Perm

# Telegram allows 4096 characters; this leaves room for the header.
MAX_LENGTH = 3500
# How far ahead an announcement may be scheduled.
MAX_SCHEDULE_AHEAD = timedelta(days=90)
# A scheduled announcement must leave the job a moment to pick it up.
MIN_SCHEDULE_AHEAD = timedelta(minutes=1)


@transaction.atomic
def publish(
    author: Membership,
    text: str,
    position_ids: Iterable[int] = (),
    *,
    branch_ids: Iterable[int] = (),
    scheduled_for: datetime | None = None,
    pinned_until: datetime | None = None,
    expires_at: datetime | None = None,
) -> Announcement:
    """Send an announcement to everyone, or only to people in the given positions and/or
    branches (each filter only when given), now or at `scheduled_for`. Someone who sees only
    some branches announces only to those. `pinned_until` keeps it at the top of the app's
    feed until then; after `expires_at` it disappears from the feed. Returns it (with its
    receipts once sent)."""
    if not author.has_perm(Perm.ANNOUNCE):
        raise PermissionDenied(_("Only managers can send announcements."))
    now = timezone.now()
    text = _valid_text(text)
    positions, branches = _audience_filters(author, position_ids, branch_ids)
    _check_times(now, scheduled_for, pinned_until, expires_at)

    announcement = Announcement.objects.create(
        company_id=author.company_id,
        author=author,
        text=text,
        status=Announcement.Status.SCHEDULED if scheduled_for else Announcement.Status.SENT,
        scheduled_for=scheduled_for,
        pinned_until=pinned_until,
        expires_at=expires_at,
    )
    announcement.positions.set(positions)
    announcement.branches.set(branches)
    if scheduled_for:
        audit.record(
            AnnouncementAction.SCHEDULED,
            company_id=author.company_id,
            actor=author.user,
            target=announcement,
            scheduled_for=scheduled_for.isoformat(),
            positions=[position.name for position in positions],
            branches=[branch.name for branch in branches],
        )
        return announcement
    _send(announcement, now=now)
    return announcement


@transaction.atomic
def update_scheduled(
    announcement: Announcement,
    *,
    by: Membership,
    text: str | None = None,
    position_ids: Iterable[int] | None = None,
    branch_ids: Iterable[int] | None = None,
    scheduled_for: datetime | None = None,
    pinned_until: datetime | None = None,
    expires_at: datetime | None = None,
) -> Announcement:
    """Change an announcement that hasn't gone out yet: text, audience and times."""
    announcement = _lock(announcement)
    _ensure_may_manage(announcement, by)
    if announcement.status != Announcement.Status.SCHEDULED:
        raise DomainError(_("Only a scheduled announcement can be changed."))
    now = timezone.now()
    if text is not None:
        announcement.text = _valid_text(text)
    when = scheduled_for or announcement.scheduled_for
    _check_times(now, when, pinned_until, expires_at)
    announcement.scheduled_for = when
    announcement.pinned_until = pinned_until
    announcement.expires_at = expires_at
    announcement.save()
    if position_ids is not None or branch_ids is not None:
        positions, branches = _audience_filters(
            by,
            position_ids
            if position_ids is not None
            else announcement.positions.values_list("pk", flat=True),
            branch_ids
            if branch_ids is not None
            else announcement.branches.values_list("pk", flat=True),
        )
        announcement.positions.set(positions)
        announcement.branches.set(branches)
    audit.record(
        AnnouncementAction.EDITED,
        company_id=announcement.company_id,
        actor=by.user,
        target=announcement,
        scheduled_for=when.isoformat(),
    )
    return announcement


@transaction.atomic
def cancel_scheduled(announcement: Announcement, *, by: Membership) -> Announcement:
    """Call off a scheduled announcement before it goes out."""
    announcement = _lock(announcement)
    _ensure_may_manage(announcement, by)
    if announcement.status != Announcement.Status.SCHEDULED:
        raise DomainError(_("Only a scheduled announcement can be cancelled."))
    announcement.status = Announcement.Status.CANCELLED
    announcement.save(update_fields=["status", "updated_at"])
    audit.record(
        AnnouncementAction.CANCELLED,
        company_id=announcement.company_id,
        actor=by.user,
        target=announcement,
    )
    return announcement


@transaction.atomic
def pin(announcement: Announcement, *, by: Membership, until: datetime) -> Announcement:
    announcement = _lock(announcement)
    _ensure_may_manage(announcement, by)
    if announcement.status == Announcement.Status.CANCELLED:
        raise DomainError(_("This announcement was cancelled."))
    now = timezone.now()
    if until <= now:
        raise DomainError(_("Pick a moment in the future."))
    if announcement.expires_at and until > announcement.expires_at:
        raise DomainError(_("It can't stay pinned after it expires."))
    announcement.pinned_until = until
    announcement.save(update_fields=["pinned_until", "updated_at"])
    audit.record(
        AnnouncementAction.PINNED,
        company_id=announcement.company_id,
        actor=by.user,
        target=announcement,
        pinned_until=until.isoformat(),
    )
    return announcement


@transaction.atomic
def unpin(announcement: Announcement, *, by: Membership) -> Announcement:
    announcement = _lock(announcement)
    _ensure_may_manage(announcement, by)
    if announcement.pinned_until is None:
        return announcement
    announcement.pinned_until = None
    announcement.save(update_fields=["pinned_until", "updated_at"])
    audit.record(
        AnnouncementAction.UNPINNED,
        company_id=announcement.company_id,
        actor=by.user,
        target=announcement,
    )
    return announcement


@transaction.atomic
def remind_unread(announcement: Announcement, *, by: Membership) -> int:
    """Send the announcement again to everyone who hasn't read it (and can still be reached).
    Returns how many people get the reminder."""
    announcement = _lock(announcement)
    _ensure_may_manage(announcement, by)
    if announcement.status != Announcement.Status.SENT:
        raise DomainError(_("Only a sent announcement can be reminded about."))
    if announcement.expires_at and announcement.expires_at <= timezone.now():
        raise DomainError(_("This announcement has expired."))
    receipts = list(
        visible_receipts(announcement, by).filter(
            read_at__isnull=True, membership__status=Membership.Status.APPROVED
        )
    )
    if not receipts:
        return 0
    now = timezone.now()
    ids = [receipt.pk for receipt in receipts]
    Receipt.objects.filter(pk__in=ids).update(reminded_at=now)
    audit.record(
        AnnouncementAction.REMINDED,
        company_id=announcement.company_id,
        actor=by.user,
        target=announcement,
        people=len(ids),
    )
    transaction.on_commit(partial(jobs.remind_announcement.delay, announcement.pk, ids))
    return len(ids)


def send_due(now: datetime | None = None) -> int:
    """Send every scheduled announcement whose time has come, once each (Celery beat runs this
    every minute). Returns how many went out."""
    now = now or timezone.now()
    due = list(
        Announcement.objects.filter(
            status=Announcement.Status.SCHEDULED,
            scheduled_for__lte=now,
            company__is_active=True,
        )
        .order_by("scheduled_for", "pk")
        .values_list("pk", flat=True)
    )
    sent = 0
    for announcement_id in due:
        with transaction.atomic():
            announcement = (
                Announcement.objects.select_for_update(skip_locked=True)
                .filter(pk=announcement_id, status=Announcement.Status.SCHEDULED)
                .first()
            )
            if announcement is None:
                continue  # sent or cancelled a moment ago
            _send(announcement, now=now)
            sent += 1
    return sent


def read(announcement: Announcement, *, by: Membership) -> Receipt | None:
    """`by` has read the announcement (their receipt is marked once)."""
    receipt = Receipt.objects.filter(announcement=announcement, membership=by).first()
    if receipt is not None and receipt.read_at is None:
        receipt.read_at = timezone.now()
        receipt.save(update_fields=["read_at"])
    return receipt


def audience(
    company_id: int, positions: list[Position], branches: list[Branch] = ()
) -> QuerySet[Membership]:
    """Registered members (suspended people excluded), only of `positions` and only working
    in one of `branches` when any are given."""
    people = Membership.objects.filter(
        company_id=company_id, status=Membership.Status.APPROVED, onboarded_at__isnull=False
    )
    if positions:
        people = people.filter(position__in=positions)
    if branches:
        people = people.filter(pk__in=people.filter(branches__in=branches).values("pk"))
    return people


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
    read_by = [receipt.membership for receipt in receipts if receipt.read_at]
    unread = [receipt.membership for receipt in receipts if receipt.read_at is None]
    return read_by, unread


# Helpers --------------------------------------------------------------------------------


def _send(announcement: Announcement, *, now: datetime) -> None:
    """Make the receipts for the audience as it is now and deliver the copies after commit."""
    author = announcement.author
    positions = list(announcement.positions.all())
    branches = list(announcement.branches.all())
    people = audience(announcement.company_id, positions, branches)
    if author is not None:
        people = people.exclude(pk=author.pk)
    recipients = list(people)
    Receipt.objects.bulk_create(
        (Receipt(announcement=announcement, membership=person) for person in recipients),
        ignore_conflicts=True,
    )
    announcement.status = Announcement.Status.SENT
    announcement.sent_at = now
    announcement.save(update_fields=["status", "sent_at", "updated_at"])
    audit.record(
        AuditLog.Action.ANNOUNCEMENT_SENT,
        company_id=announcement.company_id,
        actor=author.user if author is not None else None,
        target=announcement,
        recipients=len(recipients),
        positions=[position.name for position in positions],
        branches=[branch.name for branch in branches],
    )
    transaction.on_commit(partial(jobs.deliver_announcement.delay, announcement.pk))
    transaction.on_commit(partial(_bump, announcement.company_id))


def _bump(company_id: int) -> None:
    from apps.console import pulse

    pulse.bump(company_id, "announcements.announcements")


def _valid_text(text: str) -> str:
    text = telegram_html.clean(text or "")
    if not telegram_html.plain(text):
        raise DomainError(_("Write something to send."))
    if len(text) > MAX_LENGTH:
        raise DomainError(
            _("That's too long for one message: %(limit)d characters at most.")
            % {"limit": MAX_LENGTH}
        )
    return text


def _audience_filters(
    author: Membership, position_ids: Iterable[int], branch_ids: Iterable[int]
) -> tuple[list[Position], list[Branch]]:
    positions = list(Position.objects.for_company(author.company_id).filter(pk__in=position_ids))
    branches = list(Branch.objects.for_company(author.company_id).filter(pk__in=branch_ids))
    allowed = scope.branch_ids(author)
    if allowed is not None:
        if any(branch.pk not in allowed for branch in branches):
            raise PermissionDenied(_("You can only announce to the branches you manage."))
        if not branches:
            # Someone who sees some branches speaks to those, never to the whole company.
            branches = list(Branch.objects.for_company(author.company_id).filter(pk__in=allowed))
            if not branches:
                raise PermissionDenied(_("You don't manage any branch to announce to."))
    return positions, branches


def _check_times(
    now: datetime,
    scheduled_for: datetime | None,
    pinned_until: datetime | None,
    expires_at: datetime | None,
) -> None:
    starts = scheduled_for or now
    if scheduled_for is not None:
        if scheduled_for < now + MIN_SCHEDULE_AHEAD:
            raise DomainError(_("Schedule it at least a minute from now."))
        if scheduled_for > now + MAX_SCHEDULE_AHEAD:
            raise DomainError(_("Schedule it at most 90 days ahead."))
    if pinned_until is not None and pinned_until <= starts:
        raise DomainError(_("Keep it pinned until after it goes out."))
    if expires_at is not None and expires_at <= starts:
        raise DomainError(_("It must expire after it goes out."))
    if pinned_until and expires_at and pinned_until > expires_at:
        raise DomainError(_("It can't stay pinned after it expires."))


def _lock(announcement: Announcement) -> Announcement:
    return (
        Announcement.objects.select_for_update(of=("self",))
        .select_related("author__user", "company")
        .get(pk=announcement.pk)
    )


def _ensure_may_manage(announcement: Announcement, by: Membership) -> None:
    if by.company_id != announcement.company_id or not by.has_perm(Perm.ANNOUNCE):
        raise PermissionDenied(_("You don't have permission to do this."))
    if not may_see(announcement, by):
        raise PermissionDenied(_("You don't have permission to do this."))


def may_see(announcement: Announcement, viewer: Membership) -> bool:
    """Announcers see every announcement, except someone limited to some branches, who sees
    their own and those sent to one of their branches."""
    allowed = scope.branch_ids(viewer)
    if allowed is None or announcement.author_id == viewer.pk:
        return True
    return announcement.branches.filter(pk__in=allowed).exists()


def visible_receipts(announcement: Announcement, viewer: Membership) -> QuerySet[Receipt]:
    """Receipts `viewer` may see: everyone's with every branch, else people of their branches."""
    receipts = announcement.receipts.all()
    allowed = scope.branch_ids(viewer)
    if allowed is not None:
        in_scope = Membership.objects.filter(
            company_id=announcement.company_id, branches__in=allowed
        ).values("pk")
        receipts = receipts.filter(membership__in=in_scope)
    return receipts
