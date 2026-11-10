"""The company's own Face ID bot: a BotFather token set on the Face ID settings page, after
which everything Face ID sends to Telegram goes through it (`route`, registered with
`apps.notifications.routes` as the "faceid" channel):

* the "who came" scan messages with the snapshot, unknown faces and unlinked numbers (inbox
  kinds `faceid.*`) to the managers who get them today;
* the person's own check-in message (`apps.attendance.notify.scan_message`);
* the branch groups' arrival posts, when the bot was added to the group (otherwise the employee
  bot posts them, as before).

Without a connected bot nothing changes: the shared bots send as before. Telegram lets a bot
write only to people who pressed Start in it: a 403 is recorded on `FaceBotChat` and nothing
more is sent to that person until they press Start (no retries). The `faceid_bot` command polls
every connected bot (`poll_once`) to answer /start and mark the person as started; it reads the
tokens again on every round, so a new or changed token needs no restart.

Tests never reach Telegram: they replace `get_updates`, `reply` and `check_token`, and run with
TELEGRAM_DRY_RUN or a fake `telegram.send_with_token`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError,
)
from django.db import IntegrityError, transaction
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.audit import services as audit
from apps.console import pulse
from apps.core.exceptions import DomainError
from apps.davomat import telegram as tg
from apps.faceid import conf
from apps.faceid.audit_actions import FaceIdAction
from apps.faceid.models import FaceBotChat, FaceIdSettings, FaceLink
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.members.queries import members_with_perm
from apps.notifications import telegram
from apps.notifications.routes import Routed

logger = logging.getLogger(__name__)

Status = FaceIdSettings.BotStatus
PULSE = "faceid.settings"
START_PAYLOAD = "faceid"
LANGUAGES = ("uz", "ru", "en")


class TokenError(DomainError):
    """A token Telegram refuses (shown under the token field)."""


def _bump(company_id: int) -> None:
    transaction.on_commit(lambda: pulse.bump(company_id, PULSE))


def connected(row: FaceIdSettings) -> bool:
    return bool(row.bot_token and row.bot_username and row.bot_status == Status.OK)


def has_bot(company_id: int) -> bool:
    """Whether the company's Face ID bot is connected and working."""
    return (
        FaceIdSettings.objects.filter(company_id=company_id, bot_status=Status.OK)
        .exclude(bot_token="")
        .exclude(bot_username="")
        .exists()
    )


def start_url(row: FaceIdSettings) -> str:
    return f"https://t.me/{row.bot_username}?start={START_PAYLOAD}" if row.bot_username else ""


# Connecting -----------------------------------------------------------------------------------


def connect(company, *, by: Membership | None, token: str) -> FaceIdSettings:
    """Check the BotFather token with Telegram (`getMe`) and keep it, encrypted, with the bot's
    name. Another bot than before starts with nobody started. Raises TokenError or DomainError
    (Telegram can't be reached)."""
    token = "".join(str(token or "").split())
    if not token:
        raise TokenError(_("Paste the token BotFather gave you."))
    try:
        info = tg.check_token(token)
    except tg.TokenRefused as exc:
        raise TokenError(
            _("Telegram doesn't accept this token. Copy it from BotFather again.")
        ) from exc
    except tg.TelegramUnreachable as exc:
        raise DomainError(_("Telegram can't be reached right now. Try again in a minute.")) from exc
    if FaceIdSettings.objects.filter(bot_id=info.id).exclude(company=company).exists():
        raise TokenError(_("This bot already works for another company. Make a new one."))
    with transaction.atomic():
        row = FaceIdSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        if row.bot_id != info.id:
            FaceBotChat.objects.filter(company=company).delete()
            row.bot_offset = 0
        row.bot_token = token
        row.bot_id, row.bot_username, row.bot_name = info.id, info.username, info.name[:128]
        row.bot_status = Status.OK
        row.bot_checked_at = timezone.now()
        row.save()
        _audit(by, FaceIdAction.BOT_CONNECTED, row, bot=f"@{info.username}")
    _bump(company.pk)
    return row


def disconnect(company, *, by: Membership | None) -> FaceIdSettings:
    """Forget the token: Face ID's messages go through the shared bots again."""
    with transaction.atomic():
        row = FaceIdSettings.objects.select_for_update().get(pk=conf.get_settings(company).pk)
        if not row.bot_token and row.bot_status == Status.NOT_SET:
            return row
        was = row.bot_username
        row.bot_token, row.bot_id, row.bot_username, row.bot_name = "", None, "", ""
        row.bot_status = Status.NOT_SET
        row.bot_checked_at = timezone.now()
        row.bot_offset = 0
        row.save()
        FaceBotChat.objects.filter(company=company).delete()
        _audit(by, FaceIdAction.BOT_REMOVED, row, bot=f"@{was}" if was else "")
    _bump(company.pk)
    return row


