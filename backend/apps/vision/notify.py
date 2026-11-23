"""Ko‘z alerts in Telegram (docs/KOZ.md §7), run by `apps.vision.tasks` after the change commits.

Who: when `notify_on_shift`, the people checked in at the alert's branch right now (an open
attendance record there), through the employee bot; when `notify_managers`, the members with
`vision.view` who see that branch, through the bot they use for owner messages
(`apps.inbox.delivery.bots_for`). Nobody twice (one `AlertMessage` per person and alert). A box
offline is for the managers only. Every copy is kept, so each is edited when someone goes or
the alert ends. Nothing here writes alerts.
"""

from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from django.utils import translation

from apps.attendance.models import AttendanceRecord
from apps.inbox.delivery import bots_for
from apps.members import scope
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.notifications import telegram
from apps.notifications.tasks import edit_telegram_message
from apps.notifications.telegram import BotName, serialize_markup
from apps.vision import bot_messages, conf
from apps.vision.models import Alert, AlertMessage

logger = logging.getLogger(__name__)

ON_SHIFT, MANAGER = "on_shift", "manager"


def _alert(alert_id: int) -> Alert | None:
    return (
        Alert.objects.select_related(
            "company", "branch", "camera", "agent", "acknowledged_by__user"
        )
        .filter(pk=alert_id)
        .first()
    )


def recipients(alert: Alert) -> list[tuple[Membership, str]]:
    """(person, why) in sending order: who is on shift first, then the managers."""
    company = alert.company
    settings = conf.get_settings(company)
    found: dict[int, tuple[Membership, str]] = {}
    if (
        alert.kind in Alert.CAMERA_KINDS
        and settings.notify_on_shift
        and conf.tracks_attendance(company)
    ):
        records = (
            AttendanceRecord.objects.filter(
                company=company, branch_id=alert.branch_id, status=AttendanceRecord.Status.OPEN
            )
            .select_related("membership__user", "membership__company")
            .order_by("check_in_at", "pk")
        )
        for record in records:
            person = record.membership
            if person.status == Membership.Status.APPROVED:
                found.setdefault(person.pk, (person, ON_SHIFT))
    if settings.notify_managers:
        holders = (
            members_with_perm(company, Perm.VISION_VIEW)
            .select_related("user", "role", "company")
            .prefetch_related("branches")
            .order_by("pk")
        )
        for person in holders:
            if scope.allows(scope.branch_ids(person), alert.branch_id):
                found.setdefault(person.pk, (person, MANAGER))
    return [(person, why) for person, why in found.values() if person.user.telegram_id]


def recipients_of(alert_id: int) -> list[tuple[int, str]]:
    """Who to send an alert to, by id; nobody once it is over or the module is off."""
    alert = _alert(alert_id)
    if alert is None or not conf.is_on(alert.company) or not alert.company.is_active:
        return []
    if alert.state != Alert.State.OPEN:
        return []
    return [(person.pk, why) for person, why in recipients(alert)]


def send_copy(alert_id: int, member_id: int, reason: str) -> int | None:
    """One person's copy, with the photo when the settings allow it; its message id is kept.
    Telegram network errors propagate (the task retries); a blocked bot tries the next one."""
    alert = _alert(alert_id)
    person = (
        Membership.objects.select_related("user", "role", "company").filter(pk=member_id).first()
    )
    if alert is None or person is None or person.status != Membership.Status.APPROVED:
        return None
    chat_id = person.user.telegram_id
    if not chat_id:
        return None
    copy, _created = AlertMessage.objects.get_or_create(
        alert=alert, member=person, defaults={"reason": reason}
    )
    if copy.message_id is not None:
        return copy.message_id  # sent before this retry
    settings = conf.get_settings(alert.company)
    photo = alert.photo.name if alert.photo and settings.alert_photo else None
    bots = [BotName.EMPLOYEE] if reason == ON_SHIFT else bots_for(person.user, "owner", person)
    with translation.override(person.user.language):
        text, markup = bot_messages.alert_message(alert, manager=reason == MANAGER)
    for bot in bots:
        try:
            message_id = telegram.send_message(
                bot, chat_id, text, serialize_markup(markup), photo, "private"
            )
        except TelegramForbiddenError:
            continue  # blocked or never started: the next bot, if any
        except TelegramBadRequest as exc:
            logger.warning("Ko‘z alert %s not delivered to %s: %s", alert.pk, member_id, exc)
            return None
        AlertMessage.objects.filter(pk=copy.pk).update(
            bot=bot, chat_id=chat_id, message_id=message_id
        )
        return message_id
    return None


def refresh(alert_id: int) -> int:
    """Every delivered copy, drawn again as the alert is now (acknowledged, or over)."""
    alert = _alert(alert_id)
    if alert is None:
        return 0
    copies = alert.messages.filter(message_id__isnull=False).select_related("member__user")
    edited = 0
    for copy in copies:
        with translation.override(copy.member.user.language):
            text, markup = bot_messages.alert_message(alert, manager=copy.reason == MANAGER)
        edit_telegram_message.delay(
            copy.bot or BotName.EMPLOYEE,
            copy.chat_id,
            copy.message_id,
            text,
            serialize_markup(markup),
        )
        edited += 1
    return edited
