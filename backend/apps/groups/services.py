from collections.abc import Iterable
from functools import partial

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Branch, Company
from apps.core.exceptions import DomainError
from apps.groups import tasks as group_jobs
from apps.groups.models import (
    DEFAULT_EVENTS,
    EVENT_FEATURES,
    GroupEvent,
    TelegramGroup,
    available_events,
)
from apps.members import services as members
from apps.members.models import Membership, Position
from apps.members.permissions import Perm


def broadcast(
    company_id: int,
    event: GroupEvent,
    text: str,
    *,
    position_ids: Iterable[int] = (),
    branch_id: int | None = None,
    photo: str | None = None,
    photo_storage: str = "default",
) -> int:
    """Post `text` (HTML, already in the company's language) to every group of the company
    that wants `event`. Returns how many groups it was queued for.

    News about people in some positions reaches groups without a position filter and groups
    narrowed to one of those positions; news from a branch reaches groups without a branch
    filter and groups of that branch. News about nobody in particular (no positions, no
    branch) reaches every group that wants the event. An event whose module is off goes
    nowhere. `photo` is a path in `photo_storage` ("default" public media or "private").
    Posts are queued once the caller's transaction commits (at once outside one).
    """
    if photo_storage not in ("default", "private"):
        raise ValueError(f"Unknown storage {photo_storage!r}.")
    company = Company.objects.filter(pk=company_id, is_active=True).first()
    if company is None:
        return 0
    feature = EVENT_FEATURES.get(event)
    if feature is not None and not company.has_feature(feature):
        return 0
    groups = TelegramGroup.objects.filter(
        company_id=company_id, is_active=True, events__contains=[event]
    )
    position_ids = list(position_ids)
    if position_ids:
        groups = groups.filter(Q(positions=None) | Q(positions__in=position_ids))
    if branch_id is not None:
        groups = groups.filter(Q(branches=None) | Q(branches=branch_id))
    group_ids = list(groups.values_list("pk", flat=True).distinct())
    for group_id in group_ids:
        # After the caller's transaction commits, like every other job: a change that is
        # rolled back never reaches a group.
        transaction.on_commit(
            partial(group_jobs.queue_post, group_id, (text, None), photo, photo_storage)
        )
    return len(group_ids)


def managing_membership(user: User) -> Membership | None:
    """The membership someone connects groups with: the current one if it may, else any that may."""
    current = members.current_membership(user)
    if current is not None and current.has_perm(Perm.GROUPS_MANAGE):
        return current
    others = (
        Membership.objects.filter(
            user=user, status=Membership.Status.APPROVED, company__is_active=True
        )
        .select_related("company", "role")
        .order_by("-updated_at")
    )
    return next((m for m in others if m.has_perm(Perm.GROUPS_MANAGE)), None)


@transaction.atomic
def connect(chat_id: int, title: str, by: User) -> TelegramGroup:
    """Link a group to the company of the manager who asked."""
    manager = managing_membership(by)
    if manager is None:
        raise PermissionDenied(
            _("Only a company manager can connect this group. Ask one to send /connect here.")
        )
    group = TelegramGroup.objects.select_for_update().filter(chat_id=chat_id).first()
    if group is not None and group.is_active and group.company_id != manager.company_id:
        raise DomainError(_("This group is already connected to another company."))
    taken_over = group is not None and group.company_id != manager.company_id
    if group is None:
        group = TelegramGroup(chat_id=chat_id, events=list(DEFAULT_EVENTS))
    elif taken_over:
        group.events = list(DEFAULT_EVENTS)  # left behind by another company: start fresh
    group.company = manager.company
    group.title = title or ""
    group.linked_by = manager
    group.is_active = True
    group.save()
    if taken_over:
        group.positions.clear()  # the old company's positions mean nothing here
    _audit(AuditLog.Action.GROUP_CONNECTED, group, by)
    return group


def find(chat_id: int) -> TelegramGroup | None:
    return (
        TelegramGroup.objects.select_related("company")
        .filter(chat_id=chat_id, is_active=True)
        .first()
    )


def ensure_manager(group: TelegramGroup, user: User) -> None:
    if not members.can(user, group.company, Perm.GROUPS_MANAGE):
        raise PermissionDenied(_("Only a manager of this company can change that."))