def mark_refused_token(company_id: int) -> None:
    """Telegram stopped accepting the token (revoked in BotFather): the settings say so, and
    the shared bots send again until a new token is pasted."""
    FaceIdSettings.objects.filter(company_id=company_id).exclude(bot_token="").update(
        bot_status=Status.INVALID, bot_checked_at=timezone.now()
    )
    _bump(company_id)


def send_test(company, user: User) -> None:
    """A test message from the Face ID bot to `user`. Raises DomainError with what to do."""
    row = conf.get_settings(company)
    if not row.bot_token or not row.bot_username:
        raise DomainError(_("Connect the Face ID bot first."))
    if user.telegram_id is None:
        raise DomainError(_("Link your Telegram first, then try again."))
    with translation.override(user.language):
        text = _("Test message from the Face ID bot of %(company)s.") % {"company": company.name}
    try:
        telegram.send_with_token(row.bot_token, user.telegram_id, text)
    except TelegramUnauthorizedError as exc:
        mark_refused_token(company.pk)
        raise DomainError(
            _("Telegram doesn't accept the bot's token any more. Paste a new one.")
        ) from exc
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        _refused(company.pk, user.telegram_id)
        raise DomainError(
            _("Open @%(bot)s in Telegram, press Start, then try again.") % {"bot": row.bot_username}
        ) from exc
    except (TelegramAPIError, OSError) as exc:
        raise DomainError(_("Telegram can't be reached right now. Try again in a minute.")) from exc
    _started(company.pk, user.telegram_id, by_delivery=True)


def _audit(by: Membership | None, action: str, row: FaceIdSettings, **details) -> None:
    audit.record(
        action,
        company_id=row.company_id,
        actor=by.user if by is not None else None,
        target=row,
        **details,
    )


# Who gets Face ID's messages, and who still has to press Start --------------------------------


@dataclass(frozen=True)
class Recipient:
    member: Membership
    role: str  # "manager" (scans, unknown faces) or "employee" (their own check-in message)
    state: str  # "started", "refused" (403: never pressed Start or blocked) or "waiting"


def recipients(company) -> list[Recipient]:
    """Everyone with Telegram the Face ID bot writes to: holders of the attendance permissions
    (the managers' messages), and when `notify_employee` is on, the people linked to a number."""
    row = conf.get_settings(company)
    managers: dict[int, Membership] = {}
    for perm in (Perm.ATTENDANCE_VIEW, Perm.ATTENDANCE_MANAGE):
        for member in members_with_perm(company, perm).select_related("user"):
            managers.setdefault(member.pk, member)
    employees: dict[int, Membership] = {}
    if row.notify_employee:
        linked = FaceLink.objects.filter(company=company, membership__isnull=False).values(
            "membership_id"
        )
        for member in Membership.objects.filter(
            company=company, pk__in=linked, status=Membership.Status.APPROVED
        ).select_related("user"):
            if member.pk not in managers:
                employees[member.pk] = member
    chats = {chat.telegram_id: chat for chat in FaceBotChat.objects.filter(company=company)}
    people: list[Recipient] = []
    for role, group in (("manager", managers), ("employee", employees)):
        for member in group.values():
            telegram_id = member.user.telegram_id
            if telegram_id is None:
                continue
            chat = chats.get(telegram_id)
            if chat is not None and chat.refused:
                state = "refused"
            elif chat is not None and chat.started_at is not None:
                state = "started"
            else:
                state = "waiting"
            people.append(Recipient(member, role, state))
    people.sort(key=lambda person: (person.state == "started", person.member.full_name))
    return people


def _chat(company_id: int, telegram_id: int) -> FaceBotChat:
    chat = FaceBotChat.objects.filter(company_id=company_id, telegram_id=telegram_id).first()
    if chat is not None:
        return chat
    user = User.objects.filter(telegram_id=telegram_id).first()
    try:
        with transaction.atomic():
            return FaceBotChat.objects.create(
                company_id=company_id, telegram_id=telegram_id, user=user
            )
    except IntegrityError:
        return FaceBotChat.objects.get(company_id=company_id, telegram_id=telegram_id)


def _started(company_id: int, telegram_id: int, *, by_delivery: bool = False) -> None:
    chat = _chat(company_id, telegram_id)
    if by_delivery and chat.started_at is not None and not chat.refused:
        return
    FaceBotChat.objects.filter(pk=chat.pk).update(started_at=timezone.now())
    _bump(company_id)


def _refused(company_id: int, telegram_id: int) -> None:
    chat = _chat(company_id, telegram_id)
    FaceBotChat.objects.filter(pk=chat.pk).update(refused_at=timezone.now())
    _bump(company_id)


# Delivery (`apps.notifications.routes` router) --------------------------------------------------


