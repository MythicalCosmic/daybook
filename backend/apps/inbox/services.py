"""Notifications: create them, act on them, read and archive them, and preferences.

    notify(approvers, "finance.claim", title=lambda m: _("Expense claim from %s") % name,
           target=claim, actions=[NotificationAction("approve", _("Approve"), "primary")])

`run_action` is the one way to act on a notification, from a Telegram button and from the
dashboard alike: it runs the handler the module registered, marks every copy of the same
notification (same kind and target) as handled, and replaces their Telegram buttons with the
outcome.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models, transaction
from django.utils import timezone, translation
from django.utils.functional import Promise
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.console import pulse
from apps.console.registry import QUEUE_STYLES
from apps.core.exceptions import DomainError
from apps.inbox import bot_messages, delivery, registry, tasks
from apps.inbox.models import Notification, NotificationPreference
from apps.members.models import Membership

logger = logging.getLogger(__name__)

UNREAD_PULSE = "inbox.unread"
STYLES = QUEUE_STYLES  # the same buttons as Needs you items

type Text = str | Promise | Callable[[Membership], str]


@dataclass(frozen=True)
class NotificationAction:
    """A button on a notification. `label` may be lazy text or `(Membership) -> str`."""

    key: str
    label: Text
    style: str = "default"
    needs_reason: bool = False

    def __post_init__(self):
        if not registry.ACTION_KEY.match(self.key):
            raise ValueError(f"Action key {self.key!r}: lowercase letters, digits and _.")
        if self.style not in STYLES:
            raise ValueError(f"Action style must be one of {STYLES}.")


def notify(
    recipients: Iterable[Membership],
    kind: str,
    *,
    title: Text,
    body: Text = "",
    url: str = "",
    app_screen: str = "",
    target: models.Model | None = None,
    actor: Membership | None = None,
    severity: str | None = None,
    actions: Sequence[NotificationAction | dict] = (),
    data: dict | None = None,
    dedupe_key: str = "",
    photo: str | None = None,
    photo_storage: str = "default",
) -> list[Notification]:
    """One notification per approved recipient, in each one's language; Telegram copies go
    out after commit per the kind's default and the person's preference.

    A recipient who already has `dedupe_key` is skipped. Returns the rows created (including
    Telegram-only ones of kinds that live in Needs you)."""
    spec = registry.get_kind(kind)
    buttons = [_as_action(action) for action in actions]
    for button in buttons:
        if registry.get_handler(kind, button.key) is None:
            raise LookupError(f"No handler registered for {kind}.{button.key}.")
    severity = severity or spec.severity
    if severity not in registry.SEVERITIES:
        raise ValueError(f"Severity must be one of {registry.SEVERITIES}.")
    people = [
        person for person in _distinct(recipients) if person.status == Membership.Status.APPROVED
    ]
    if not people:
        return []
    preferences = {
        preference.membership_id: preference
        for preference in NotificationPreference.objects.filter(membership__in=people, kind=kind)
    }

    created: list[Notification] = []
    telegram_ids: list[int] = []
    with transaction.atomic():
        for person in people:
            preference = preferences.get(person.pk)
            in_app = spec.queue_kind is None and (preference is None or preference.in_app)
            wants_telegram = spec.default_telegram if preference is None else preference.telegram
            if not in_app and not wants_telegram:
                continue
            with translation.override(person.user.language):
                item = Notification(
                    company_id=person.company_id,
                    recipient=person,
                    kind=kind,
                    severity=severity,
                    title=_render(title, person)[:200],
                    body=_render(body, person),
                    url=url[:300],
                    app_screen=app_screen[:120],
                    target_type=target._meta.model_name if target is not None else "",
                    target_id=target.pk if target is not None else None,
                    actor=actor,
                    actions=[
                        {
                            "key": button.key,
                            "label": _render(button.label, person),
                            "style": button.style,
                            "needs_reason": button.needs_reason,
                        }
                        for button in buttons
                    ],
                    data=data or {},
                    in_app=in_app,
                    dedupe_key=dedupe_key[:120],
                )
            if not _insert(item):
                continue
            created.append(item)
            if wants_telegram:
                telegram_ids.append(item.pk)

    companies = {item.company_id for item in created if item.in_app}
    for notification_id in telegram_ids:
        transaction.on_commit(
            lambda pk=notification_id: tasks.deliver_telegram.delay(pk, photo, photo_storage)
        )
    for company_id in companies:
        transaction.on_commit(lambda cid=company_id: pulse.bump(cid, UNREAD_PULSE))
    return created


def run_action(notification_id: int, key: str, *, by: Membership, reason: str = "") -> str | None:
    """Act on one of `by`'s notifications through the handler its module registered.

    Raises `Notification.DoesNotExist`, `PermissionDenied` (not theirs, or the handler's own
    check) or `DomainError` (already handled, unknown action, missing reason, or a business
    rule in the handler). Returns the handler's message."""
    reason = (reason or "").strip()
    now = timezone.now()
    with transaction.atomic():
        item = (
            Notification.objects.select_for_update(of=("self",))
            .select_related("recipient__user", "company")
            .get(pk=notification_id)
        )
        if item.recipient_id != by.pk or by.status != Membership.Status.APPROVED:
            raise PermissionDenied(_("You don't have access to this."))
        if item.acted_at is not None:
            raise DomainError(_("This has already been handled."))
        button = next((action for action in item.actions if action.get("key") == key), None)
        handler = registry.get_handler(item.kind, key)
        if button is None or handler is None:
            raise DomainError(_("This action isn't available any more."))
        if button.get("needs_reason") and not reason:
            raise DomainError(_("Please give a reason."))

        message = handler(item, by, reason)

        handled = [item.pk]
        item.acted_at = now
        item.acted_by = by.user
        item.read_at = item.read_at or now
        item.save(update_fields=["acted_at", "acted_by", "read_at", "updated_at"])
        if item.target_id is not None:
            siblings = Notification.objects.filter(
                company_id=item.company_id,
                kind=item.kind,
                target_type=item.target_type,
                target_id=item.target_id,
                acted_at__isnull=True,
            ).exclude(pk=item.pk)
            handled += list(siblings.values_list("pk", flat=True))
            siblings.update(acted_at=now, acted_by=by.user, updated_at=now)

    actor_name = str(by)
    # The handler answered in the actor's language, which is this copy's recipient's.
    own = {item.pk: bot_messages.outcome_line(message, actor_name)} if message else {}
    transaction.on_commit(
        lambda: delivery.edit_after_action(handled, key=key, actor_name=actor_name, messages=own)
    )
    transaction.on_commit(lambda: pulse.bump(item.company_id, UNREAD_PULSE))
    return message


