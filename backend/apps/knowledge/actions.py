"""Handlers of the knowledge base's notification buttons (`inbox.registry.register_action`)."""

from django.db import transaction

from apps.core.exceptions import DomainError
from apps.knowledge import bot_messages, queries
from apps.knowledge.models import Page
from apps.members.models import Membership
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup


def read_in_chat(notification, by: Membership, reason: str) -> str:
    """ "📖 Read": the page arrives in the chat, with "I've read it" when it asks for that."""
    page = (
        Page.objects.select_related("space")
        .filter(company_id=notification.company_id, pk=notification.target_id)
        .first()
    )
    if page is None or not queries.can_read(by, page):
        raise DomainError(bot_messages.not_found())
    ack = queries.my_ack(by, page)
    text, markup = bot_messages.page_message(
        page, read=ack is not None and queries.is_read(ack.version, page)
    )
    chat_id = by.user.telegram_id
    if chat_id is not None:
        markup_data = serialize_markup(markup)
        transaction.on_commit(
            lambda: send_telegram_message.delay(BotName.EMPLOYEE, chat_id, text, markup_data)
        )
    return bot_messages.sent_below()
