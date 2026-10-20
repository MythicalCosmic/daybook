"""Exports: one Excel/CSV file a person asked for, built in the background, kept 7 days."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership


class Export(TenantModel):
    class Format(models.TextChoices):
        XLSX = "xlsx", "Excel (xlsx)"
        CSV = "csv", "CSV"
        ZIP = "zip", "ZIP"

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting")
        RUNNING = "running", _("Building")
        READY = "ready", _("Ready")
        FAILED = "failed", _("Failed")

    kind = models.CharField(max_length=48, help_text=_("Registered exporter, e.g. tasks.tasks."))
    format = models.CharField(max_length=4, choices=Format.choices)
    params = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    rows = models.PositiveIntegerField(null=True, blank=True)
    file = models.FileField(
        storage=private_storage, upload_to=private_upload_to("exports"), blank=True
    )
    requested_by = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="exports")
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    deliver_telegram = models.BooleanField(
        default=False, help_text=_("Also send the file to the requester in Telegram.")
    )
    sensitive = models.BooleanField(
        default=False, help_text=_("Salaries, IDs or per-person money: copied from the exporter.")
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["requested_by", "-created_at"])]

    def __str__(self):
        return f"{self.kind}.{self.format} ({self.get_status_display()})"
