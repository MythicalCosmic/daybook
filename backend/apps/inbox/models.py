"""Notifications: one row per recipient, shown in the dashboard and the mini app, copied to
Telegram per the kind's default and the person's preference (docs/PLAN-OWNER.md §3.4)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.members.models import Membership


class Notification(TenantModel):
    class Severity(models.TextChoices):
        INFO = "info", _("Info")
        WARNING = "warning", _("Warning")
        CRITICAL = "critical", _("Critical")

    recipient = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(
        max_length=48, help_text=_("Registered kind, e.g. sales.cash_difference.")
    )
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.INFO)
    # Rendered in the recipient's language when created.
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True, help_text=_("Dashboard route."))
    app_screen = models.CharField(max_length=120, blank=True, help_text=_("Mini app deep link."))
    target_type = models.CharField(max_length=32, blank=True)
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    actor = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # [{"key": "approve", "label": "...", "style": "primary", "needs_reason": false}]
    actions = models.JSONField(default=list, blank=True)
    data = models.JSONField(default=dict, blank=True)
    in_app = models.BooleanField(
        default=True,
        help_text=_("False for kinds that live in Needs you: a Telegram copy only."),
    )
    dedupe_key = models.CharField(max_length=120, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    telegram_sent_at = models.DateTimeField(null=True, blank=True)
    # Which bot sent the copy, and where, so it can be edited after someone acts.
    telegram_bot = models.CharField(max_length=8, blank=True)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True)
    telegram_message_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "in_app", "read_at", "-created_at"],
                name="inbox_recipient_unread",
            ),
            models.Index(fields=["company", "kind", "target_type", "target_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="unique_notification_dedupe_key",
            ),
        ]

    def __str__(self):
        return f"{self.kind}: {self.title}"


class NotificationPreference(models.Model):
    """A person's choice for one kind; without a row the kind's defaults apply."""

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    kind = models.CharField(max_length=48)
    in_app = models.BooleanField(default=True)
    telegram = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "kind"], name="unique_notification_preference"
            ),
        ]

    def __str__(self):
        return f"{self.membership}: {self.kind}"
