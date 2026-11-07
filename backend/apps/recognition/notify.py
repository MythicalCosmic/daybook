"""Who hears about recognition, and when (docs/PLAN-LEARNING.md §9.1).

- `recognition.kudos`: the receiver. An inbox entry in the app (the feed opens from it); the bot
  message with "Say thanks back" goes out on its own (`kudos`), like the tasks app's "can't do
  it", so the inbox sends no second copy.
- `recognition.level`, `recognition.badge`: the person. One plain message for everything new
  since the last one, at most one a minute (`schedule_notices` batches), never in the company's
  quiet hours; "Open in app" leads to their achievements.

Background work only: these run after commit (Celery), never inside the request that awarded.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.utils import timezone, translation

from apps.inbox import services as inbox
from apps.inbox.models import NotificationPreference
from apps.members.models import Membership
from apps.notifications.telegram import BotName, serialize_markup
from apps.recognition import badges as catalogue
from apps.recognition import bot_messages, conf, rules
from apps.recognition.models import BadgeAward, Kudos, LevelUp, PointsEntry

KUDOS = "recognition.kudos"
LEVEL = "recognition.level"
BADGE = "recognition.badge"

NOTICE_GAP_SECONDS = 60  # at most one message a minute per person
FIRST_WAIT_SECONDS = 5  # what one request earns arrives together


def _pending_key(member_id: int) -> str:
    return f"recognition:notice-pending:{member_id}"


def _last_key(member_id: int) -> str:
    return f"recognition:notice-last:{member_id}"


# Kudos ---------------------------------------------------------------------------------------


def wants_telegram(member: Membership, kind: str) -> bool:
    """Unless the person turned the kind's Telegram copy off."""
    preference = NotificationPreference.objects.filter(membership=member, kind=kind).first()
    return preference is None or preference.telegram


def kudos(kudos_id: int) -> None:
    """The receiver hears about it: an inbox entry and the bot message."""
    from apps.notifications.tasks import send_telegram_message

    item = (
        Kudos.objects.select_related("from_member__user", "to_member__user", "company")
        .filter(pk=kudos_id, hidden_at__isnull=True)
        .first()
    )
    if item is None or not conf.is_on(item.company):
        return
    receiver = item.to_member
    if receiver.status != Membership.Status.APPROVED:
        return
    points = (
        PointsEntry.objects.filter(company=item.company, key=f"kudos:{item.pk}")
        .values_list("points", flat=True)
        .first()
    )
    inbox.notify(
        [receiver],
        KUDOS,
        title=lambda person: bot_messages.thanked_line(item),
        body=item.message,
        app_screen=bot_messages.FEED_SCREEN,
        target=item,
        actor=item.from_member,
        dedupe_key=f"recognition.kudos:{item.pk}",
    )
    user = receiver.user
    if user.telegram_id is None or not wants_telegram(receiver, KUDOS):
        return
    with translation.override(user.language):
        text, markup = bot_messages.kudos(item, points=points)
    send_telegram_message.delay(
        BotName.EMPLOYEE, user.telegram_id, text, serialize_markup(markup) if markup else None
    )


# Levels and badges ---------------------------------------------------------------------------


def schedule_notices(member_id: int) -> None:
    """Tell the person about what they just earned, batched: everything new within the wait
    goes in one message, and never more than one a minute."""
    from apps.recognition import tasks

    if not cache.add(_pending_key(member_id), 1, timeout=NOTICE_GAP_SECONDS * 3):
        return  # a message is already on its way and will carry this too
    last = cache.get(_last_key(member_id))
    wait = FIRST_WAIT_SECONDS
    if last is not None:
        wait = max(FIRST_WAIT_SECONDS, int(NOTICE_GAP_SECONDS - (time.time() - last)) + 1)
    tasks.send_notices.apply_async((member_id,), countdown=wait)


def quiet_until(member: Membership, now: datetime) -> datetime | None:
    """When the company's quiet hours (its reminder policy) end, if they are on now."""
    from apps.reminders.policies import default_policy
    from apps.reminders.schedule import quiet_until as until

    local = timezone.localtime(now, ZoneInfo(member.company.timezone))
    return until(local, default_policy(member.company_id))


def achievements(member_id: int, *, now: datetime | None = None) -> bool:
    """Send the person one message about their new levels and badges (those the bot hasn't
    told them about); returns whether a message was made."""
    now = now or timezone.now()
    member = Membership.objects.select_related("user", "company").filter(pk=member_id).first()
    if member is None:
        return False
    levels = list(LevelUp.objects.filter(membership=member, notified_at__isnull=True))
    awards = list(
        BadgeAward.objects.filter(membership=member, notified_at__isnull=True).order_by(
            "awarded_at", "pk"
        )
    )
    if not levels and not awards:
        return False
    LevelUp.objects.filter(pk__in=[row.pk for row in levels]).update(notified_at=now)
    BadgeAward.objects.filter(pk__in=[row.pk for row in awards]).update(notified_at=now)
    if member.status != Membership.Status.APPROVED or not conf.is_on(member.company):
        return False
    top = max(levels, key=lambda row: row.number) if levels else None
    topics = _topic_names(awards)

    def names(person) -> list[str]:
        return [catalogue.title(row.badge, row.ref, topic=topics.get(row.ref)) for row in awards]

    def title(person) -> str:
        if top is not None:
            return bot_messages.level_title(rules.level_name(top.number))
        return bot_messages.badges_line(names(person))

    def body(person) -> str:
        lines = []
        if top is not None and awards:
            lines.append(bot_messages.badges_line(names(person)))
        if top is not None:
            following = rules.level_info(top.number).next_at
            if following is not None:
                from apps.recognition.progress import total_points

                left = max(1, following - total_points(member))
                lines.append(bot_messages.to_next_level(left))
        return "\n".join(lines)

    target = top or awards[-1]
    inbox.notify(
        [member],
        LEVEL if top is not None else BADGE,
        title=title,
        body=body,
        app_screen=bot_messages.ACHIEVEMENTS_SCREEN,
        target=target,
        dedupe_key=f"recognition.notice:{type(target).__name__.lower()}:{target.pk}",
    )
    return True


def _topic_names(awards: list[BadgeAward]) -> dict[str, str]:
    ids = [int(row.ref) for row in awards if row.badge == "topic_expert" and row.ref.isdigit()]
    if not ids:
        return {}
    from apps.knowledge.models import Topic

    return {
        str(pk): name for pk, name in Topic.objects.filter(pk__in=ids).values_list("pk", "name")
    }
