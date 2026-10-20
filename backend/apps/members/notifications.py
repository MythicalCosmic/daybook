from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.companies.models import Company
from apps.inbox import services as inbox
from apps.inbox.services import NotificationAction
from apps.members import bot_messages
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup

JOIN_KIND = "members.join"


def approver_chats(company: Company) -> dict[int, str]:
    """Telegram chat id -> language, for everyone allowed to decide the company's join requests."""
    admin_ids = settings.PLATFORM_ADMIN_TG_IDS
    chats = dict.fromkeys(admin_ids, company.default_language)
    chats.update(
        User.objects.filter(telegram_id__in=admin_ids).values_list("telegram_id", "language")
    )
    chats.update(
        members_with_perm(company, Perm.MEMBERS_APPROVE)
        .filter(user__telegram_id__isnull=False)
        .values_list("user__telegram_id", "user__language")
    )
    return chats


def send_join_request(membership_id: int) -> None:
    """Tell the approvers: through the inbox (Needs you, and a Telegram copy whose Approve
    button asks for branches when the company has several), and with the classic message to
    platform admins who aren't members of the company."""
    membership = _load(membership_id)
    if membership is None or membership.status != Membership.Status.PENDING:
        return
    if not membership.is_onboarded:
        return  # nothing to decide on until they've filled in their details
    company = membership.company
    approvers = list(
        members_with_perm(company, Perm.MEMBERS_APPROVE).select_related("user", "company")
    )
    inbox.notify(
        approvers,
        JOIN_KIND,
        title=lambda person: bot_messages.join_request_title(membership),
        body=lambda person: bot_messages.join_request_body(membership),
        url=f"/c/{company.pk}/people/requests?request={membership.pk}",
        target=membership,
        actions=[
            NotificationAction("approve", lambda person: _("✅ Approve"), "primary"),
            NotificationAction("reject", lambda person: _("❌ Reject"), "danger"),
        ],
        # One copy per request: a person asking again after a refusal is a new request.
        dedupe_key=f"members.join:{membership.pk}:{int(membership.updated_at.timestamp())}",
    )
    reached = {person.user.telegram_id for person in approvers}
    for chat_id, language in approver_chats(company).items():
        if chat_id in reached:
            continue
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


def send_onboarding_complete(membership_id: int) -> None:
    membership = _load(membership_id)
    if membership is None or membership.user.telegram_id is None:
        return
    with translation.override(membership.user.language):
        text, markup = bot_messages.onboarding_complete(membership)
    send_telegram_message.delay(
        BotName.EMPLOYEE, membership.user.telegram_id, text, serialize_markup(markup)
    )


def send_offboarded(membership_id: int) -> None:
    membership = _load(membership_id)
    if membership is None or membership.user.telegram_id is None:
        return
    with translation.override(membership.user.language):
        text, markup = bot_messages.offboarded(membership)
    send_telegram_message.delay(
        BotName.EMPLOYEE, membership.user.telegram_id, text, serialize_markup(markup)
    )


def send_suspended(membership_id: int) -> None:
    membership = _load(membership_id)
    if membership is None or membership.status != Membership.Status.SUSPENDED:
        return
    _send_to_member(membership, bot_messages.paused)


def send_reinstated(membership_id: int) -> None:
    membership = _load(membership_id)
    if membership is None or membership.status != Membership.Status.APPROVED:
        return
    _send_to_member(membership, bot_messages.reinstated)


def _send_to_member(membership: Membership, build) -> None:
    if membership.user.telegram_id is None:
        return
    with translation.override(membership.user.language):
        text, markup = build(membership)
    send_telegram_message.delay(
        BotName.EMPLOYEE, membership.user.telegram_id, text, serialize_markup(markup)
    )


def _load(membership_id: int) -> Membership | None:
    return (
        Membership.objects.select_related("company", "user", "position", "decided_by")
        .filter(pk=membership_id)
        .first()
    )