def route(
    company_id: int,
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    photo: str | None = None,
    photo_storage: str = "default",
    *,
    group: bool = False,
) -> Routed | None:
    """Send through the company's Face ID bot when it has one; None (the shared bot sends, as
    before) when it hasn't, when its token stopped working, or for a group it isn't in."""
    row = (
        FaceIdSettings.objects.filter(company_id=company_id)
        .only("company_id", "bot_token", "bot_username", "bot_status")
        .first()
    )
    if row is None or not connected(row):
        return None
    if not group:
        chat = FaceBotChat.objects.filter(company_id=company_id, telegram_id=chat_id).first()
        if chat is not None and chat.refused:
            return Routed(None)  # Told once already: nothing until they press Start.
    try:
        message_id = telegram.send_with_token(
            row.bot_token, chat_id, text, reply_markup, photo, photo_storage
        )
    except TelegramUnauthorizedError:
        mark_refused_token(company_id)
        return None
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        if group:
            logger.info(
                "Face ID bot can't post in group %s (%s): the employee bot does", chat_id, exc
            )
            return None
        logger.info("Face ID bot can't write to %s: %s", chat_id, exc)
        _refused(company_id, chat_id)
        return Routed(None)
    if not group and message_id is not None:
        _started(company_id, chat_id, by_delivery=True)
    return Routed(message_id)


# The poller (`manage.py faceid_bot`) ------------------------------------------------------------


@dataclass(frozen=True)
class Update:
    update_id: int
    chat_id: int | None
    chat_type: str
    from_id: int | None
    language_code: str
    text: str


def get_updates(token: str, offset: int) -> list[Update]:
    """Telegram's waiting updates of one bot (no long polling: one round over every bot)."""

    async def ask() -> list[Update]:
        async with Bot(token) as bot:
            updates = await bot.get_updates(
                offset=offset or None, timeout=0, allowed_updates=["message"], request_timeout=15
            )
        rows = []
        for update in updates:
            message = update.message
            rows.append(
                Update(
                    update_id=update.update_id,
                    chat_id=message.chat.id if message else None,
                    chat_type=message.chat.type if message else "",
                    from_id=message.from_user.id if message and message.from_user else None,
                    language_code=(
                        (message.from_user.language_code or "")
                        if message and message.from_user
                        else ""
                    ),
                    text=(message.text or "") if message else "",
                )
            )
        return rows

    return asyncio.run(ask())


def reply(token: str, chat_id: int, text: str) -> None:
    telegram.send_with_token(token, chat_id, text)


def welcome(company, language: str) -> str:
    with translation.override(language):
        return _(
            "Hello. This is the Face ID bot of %(company)s. Face ID notices (who came, "
            "unknown faces, your own check-ins) will come here."
        ) % {"company": company.name}


def _language(user: User | None, code: str, company) -> str:
    if user is not None and user.language in LANGUAGES:
        return user.language
    code = (code or "").split("-")[0].lower()
    if code in LANGUAGES:
        return code
    return company.default_language if company.default_language in LANGUAGES else "uz"


def handle(row: FaceIdSettings, update: Update) -> bool:
    """/start in a private chat: the person is started, and welcomed. True when handled."""
    if update.chat_type != "private" or update.from_id is None:
        return False
    if not update.text.strip().startswith("/start"):
        return False
    _started(row.company_id, update.from_id)
    chat = FaceBotChat.objects.select_related("user").get(
        company_id=row.company_id, telegram_id=update.from_id
    )
    if chat.user is None:
        user = User.objects.filter(telegram_id=update.from_id).first()
        if user is not None:
            FaceBotChat.objects.filter(pk=chat.pk).update(user=user)
            chat.user = user
    language = _language(chat.user, update.language_code, row.company)
    try:
        reply(row.bot_token, update.chat_id or update.from_id, welcome(row.company, language))
    except TelegramAPIError as exc:
        logger.info("Face ID bot couldn't welcome %s: %s", update.from_id, exc)
    return True


def poll_bot(row: FaceIdSettings) -> int:
    """One round of one bot: its waiting updates handled, its offset moved on. Returns how many
    /start it answered."""
    try:
        updates = get_updates(row.bot_token, row.bot_offset)
    except TelegramUnauthorizedError:
        mark_refused_token(row.company_id)
        return 0
    except (TelegramAPIError, OSError, TimeoutError) as exc:
        logger.warning("Face ID bot of company %s: getUpdates failed: %s", row.company_id, exc)
        return 0
    if not updates:
        return 0
    answered = 0
    for update in updates:
        try:
            answered += handle(row, update)
        except Exception:
            logger.exception("Face ID bot of company %s: update %s", row.company_id, update)
    offset = max(update.update_id for update in updates) + 1
    # Only while the token is still the one polled: a new bot starts from its own beginning.
    FaceIdSettings.objects.filter(pk=row.pk, bot_id=row.bot_id).update(bot_offset=offset)
    return answered


def poll_once() -> int:
    """One round over every company's connected Face ID bot (read fresh each time)."""
    rows = (
        FaceIdSettings.objects.exclude(bot_token="")
        .filter(bot_status=Status.OK, company__is_active=True)
        .select_related("company")
        .order_by("pk")
    )
    return sum(poll_bot(row) for row in rows)
