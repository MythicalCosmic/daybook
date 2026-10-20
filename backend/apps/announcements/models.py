from django.db import models
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, TenantModel
from apps.members.models import Membership, Position


class Announcement(TenantModel):
    """A message from a manager to everyone, or to some positions, with read receipts."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SCHEDULED = "scheduled", _("Scheduled")
        SENT = "sent", _("Sent")
        CANCELLED = "cancelled", _("Cancelled")

    author = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    text = models.TextField(help_text=_("As the author wrote it, formatting included."))
    positions = models.ManyToManyField(
        Position, blank=True, related_name="+", help_text=_("Who gets it. None = everyone.")
    )
    branches = models.ManyToManyField(
        Branch,
        blank=True,
        related_name="announcements",
        help_text=_("Only people in these branches get it. None = every branch."),
    )
    summary_sent_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When the author heard who still hadn't read it.")
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    pinned_until = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        first_line = strip_tags(self.text).strip().split("\n")[0]
        return first_line if len(first_line) <= 60 else f"{first_line[:59]}…"


class Receipt(models.Model):
    """One person's copy of an announcement, and whether they've read it."""

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="receipts"
    )
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="+")
    read_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "membership"], name="one_receipt_per_person"
            ),
        ]

    def __str__(self):
        return f"{self.membership}: {self.announcement}"
