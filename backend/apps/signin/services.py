"""Owner sessions: who may sign in, issuing tokens, rotating refresh tokens, logging out.

Two ways in (docs/PLAN-OWNER.md §7):

- **Desktop** (`issue_session`): a `DeviceSession`, an owner refresh token in an httpOnly
  cookie scoped to `/api/v1/owner/auth/`, and an access token naming the session (`sid`).
- **Inside Telegram** (`issue_access`): an access token only; no cookie, no refresh token, no
  session (Telegram Web runs the dashboard in a cross-site iframe, where the cookie never goes).

Refresh tokens rotate on every use and the old one is blacklisted. Presenting a replaced token
again means someone else holds the newest one: the whole session is revoked. The one exception
is a token replaced less than `REUSE_GRACE` ago, which two tabs refreshing at the same moment
send; it gets a new access token but no new refresh token.
"""

import ipaddress
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.settings import api_settings as drf_settings
from rest_framework_simplejwt.exceptions import TokenBackendError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts.models import User
from apps.members.models import Membership
from apps.members.permissions import Perm
from apps.signin.models import DeviceSession
from apps.signin.tokens import (
    SESSION_CLAIM,
    OwnerAccessToken,
    OwnerRefreshToken,
    owner_token_backend,
)

logger = logging.getLogger(__name__)

REFRESH_COOKIE = "owner_refresh"
REFRESH_COOKIE_PATH = "/api/v1/owner/auth/"
# Two tabs refreshing at once both send the same token; the slower one is not a thief.
REUSE_GRACE = timedelta(seconds=30)


class RefreshFailed(Exception):
    """The refresh cookie can't be used (missing, expired, revoked, reused or no access)."""


def can_sign_in(user: User) -> bool:
    """An active user with an approved membership holding `dashboard.access` in an active
    company. Platform admins are not special here; they keep Django admin."""
    if not user.is_active:
        return False
    return (
        Membership.objects.filter(
            user=user, status=Membership.Status.APPROVED, company__is_active=True
        )
        .filter(Q(role__is_owner=True) | Q(role__permissions__contains=[Perm.DASHBOARD_ACCESS]))
        .exists()
    )


def client_ip(request) -> str | None:
    """The client's address behind `NUM_PROXIES` reverse proxies, as DRF's throttles see it."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    address = request.META.get("REMOTE_ADDR")
    proxies = drf_settings.NUM_PROXIES
    if proxies and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",")]
        address = hops[-min(proxies, len(hops))]
    try:
        return str(ipaddress.ip_address(address)) if address else None
    except ValueError:
        return None


def user_agent(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:300]


def issue_access(user: User) -> str:
    """An owner access token without a session: the Telegram Mini App path."""
    return str(OwnerAccessToken.for_user(user))


@dataclass(frozen=True)
class IssuedSession:
    access: str
    refresh: str
    session: DeviceSession


@transaction.atomic
def issue_session(user: User, request) -> IssuedSession:
    """A new desktop session for `user`: the caller must have checked `can_sign_in`."""
    refresh = OwnerRefreshToken.for_user(user)
    session = DeviceSession.objects.create(
        user=user,
        refresh_jti=refresh[jwt_settings.JTI_CLAIM],
        user_agent=user_agent(request),
        ip=client_ip(request),
    )
    refresh[SESSION_CLAIM] = session.pk
    return IssuedSession(access=str(refresh.access_token), refresh=str(refresh), session=session)


def session_response(user: User, request, *, status: int = 200) -> Response:
    """`{access}` plus the refresh cookie: what a desktop sign-in answers."""
    issued = issue_session(user, request)
    response = Response({"access": issued.access}, status=status)
    set_refresh_cookie(response, issued.refresh)
    return response


def set_refresh_cookie(response, refresh: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Strict",
    )


def clear_refresh_cookie(response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite="Strict")


def rotate(raw: str, request) -> tuple[str, str | None]:
    """Exchange a refresh token for `(access, new refresh)`; the refresh is None within the
    reuse grace. Raises `RefreshFailed`; a reused token also revokes its session."""
    payload = _verified_payload(raw)
    now = timezone.now()
    reused = None
    with transaction.atomic():
        session = (
            DeviceSession.objects.select_for_update()
            .select_related("user")
            .filter(pk=payload.get(SESSION_CLAIM), user_id=payload[jwt_settings.USER_ID_CLAIM])
            .first()
        )
        if session is None or session.revoked_at is not None:
            raise RefreshFailed("The session has ended.")
        if not can_sign_in(session.user):
            raise RefreshFailed("No dashboard access any more.")
        jti = payload[jwt_settings.JTI_CLAIM]
        blacklisted = BlacklistedToken.objects.filter(token__jti=jti).exists()
        if jti == session.refresh_jti and not blacklisted:
            return _rotate(session, raw, request, now)
        in_grace = session.rotated_at is not None and now - session.rotated_at <= REUSE_GRACE
        if jti == session.previous_jti and in_grace:
            access = OwnerAccessToken.for_user(session.user)
            access[SESSION_CLAIM] = session.pk
            session.last_seen_at = now
            session.save(update_fields=["last_seen_at"])
            return str(access), None
        _revoke(session, now)
        reused = session
    logger.warning("Refresh token reuse for user %s: session %s revoked", reused.user_id, reused.pk)
    raise RefreshFailed("This sign-in was used elsewhere; the session has ended.")


def logout(raw: str | None) -> None:
    """Blacklist the cookie's token and end its session. Unusable tokens are ignored."""
    if not raw:
        return
    try:
        payload = _verified_payload(raw)
    except RefreshFailed:
        return
    with transaction.atomic():
        session = (
            DeviceSession.objects.select_for_update()
            .filter(pk=payload.get(SESSION_CLAIM), user_id=payload[jwt_settings.USER_ID_CLAIM])
            .first()
        )
        if session is not None and session.revoked_at is None:
            _revoke(session, timezone.now())
        _blacklist_jtis([payload[jwt_settings.JTI_CLAIM]])