@transaction.atomic
def toggle_event(group: TelegramGroup, event: GroupEvent, by: User) -> TelegramGroup:
    ensure_manager(group, by)
    group = TelegramGroup.objects.select_for_update().get(pk=group.pk)
    turned_on = event not in group.events
    if turned_on:
        group.events = [*group.events, event]
    else:
        group.events = [existing for existing in group.events if existing != event]
    group.save(update_fields=["events", "updated_at"])
    _audit(AuditLog.Action.GROUP_CHANGED, group, by, event=str(event), on=turned_on)
    return group


@transaction.atomic
def toggle_position(group: TelegramGroup, position_id: int, by: User) -> TelegramGroup:
    """Add a position to the group's filter, or take it out. An empty filter means everyone."""
    ensure_manager(group, by)
    group = TelegramGroup.objects.select_for_update().get(pk=group.pk)
    position = Position.objects.for_company(group.company_id).filter(pk=position_id).first()
    if position is None:
        raise DomainError(_("That position no longer exists."))
    turned_on = not group.positions.filter(pk=position.pk).exists()
    if turned_on:
        group.positions.add(position)
    else:
        group.positions.remove(position)
    _audit(AuditLog.Action.GROUP_CHANGED, group, by, position=position.name, on=turned_on)
    return group


@transaction.atomic
def disconnect(group: TelegramGroup, by: User) -> None:
    ensure_manager(group, by)
    TelegramGroup.objects.filter(pk=group.pk).update(is_active=False)
    _audit(AuditLog.Action.GROUP_DISCONNECTED, group, by)


@transaction.atomic
def bot_removed(chat_id: int, by: User | None = None) -> None:
    """Telegram says the bot left the group; `by` is whoever removed it, if anyone did."""
    group = (
        TelegramGroup.objects.select_for_update().filter(chat_id=chat_id, is_active=True).first()
    )
    if group is None:
        return
    TelegramGroup.objects.filter(pk=group.pk).update(is_active=False)
    _audit(AuditLog.Action.GROUP_REMOVED, group, by)


def _audit(action: AuditLog.Action, group: TelegramGroup, by: User | None, **details) -> None:
    audit.record(action, company_id=group.company_id, actor=by, target=group, **details)


def migrated(old_chat_id: int, new_chat_id: int) -> None:
    """A group that became a supergroup gets a new id; keep posting to it."""
    TelegramGroup.objects.move_chat(old_chat_id, new_chat_id)


def update_settings(
    group: TelegramGroup,
    *,
    by: Membership,
    events: Iterable[str] | None = None,
    position_ids: Iterable[int] | None = None,
    branch_ids: Iterable[int] | None = None,
) -> TelegramGroup:
    """What a group gets, from the dashboard (§4.4): its events, and the positions and branches
    its news is narrowed to (empty = everyone, every branch). Only the arguments given change.
    An event of a switched-off module can be kept (it was chosen before) but not added."""
    if not by.has_perm(Perm.GROUPS_MANAGE) or by.company_id != group.company_id:
        raise PermissionDenied(_("Only a manager of this company can change that."))
    with transaction.atomic():
        group = TelegramGroup.objects.select_for_update().select_related("company").get(pk=group.pk)
        if not group.is_active:
            raise DomainError(_("This group is disconnected. Add the bot to it again first."))
        before = _settings_snapshot(group)
        if events is not None:
            wanted = list(dict.fromkeys(str(event) for event in events))
            allowed = {str(event) for event in available_events(group.company, group.events)}
            if any(event not in allowed for event in wanted):
                raise DomainError(_("That event isn't available for this company."))
            group.events = [event for event in GroupEvent.values if event in wanted]
            group.save(update_fields=["events", "updated_at"])
        if position_ids is not None:
            ids = set(position_ids)
            positions = list(Position.objects.for_company(group.company_id).filter(pk__in=ids))
            if len(positions) != len(ids):
                raise DomainError(_("Pick positions of this company."))
            group.positions.set(positions)
        if branch_ids is not None:
            ids = set(branch_ids)
            branches = list(Branch.objects.for_company(group.company_id).filter(pk__in=ids))
            if len(branches) != len(ids):
                raise DomainError(_("Pick branches of this company."))
            group.branches.set(branches)
        after = _settings_snapshot(group)
        changes = {
            name: [before[name], value] for name, value in after.items() if before[name] != value
        }
        if changes:
            audit.record(
                AuditLog.Action.GROUP_CHANGED,
                company_id=group.company_id,
                actor=by.user,
                target=group,
                changes=changes,
            )
    return group


def _settings_snapshot(group: TelegramGroup) -> dict:
    return {
        "events": list(group.events),
        "positions": sorted(group.positions.values_list("pk", flat=True)),
        "branches": sorted(group.branches.values_list("pk", flat=True)),
    }
