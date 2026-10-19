from django.conf import settings
from django.db.models import Q
from django.utils import translation

from apps.accounts.models import User
from apps.companies.models import Company
from apps.members import bot_messages
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup


def approver_chats(company: Company) -> dict[int, str]:
    """Telegram chat id -> language, for everyone allowed to decide the company's join requests."""
    admin_ids = settings.PLATFORM_ADMIN_TG_IDS
    chats = dict.fromkeys(admin_ids, company.default_language)
    chats.update(
        User.objects.filter(telegram_id__in=admin_ids).values_list("telegram_id", "language")
    )
    chats.update(
        Membership.objects.for_company(company)
        .filter(status=Membership.Status.APPROVED, user__telegram_id__isnull=False)
        .filter(Q(role__is_owner=True) | Q(role__permissions__contains=[str(Perm.MEMBERS_APPROVE)]))
        .values_list("user__telegram_id", "user__language")
    )
    return chats


def send_join_request(membership_id: int) -> None:
    membership = _load(membership_id)
    if membership is None or membership.status != Membership.Status.PENDING:
        return
    for chat_id, language in approver_chats(membership.company).items():
        with translation.override(language):
            text, markup = bot_messages.join_request(membership)
        send_telegram_message.delay(BotName.EMPLOYEE, chat_id, text, serialize_markup(markup))


def send_join_decision(membership_id: int) -> None:
    membership = _load(membership_id)
    if membership is None or membership.user.telegram_id is None:
        return
    with translation.override(membership.user.language):
        message = bot_messages.decision_for_requester(membership)
    if message is not None:
        text, markup = message
        send_telegram_message.delay(
            BotName.EMPLOYEE, membership.user.telegram_id, text, serialize_markup(markup)
        )


def _load(membership_id: int) -> Membership | None:
    return (
        Membership.objects.select_related("company", "user", "decided_by")
        .filter(pk=membership_id)
        .first()
    )
