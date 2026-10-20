"""Desktop sign-in through Telegram: a login link, number matching and one POST claim (§7.1).

    Browser                         this module                        Telegram (owner bot)
    POST login-links/       ──▶    create_link: code (public, in the QR), poll token (secret,
                                    kept by the browser), a 2-digit match number; only hashes
                                    are stored; lives LINK_LIFETIME
    GET login-links/{id}/   ──▶    status_for: {status}, never a token
                                                                        /start login_<code>
                                    open_link: the prompt with three numbers ◀──
                                    decide: right number → approved; wrong number or
                                    "It wasn't me" → denied (one tap, the link is spent) ◀──
    POST …/claim/           ──▶    claim: once, under a row lock → a DeviceSession, then the
                                    "Signed in on …" message with "Log out everywhere"

Number matching beats the "attacker shows the victim a QR" trick: the victim can't see the
attacker's screen, so they guess right one time in three, and a wrong tap cancels the link.
"""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.signin import devices, notices
from apps.signin.models import LoginLink
from apps.signin.services import IssuedSession, can_sign_in, client_ip, issue_session, user_agent

LINK_LIFETIME = timedelta(minutes=3)
# An approved link must be claimed soon after: the browser polls every 1.5 s.
CLAIM_WINDOW = timedelta(minutes=2)
START_PREFIX = "login_"
CHOICES = 3

Status = LoginLink.Status


class SigninUnavailable(Exception):
    """No bot username is configured, so there is nowhere to send the person."""


class LinkRefused(Exception):
    """The bot can't offer this link. `reason`: unknown, expired, used, denied, no_access."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ClaimRefused(Exception):
    """The browser can't claim this link. `code` is what the API answers with."""

    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code = code
        self.status = status


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def login_bot() -> str:
    """Which bot confirms sign-ins: the owner bot once it has a token, else the employee bot
    (`DASHBOARD_LOGIN_BOT`, §7.1)."""
    return LoginLink.Bot.OWNER if settings.OWNER_BOT_TOKEN else LoginLink.Bot.EMPLOYEE


def bot_username(bot: str) -> str:
    if bot == LoginLink.Bot.OWNER:
        return settings.OWNER_BOT_USERNAME
    return settings.EMPLOYEE_BOT_USERNAME


def deep_link(code: str, bot: str) -> str:
    return f"https://t.me/{bot_username(bot)}?start={START_PREFIX}{code}"


@dataclass(frozen=True)
class NewLink:
    link: LoginLink
    code: str
    poll_token: str
    deep_link: str
    bot_username: str


@transaction.atomic
def create_link(request) -> NewLink:
    """A fresh link for the browser behind `request`. Raises SigninUnavailable."""
    bot = login_bot()
    username = bot_username(bot)
    if not username:
        raise SigninUnavailable
    # 32 random bytes are 43 URL-safe characters: "login_<code>" fits Telegram's 64.
    code = secrets.token_urlsafe(32)
    poll = secrets.token_urlsafe(32)
    link = LoginLink.objects.create(
        code_hash=sha256(code),
        poll_hash=sha256(poll),
        match_code=str(10 + secrets.randbelow(90)),
        bot=bot,
        user_agent=user_agent(request),
        ip=client_ip(request),
        expires_at=timezone.now() + LINK_LIFETIME,
    )
    return NewLink(link, code, poll, deep_link(code, bot), username)


def effective_status(link: LoginLink, now: datetime | None = None) -> str:
    """The status the browser should see: a pending link past its life, or an approval nobody
    claimed in time, reads as expired (GET never writes; the hourly job stores it)."""
    now = now or timezone.now()
    if link.status == Status.PENDING and link.expires_at <= now:
        return Status.EXPIRED
    if link.status == Status.APPROVED and (link.decided_at or now) + CLAIM_WINDOW <= now:
        return Status.EXPIRED
    return link.status


def _poll_matches(link: LoginLink, poll_token: str) -> bool:
    return bool(poll_token) and hmac.compare_digest(link.poll_hash, sha256(poll_token))


def _parse_id(link_id) -> uuid.UUID | None:
    try:
        return link_id if isinstance(link_id, uuid.UUID) else uuid.UUID(str(link_id))
    except ValueError:
        return None