@dataclass(frozen=True)
class BotActionResult:
    ok: bool
    message: str


def act_from_bot(notification_id: int, key: str, *, user: User) -> BotActionResult:
    """A notification button pressed in either bot by `user` (in their language)."""
    item = (
        Notification.objects.select_related("recipient__company")
        .filter(pk=notification_id, recipient__user=user)
        .first()
    )
    if item is None or not item.recipient.company.is_active:
        return BotActionResult(False, _("You don't have access to this."))
    try:
        message = run_action(item.pk, key, by=item.recipient)
    except DomainError as exc:
        return BotActionResult(False, str(exc))
    except PermissionDenied as exc:
        return BotActionResult(False, str(exc) or _("You don't have permission to do this."))
    except Notification.DoesNotExist:
        return BotActionResult(False, _("You don't have access to this."))
    return BotActionResult(True, message or _("Done."))


def mark_read(member: Membership, *, ids: Sequence[int] = (), everything: bool = False) -> int:
    """Mark `member`'s notifications read: the given ids, or all of them."""
    unread = Notification.objects.filter(recipient=member, in_app=True, read_at__isnull=True)
    if not everything:
        unread = unread.filter(pk__in=list(ids))
    count = unread.update(read_at=timezone.now())
    if count:
        transaction.on_commit(lambda: pulse.bump(member.company_id, UNREAD_PULSE))
    return count


def archive(member: Membership, notification_id: int) -> Notification:
    """Hide one of `member`'s notifications from the inbox (it counts as read)."""
    item = Notification.objects.get(pk=notification_id, recipient=member, in_app=True)
    now = timezone.now()
    item.archived_at = item.archived_at or now
    item.read_at = item.read_at or now
    item.save(update_fields=["archived_at", "read_at", "updated_at"])
    transaction.on_commit(lambda: pulse.bump(member.company_id, UNREAD_PULSE))
    return item


@transaction.atomic
def set_preferences(member: Membership, choices: Iterable[dict]) -> None:
    """`choices`: [{"kind", "in_app", "telegram"}] for registered kinds."""
    for choice in choices:
        registry.get_kind(choice["kind"])
        NotificationPreference.objects.update_or_create(
            membership=member,
            kind=choice["kind"],
            defaults={"in_app": choice["in_app"], "telegram": choice["telegram"]},
        )


def _as_action(action: NotificationAction | dict) -> NotificationAction:
    return action if isinstance(action, NotificationAction) else NotificationAction(**action)


def _render(text: Text, person: Membership) -> str:
    if callable(text) and not isinstance(text, Promise):
        return str(text(person))
    return str(text)


def _distinct(recipients: Iterable[Membership]) -> list[Membership]:
    seen: dict[int, Membership] = {}
    for person in recipients:
        seen.setdefault(person.pk, person)
    return list(seen.values())


def _insert(item: Notification) -> bool:
    """Save unless the recipient already has this dedupe key."""
    if not item.dedupe_key:
        item.save()
        return True
    try:
        with transaction.atomic():
            item.save()
    except IntegrityError:
        return False
    return True
