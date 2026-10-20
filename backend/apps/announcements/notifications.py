from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef
from django.utils import translation

from apps.announcements import bot_messages
from apps.announcements.models import Announcement, Receipt
from apps.notifications.tasks import send_telegram_message
from apps.notifications.telegram import BotName, serialize_markup

# People who haven't read an announcement hear about it once more after this long,
REMIND_AFTER = timedelta(hours=3)
# and the author learns who still hasn't after this long.
SUMMARY_AFTER = timedelta(days=1)
# Older announcements are left alone.
FOLLOW_UP_FOR = timedelta(days=3)


def deliver(announcement_id: int) -> None:
    announcement = Announcement.objects.select_related("author").filter(pk=announcement_id).first()
    if announcement is None:
        return
    for receipt in _receipts(announcement):
        _send(receipt, bot_messages.copy, announcement)


def follow_up(now: datetime) -> None:
    """Remind people who haven't read recent announcements, then tell the authors."""
    due = Receipt.objects.filter(
        read_at__isnull=True,
        reminded_at__isnull=True,
        announcement__created_at__lte=now - REMIND_AFTER,
        announcement__created_at__gte=now - FOLLOW_UP_FOR,
    ).select_related("announcement__author", "membership__user")
    for receipt in due:
        _send(receipt, lambda item: bot_messages.copy(item, reminder=True), receipt.announcement)
        Receipt.objects.filter(pk=receipt.pk).update(reminded_at=now)

    unread = Receipt.objects.filter(announcement=OuterRef("pk"), read_at__isnull=True)
    for announcement in (
        Announcement.objects.filter(
            summary_sent_at__isnull=True,
            created_at__lte=now - SUMMARY_AFTER,
            created_at__gte=now - FOLLOW_UP_FOR,
        )
        .filter(Exists(unread))
        .select_related("author__user")
    ):
        Announcement.objects.filter(pk=announcement.pk).update(summary_sent_at=now)
        author = announcement.author
        if author is None or author.user.telegram_id is None:
            continue
        receipts = list(_receipts(announcement))
        missing = [receipt.membership for receipt in receipts if receipt.read_at is None]
        with translation.override(author.user.language):
            text, markup = bot_messages.summary(announcement, missing, len(receipts))
        send_telegram_message.delay(
            BotName.EMPLOYEE, author.user.telegram_id, text, serialize_markup(markup)
        )


def _receipts(announcement: Announcement):
    return announcement.receipts.select_related("membership__user").order_by(
        "membership__first_name"
    )


def _send(receipt: Receipt, build, announcement: Announcement) -> None:
    user = receipt.membership.user
    if user.telegram_id is None:
        return
    with translation.override(user.language):
        text, markup = build(announcement)
    send_telegram_message.delay(BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup))
