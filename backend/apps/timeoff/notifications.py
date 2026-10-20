from django.utils import translation

from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.timeoff import bot_messages
from apps.timeoff.models import TimeOff


def send_request(time_off_id: int) -> None:
    time_off = _load(time_off_id)
    if time_off is None or time_off.status != TimeOff.Status.PENDING:
        return
    approvers = (
        members_with_perm(time_off.company, Perm.TIME_OFF_APPROVE)
        .exclude(pk=time_off.membership_id)
        .filter(user__telegram_id__isnull=False)
        .values_list("user__telegram_id", "user__language")
    )
    for chat_id, language in approvers:
        with translation.override(language):
            text, markup = bot_messages.request(time_off)
        send_telegram_message.delay(BotName.EMPLOYEE, chat_id, text, serialize_markup(markup))


def send_decision(time_off_id: int) -> None:
    time_off = _load(time_off_id)
    if time_off is None:
        return
    user = time_off.membership.user
    if time_off.membership.status != Membership.Status.APPROVED or user.telegram_id is None:
        return  # suspended or gone: the bot leaves them alone
    with translation.override(user.language):
        message = bot_messages.decision(time_off)
    if message is not None:
        text, markup = message
        send_telegram_message.delay(
            BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup)
        )


def _load(time_off_id: int) -> TimeOff | None:
    return (
        TimeOff.objects.select_related("company", "membership__user", "decided_by")
        .filter(pk=time_off_id)
        .first()
    )
