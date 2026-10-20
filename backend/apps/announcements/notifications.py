from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef
from django.utils import translation

from apps.announcements import bot_messages
from apps.announcements.models import Announcement, Receipt
from apps.members.models import Membership
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
    # Counted from when it went out: a scheduled announcement may be written days before.
    due = Receipt.objects.filter(
        read_at__isnull=True,
        reminded_at__isnull=True,
        announcement__status=Announcement.Status.SENT,
        announcement__sent_at__lte=now - REMIND_AFTER,
        announcement__sent_at__gte=now - FOLLOW_UP_FOR,
    ).select_related("announcement__author", "membership__user")
    for receipt in due:
        _send(receipt, lambda item: bot_messages.copy(item, reminder=True), receipt.announcement)
        Receipt.objects.filter(pk=receipt.pk).update(reminded_at=now)

    unread = Receipt.objects.filter(announcement=OuterRef("pk"), read_at__isnull=True)
    for announcement in (
        Announcement.objects.filter(
            status=Announcement.Status.SENT,
            summary_sent_at__isnull=True,
            sent_at__lte=now - SUMMARY_AFTER,
            sent_at__gte=now - FOLLOW_UP_FOR,
        )
        .filter(Exists(unread))
        .select_related("author__user")
    ):
        Announcement.objects.filter(pk=announcement.pk).update(summary_sent_at=now)
        author = announcement.author
        if author is None or not _reachable(author):
            continue
        receipts = list(_receipts(announcement))
        missing = [receipt.membership for receipt in receipts if receipt.read_at is None]
        with translation.override(author.user.language):
            text, markup = bot_messages.summary(announcement, missing, len(receipts))
        send_telegram_message.delay(
            BotName.EMPLOYEE, author.user.telegram_id, text, serialize_markup(markup)
        )


def remind(announcement_id: int, receipt_ids: list[int]) -> None:
    """The "remind unread now" copies, sent to those receipts still unread."""
    receipts = Receipt.objects.filter(
        pk__in=receipt_ids, announcement_id=announcement_id, read_at__isnull=True
    ).select_related("announcement__author", "membership__user")
    for receipt in receipts:
        _send(receipt, lambda item: bot_messages.copy(item, reminder=True), receipt.announcement)


def _receipts(announcement: Announcement):
    return announcement.receipts.select_related("membership__user").order_by(
        "membership__first_name"
    )


def _reachable(member: Membership) -> bool:
    """Approved and on Telegram: suspended people hear no announcements (§13.4)."""
    return member.status == Membership.Status.APPROVED and member.user.telegram_id is not None


def _send(receipt: Receipt, build, announcement: Announcement) -> None:
    if not _reachable(receipt.membership):
        return
    user = receipt.membership.user
    with translation.override(user.language):
        text, markup = build(announcement)
    send_telegram_message.delay(BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup))