@transaction.atomic
def revoke_session(session: DeviceSession) -> None:
    """End one session: its refresh token stops working at once, its access token within
    `OWNER_ACCESS_TOKEN_LIFETIME`."""
    session = DeviceSession.objects.select_for_update().get(pk=session.pk)
    if session.revoked_at is None:
        _revoke(session, timezone.now())


@transaction.atomic
def revoke_others(user: User, *, keep: int | None) -> int:
    """Log out every other device: every session but `keep` ends, and every outstanding token
    of the user except that session's is blacklisted. Returns how many sessions ended."""
    now = timezone.now()
    kept = DeviceSession.objects.filter(user=user, pk=keep, revoked_at__isnull=True).first()
    others = DeviceSession.objects.filter(user=user, revoked_at__isnull=True)
    if kept is not None:
        others = others.exclude(pk=kept.pk)
    count = others.update(revoked_at=now)
    spare = {jti for jti in (kept.refresh_jti, kept.previous_jti) if jti} if kept else set()
    outstanding = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True).exclude(
        jti__in=spare
    )
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in outstanding], ignore_conflicts=True
    )
    return count


def active_sessions(user: User, now=None) -> list[DeviceSession]:
    """The person's signed-in browsers, most recently used first. A browser idle for longer
    than a refresh token lives can never refresh again, so it isn't signed in any more."""
    now = now or timezone.now()
    return list(
        DeviceSession.objects.filter(
            user=user,
            revoked_at__isnull=True,
            last_seen_at__gt=now - jwt_settings.REFRESH_TOKEN_LIFETIME,
        )
    )


class InitDataRefused(Exception):
    """Telegram launch data that can't sign anyone in. `code`: init_data_invalid, no_access."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def user_from_init_data(init_data: str) -> User:
    """The person behind Telegram Mini App `init_data` (§7.2): signed by the owner bot, or by
    the employee bot as a fallback, at most `OWNER_INIT_DATA_MAX_AGE` old, and allowed into
    the dashboard. Raises InitDataRefused."""
    from apps.accounts.services import sync_telegram_user
    from apps.accounts.telegram_auth import InvalidInitData, validate_init_data

    web_user = None
    for bot in ("owner", "employee"):
        try:
            web_user = validate_init_data(
                init_data, bot=bot, max_age=settings.OWNER_INIT_DATA_MAX_AGE
            )
            break
        except InvalidInitData:
            continue
    if web_user is None:
        raise InitDataRefused("init_data_invalid")
    # Nobody is created here: only people who already belong to a company may get in.
    if not User.objects.filter(telegram_id=web_user.id).exists():
        raise InitDataRefused("no_access")
    user = sync_telegram_user(
        telegram_id=web_user.id,
        username=web_user.username,
        first_name=web_user.first_name,
        last_name=web_user.last_name,
        language_code=None,
    )
    if not can_sign_in(user):
        raise InitDataRefused("no_access")
    return user


@transaction.atomic
def revoke_all(user: User) -> int:
    """Log out everywhere: every session ends and every outstanding token of the user is
    blacklisted. Returns how many sessions were still active."""
    now = timezone.now()
    count = DeviceSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
    outstanding = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in outstanding], ignore_conflicts=True
    )
    return count


def _verified_payload(raw: str) -> dict:
    """The refresh token's claims once its signature, expiry, audience and type check out.

    The blacklist is checked by the caller, so a reused token can still be traced to its
    session."""
    try:
        payload = owner_token_backend().decode(raw)
    except TokenBackendError as exc:
        raise RefreshFailed("Invalid refresh token.") from exc
    if payload.get(jwt_settings.TOKEN_TYPE_CLAIM) != OwnerRefreshToken.token_type:
        raise RefreshFailed("Not a refresh token.")
    if jwt_settings.JTI_CLAIM not in payload or jwt_settings.USER_ID_CLAIM not in payload:
        raise RefreshFailed("Incomplete refresh token.")
    return payload


def _rotate(session: DeviceSession, raw: str, request, now) -> tuple[str, str]:
    old = OwnerRefreshToken(raw)
    new = OwnerRefreshToken.for_user(session.user)
    new[SESSION_CLAIM] = session.pk
    old.blacklist()
    session.previous_jti = session.refresh_jti
    session.refresh_jti = new[jwt_settings.JTI_CLAIM]
    session.rotated_at = now
    session.last_seen_at = now
    session.ip = client_ip(request) or session.ip
    session.user_agent = user_agent(request) or session.user_agent
    session.save(
        update_fields=[
            "previous_jti",
            "refresh_jti",
            "rotated_at",
            "last_seen_at",
            "ip",
            "user_agent",
        ]
    )
    return str(new.access_token), str(new)


def _revoke(session: DeviceSession, now) -> None:
    session.revoked_at = now
    session.save(update_fields=["revoked_at"])
    _blacklist_jtis([jti for jti in (session.refresh_jti, session.previous_jti) if jti])


def _blacklist_jtis(jtis: list[str]) -> None:
    tokens = OutstandingToken.objects.filter(jti__in=jtis, blacklistedtoken__isnull=True)
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in tokens], ignore_conflicts=True
    )
