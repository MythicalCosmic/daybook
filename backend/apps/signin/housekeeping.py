"""Daily clean-up of sign-in records (`signin.tasks.flush_expired_tokens`)."""

from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.signin.models import DeviceSession

# Ended sessions stay listed a while, so an owner can see what was signed out and when.
KEEP_ENDED_SESSIONS = timedelta(days=30)


def flush_expired_tokens() -> None:
    call_command("flushexpiredtokens", verbosity=0)
    now = timezone.now()
    # A session idle for longer than a refresh token lives can never refresh again.
    idle = now - jwt_settings.REFRESH_TOKEN_LIFETIME - KEEP_ENDED_SESSIONS
    DeviceSession.objects.filter(revoked_at__lt=now - KEEP_ENDED_SESSIONS).delete()
    DeviceSession.objects.filter(revoked_at__isnull=True, last_seen_at__lt=idle).delete()
