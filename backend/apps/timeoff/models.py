from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership


class Holiday(TenantModel):
    """A day the whole company is off: no daily tasks and no reminders."""

    date = models.DateField()
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["date"]
        constraints = [
            models.UniqueConstraint(fields=["company", "date"], name="one_holiday_per_day"),
        ]

    def __str__(self):
        return f"{self.name} ({self.date:%d.%m.%Y})"


class TimeOff(TenantModel):
    """Days someone asked to be off. Once approved, the bot leaves them alone on those days."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="time_off")
    first_day = models.DateField()
    last_day = models.DateField()
    reason = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Someone who recorded it on the person's behalf."),
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    revoke_reason = models.CharField(max_length=300, blank=True)
    attachment = models.FileField(
        storage=private_storage,
        upload_to=private_upload_to("timeoff"),
        blank=True,
        help_text=_("A sick note or another document, kept private."),
    )

    class Meta:
        verbose_name_plural = "time off"
        ordering = ["-first_day"]
        indexes = [models.Index(fields=["company", "status", "first_day"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(last_day__gte=F("first_day")), name="time_off_ends_after_it_starts"
            ),
        ]

    def __str__(self):
        return f"{self.membership}: {self.first_day:%d.%m}–{self.last_day:%d.%m}"

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1
