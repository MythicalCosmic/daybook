from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError
from apps.groups.models import DEFAULT_EVENTS, GroupEvent, TelegramGroup
from apps.members import services as members
from apps.members.models import Membership, Position
from apps.members.permissions import Perm


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
