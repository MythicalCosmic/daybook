"""Clean-up of sign-in records (`signin.tasks.flush_expired_tokens`, `expire_login_links`)."""

from datetime import timedelta

from django.core.management import call_command
from django.db.models import Q
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.signin.models import DeviceSession, LoginLink

# Ended sessions stay listed a while, so an owner can see what was signed out and when.
KEEP_ENDED_SESSIONS = timedelta(days=30)
# Login links are only interesting while someone investigates a strange sign-in.
KEEP_LOGIN_LINKS = timedelta(days=7)


def flush_expired_tokens() -> None:
    call_command("flushexpiredtokens", verbosity=0)
    now = timezone.now()
    # A session idle for longer than a refresh token lives can never refresh again.
    idle = now - jwt_settings.REFRESH_TOKEN_LIFETIME - KEEP_ENDED_SESSIONS
    DeviceSession.objects.filter(revoked_at__lt=now - KEEP_ENDED_SESSIONS).delete()
    DeviceSession.objects.filter(revoked_at__isnull=True, last_seen_at__lt=idle).delete()


def expire_login_links(now=None) -> tuple[int, int]:
    """Mark pending links past their life (and approvals nobody claimed) expired, and delete
    links older than a week. Returns (expired, deleted)."""
    from apps.signin.links import CLAIM_WINDOW

    now = now or timezone.now()
    expired = LoginLink.objects.filter(
        Q(status=LoginLink.Status.PENDING, expires_at__lte=now)
        | Q(status=LoginLink.Status.APPROVED, decided_at__lte=now - CLAIM_WINDOW)
    ).update(status=LoginLink.Status.EXPIRED)
    deleted, _rows = LoginLink.objects.filter(created_at__lt=now - KEEP_LOGIN_LINKS).delete()
    return expired, deleted
