"""One company everywhere: when someone switches company in the mini app or the dashboard, the
employee bot follows. `User.bot_company` is the company the bot's lists, menus and new tasks
use; the mini app and the dashboard save it when the person switches (not when they only open a
link to another company's task), and the bot's chat gets one message saying where they work now,
carrying that company's main menu (its modules differ per company).

In the backend rather than the bot package: the message goes out from a Celery job after the
commit, and workers can't import the bot.
"""

from functools import partial

from django.db import transaction
from django.utils import translation

from apps.accounts.models import User
from apps.accounts.services import bot_membership


def bot_company_id(user: User) -> int | None:
    """The company the bot works in for this person now, as both `me` endpoints report it:
    their approved membership's company, else None."""
    from apps.members.models import Membership

    membership = bot_membership(user)
    if membership is None or membership.status != Membership.Status.APPROVED:
        return None
    return membership.company_id


def follow(user: User, before: int | None) -> bool:
    """After `User.bot_company` was saved: when that moved the company the bot works in (from
    `before`), the bot's chat hears after the commit. Returns whether it moved."""
    from apps.accounts.tasks import announce_company

    after = bot_company_id(user)
    if after is None or after == before:
        return False
    transaction.on_commit(partial(announce_company.delay, user.pk, after))
    return True


def announce(user_id: int, company_id: int) -> None:
    """ "Now working in <b>X</b>." with that company's main menu, in the person's language, to
    their chat with the employee bot. Nothing when they switched again since, aren't approved
    there, or haven't finished joining (their next message brings what they need)."""
    from apps.members import bot_messages
    from apps.notifications.tasks import send_telegram_message
    from apps.notifications.telegram import BotName, serialize_markup

    user = User.objects.filter(pk=user_id).first()
    if user is None or user.telegram_id is None:
        return
    membership = bot_membership(user)
    if (
        membership is None
        or membership.company_id != company_id
        or bot_company_id(user) != company_id
        or not membership.is_onboarded
    ):
        return
    with translation.override(user.language):
        text, markup = bot_messages.company_switched(membership)
    send_telegram_message.delay(BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup))
