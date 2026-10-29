"""Telegram copies of notifications: which bot, sending, and editing after someone acts.

A plain module: `inbox.tasks` and `inbox.services` both use it, and it imports neither.

Which bot: owner-audience kinds go through the owner bot when it is configured
(`OWNER_BOT_TOKEN`) and the person started it and hasn't blocked it; everything else, and the
fallback when the owner bot refuses, goes through the employee bot.
"""

import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from django.conf import settings
from django.utils import timezone, translation
from django.utils.functional import Promise

from apps.accounts.models import User
from apps.inbox import bot_messages, registry
from apps.inbox.models import Notification
from apps.members.models import Membership
from apps.notifications import telegram
from apps.notifications.tasks import edit_telegram_message
from apps.notifications.telegram import BotName, serialize_markup

logger = logging.getLogger(__name__)

BLOCKED_FIELD = {
    BotName.OWNER: "owner_bot_blocked_at",
    BotName.EMPLOYEE: "employee_bot_blocked_at",
}


def bots_for(user: User, audience: str, member: Membership | None = None) -> list[BotName]:
    """The bots to try, in order. The owner bot only for owners and top managers (`member`,
    when known): everyone else hears through the employee bot."""
    from apps.members.departments import is_top_manager

    owner_bot_ready = (
        audience == "owner"
        and bool(settings.OWNER_BOT_TOKEN)
        and user.owner_bot_started_at is not None
        and user.owner_bot_blocked_at is None
        and (member is None or is_top_manager(member))
    )
    return [BotName.OWNER, BotName.EMPLOYEE] if owner_bot_ready else [BotName.EMPLOYEE]


def bot_for(user: User, audience: str) -> BotName:
    return bots_for(user, audience)[0]


def deliver(notification_id: int, *, photo: str | None = None, photo_storage: str = "default"):
    """Send the Telegram copy of one notification (once). Telegram network errors propagate,
    so the Celery task retries; a blocked bot is recorded on the user."""
    item = (
        Notification.objects.select_related("recipient__user", "recipient__role", "company")
        .filter(pk=notification_id)
        .first()
    )
    if item is None or item.telegram_sent_at is not None or item.acted_at is not None:
        return
    # Someone blocked, offboarded or suspended since the notification was made hears nothing.
    if item.recipient.status != Membership.Status.APPROVED or not item.company.is_active:
        return
    user = item.recipient.user
    if user.telegram_id is None:
        return
    kind = registry.KINDS.get(item.kind)
    audience = kind.audience if kind else "employee"
    with translation.override(user.language):
        text, markup = bot_messages.notification(item, audience=audience)
    for bot in bots_for(user, audience, item.recipient):
        try:
            message_id = telegram.send_message(
                bot, user.telegram_id, text, serialize_markup(markup), photo, photo_storage
            )
        except TelegramForbiddenError:
            _set_blocked(user, bot, timezone.now())
            continue
        except TelegramBadRequest as exc:
            logger.warning("Notification %s not delivered: %s", item.pk, exc)
            return
        if message_id is not None:
            Notification.objects.filter(pk=item.pk).update(
                telegram_sent_at=timezone.now(),
                telegram_bot=bot,
                telegram_chat_id=user.telegram_id,
                telegram_message_id=message_id,
            )
            _set_blocked(user, bot, None)
        return


def edit_after_action(
    notification_ids: list[int],
    *,
    key: str,
    actor_name: str,
    messages: dict[int, str],
    outcome=None,
) -> None:
    """Replace the buttons of the Telegram copies with who did what.

    `messages` maps a notification id to its finished outcome text. The others show `outcome`
    when given (lazy text or `(Membership) -> str`, as `inbox.services.settle` passes it),
    else the label of action `key`, in their own recipient's language."""
    items = Notification.objects.select_related("recipient__user").filter(
        pk__in=notification_ids, telegram_message_id__isnull=False
    )
    for item in items:
        user = item.recipient.user
        kind = registry.KINDS.get(item.kind)
        audience = kind.audience if kind else "employee"
        with translation.override(user.language):
            if outcome is None:
                line = messages.get(item.pk) or bot_messages.answered_line(
                    _label(item, key), actor_name
                )
            else:
                label = _render(outcome, item.recipient)
                line = messages.get(item.pk) or bot_messages.outcome_line(label, actor_name)
            text, markup = bot_messages.notification(item, audience=audience, outcome=line)
        edit_telegram_message.delay(
            item.telegram_bot or BotName.EMPLOYEE,
            item.telegram_chat_id,
            item.telegram_message_id,
            text,
            serialize_markup(markup),
        )


def _render(text, person: Membership) -> str:
    if callable(text) and not isinstance(text, Promise):
        return str(text(person))
    return str(text)


def _label(item: Notification, key: str) -> str:
    for action in item.actions:
        if action.get("key") == key:
            return action.get("label", key)
    return key


def _set_blocked(user: User, bot: BotName, when) -> None:
    field = BLOCKED_FIELD[bot]
    if getattr(user, field) == when or (when is not None and getattr(user, field) is not None):
        return
    setattr(user, field, when)
    User.objects.filter(pk=user.pk).update(**{field: when})