def status_for(link_id, poll_token: str) -> str | None:
    """The link's status for the browser holding `poll_token`; None for anyone else."""
    pk = _parse_id(link_id)
    link = LoginLink.objects.filter(pk=pk).first() if pk else None
    if link is None or not _poll_matches(link, poll_token):
        return None
    return effective_status(link)


@dataclass(frozen=True)
class LoginPrompt:
    """What the bot shows: where the sign-in comes from and three numbers to choose from."""

    link_id: uuid.UUID
    choices: tuple[str, ...]
    device: devices.Device
    ip: str
    created_at: datetime


def open_link(code: str, user: User) -> LoginPrompt:
    """`/start login_<code>` from `user`. Raises LinkRefused; never changes the link, so
    opening it twice is harmless."""
    link = LoginLink.objects.filter(code_hash=sha256(code)).first() if code else None
    if link is None:
        raise LinkRefused("unknown")
    status = effective_status(link)
    if status == Status.EXPIRED:
        raise LinkRefused("expired")
    if status in (Status.APPROVED, Status.CONSUMED):
        raise LinkRefused("used")
    if status == Status.DENIED:
        raise LinkRefused("denied")
    if not can_sign_in(user):
        raise LinkRefused("no_access")
    return LoginPrompt(
        link_id=link.pk,
        choices=_choices(link.match_code),
        device=devices.describe(link.user_agent),
        ip=devices.masked_ip(link.ip),
        created_at=link.created_at,
    )


def _choices(match: str) -> tuple[str, ...]:
    """The right number among decoys, in random order."""
    rng = secrets.SystemRandom()
    decoys = rng.sample([str(n) for n in range(10, 100) if str(n) != match], CHOICES - 1)
    numbers = [match, *decoys]
    rng.shuffle(numbers)
    return tuple(numbers)


def decide(link_id, user: User, pick: str | None) -> str:
    """`user` tapped `pick` (None: "It wasn't me"). Returns the outcome: approved,
    wrong_number, denied, no_access, expired, used or unknown. Any tap but the right number
    spends the link."""
    pk = _parse_id(link_id)
    if pk is None:
        return "unknown"
    now = timezone.now()
    with transaction.atomic():
        link = LoginLink.objects.select_for_update().filter(pk=pk).first()
        if link is None:
            return "unknown"
        status = effective_status(link, now)
        if status == Status.EXPIRED:
            if link.status == Status.PENDING:
                link.status = Status.EXPIRED
                link.save(update_fields=["status"])
            return "expired"
        if status != Status.PENDING:
            # A second tap from the same person (a double tap before the buttons went away)
            # repeats the first answer instead of claiming the link was used by someone.
            if link.user_id == user.pk and link.status in (Status.APPROVED, Status.CONSUMED):
                return "approved"
            if link.user_id == user.pk and link.status == Status.DENIED:
                return "denied"
            return "used"
        outcome = "approved"
        if pick is None:
            outcome = "denied"
        elif not can_sign_in(user):
            outcome = "no_access"
        elif not hmac.compare_digest(str(pick), link.match_code):
            outcome = "wrong_number"
        link.status = Status.APPROVED if outcome == "approved" else Status.DENIED
        link.user = user
        link.decided_at = now
        link.save(update_fields=["status", "user", "decided_at"])
    return outcome


def claim(link_id, poll_token: str, request) -> IssuedSession:
    """The browser collects its session, once. Raises ClaimRefused."""
    pk = _parse_id(link_id)
    now = timezone.now()
    with transaction.atomic():
        link = LoginLink.objects.select_for_update().filter(pk=pk).first() if pk else None
        if link is None or not _poll_matches(link, poll_token):
            raise ClaimRefused("not_found", 404)
        status = effective_status(link, now)
        if status == Status.CONSUMED:
            raise ClaimRefused("used", 409)
        if status != Status.APPROVED:
            raise ClaimRefused(status, 409)
        if link.user is None or not can_sign_in(link.user):
            raise ClaimRefused("no_access", 403)
        link.status = Status.CONSUMED
        link.consumed_at = now
        link.save(update_fields=["status", "consumed_at"])
        issued = issue_session(link.user, request)
        session, bot = issued.session, link.bot
        transaction.on_commit(lambda: notices.signed_in(session, bot=bot))
    return issued
