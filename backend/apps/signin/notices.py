"""Telegram messages owner sign-in sends on its own (not through the inbox: signing in belongs
to a person, not to one company)."""

import logging

from django.conf import settings
from django.utils import translation

from apps.accounts.models import User
from apps.notifications.telegram import BotName, serialize_markup
from apps.signin.models import DeviceSession

logger = logging.getLogger(__name__)


def bot_for(user: User, *, preferred: str) -> str | None:
    """The bot to write to `user` through: the one they just used when it can reach them,
    else the other one, else None."""
    owner_ok = bool(settings.OWNER_BOT_TOKEN) and user.owner_bot_blocked_at is None
    employee_ok = bool(settings.EMPLOYEE_BOT_TOKEN) and user.employee_bot_blocked_at is None
    if preferred == BotName.OWNER and owner_ok:
        return BotName.OWNER
    if employee_ok:
        return BotName.EMPLOYEE
    if owner_ok and user.owner_bot_started_at is not None:
        return BotName.OWNER
    return None


def signed_in(session: DeviceSession, *, bot: str) -> None:
    """Sends "Signed in on Chrome · Windows… Not you? [Log out everywhere]" (never raises)."""
    from apps.notifications.tasks import send_telegram_message
    from apps.signin import bot_messages

    user = session.user
    chosen = bot_for(user, preferred=bot) if user.telegram_id else None
    if chosen is None:
        return
    with translation.override(user.language):
        text, markup = bot_messages.signed_in(session)
    try:
        send_telegram_message.delay(chosen, user.telegram_id, text, serialize_markup(markup))
    except Exception:  # a notice must never break a sign-in that already happened
        logger.exception("Couldn't queue the signed-in notice for user %s", user.pk)
