"""Owner sign-in: login links (desktop QR / deep link), device sessions and signup codes.

None of these belong to a company: a person signs in once and then sees every company where
they hold `dashboard.access` (docs/PLAN-OWNER.md §3.6, §7).
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class LoginLink(models.Model):
    """One desktop sign-in attempt: the browser holds the poll secret, the QR the public code.

    Only hashes are stored. The bot offers `match_code` among three numbers (number matching).
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for Telegram")
        APPROVED = "approved", _("Approved")
        DENIED = "denied", _("Denied")
        EXPIRED = "expired", _("Expired")
        CONSUMED = "consumed", _("Used")

    class Bot(models.TextChoices):
        OWNER = "owner", _("Owner bot")
        EMPLOYEE = "employee", _("Employee bot")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=64, unique=True)
    poll_hash = models.CharField(max_length=64)
    match_code = models.CharField(max_length=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    bot = models.CharField(max_length=8, choices=Bot.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="login_links",
    )
    user_agent = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["status", "expires_at"])]

    def __str__(self):
        return f"{self.get_status_display()} ({self.created_at:%d.%m.%Y %H:%M})"


class DeviceSession(models.Model):
    """A signed-in browser on the desktop. Its id is the `sid` claim of the owner tokens.

    `refresh_jti` is the newest refresh token; `previous_jti` is the one it replaced, accepted
    for a few seconds so two tabs refreshing at once don't look like a stolen token.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_sessions"
    )
    refresh_jti = models.CharField(max_length=64)
    previous_jti = models.CharField(max_length=64, blank=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [models.Index(fields=["user", "revoked_at"])]

    def __str__(self):
        return f"{self.user} · {self.user_agent[:40] or _('unknown device')}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class SignupCode(models.Model):
    """Lets someone create a company from the owner bot while `COMPANY_SIGNUP=code`."""

    code_hash = models.CharField(max_length=64, unique=True)
    uses_left = models.PositiveSmallIntegerField(default=1)
    expires_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.note or f"Signup code {self.pk}"
