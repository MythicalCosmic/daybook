"""Models of the people lifecycle (docs/PLAN-OWNER.md §13.4, with the pharmacy categories of
§14.14). Built now: disciplinary records. Suspensions are the membership's own status
(`members.services.suspend/reinstate`); terminations, job changes, equipment and reviews come
later."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership


class DisciplinaryRecord(TenantModel):
    """A warning or a reprimand someone was given, with what happened and, when one was
    proposed with it, the fine in payroll (`fine_id`, an `payroll.Adjustment`)."""

    class Kind(models.TextChoices):
        VERBAL_WARNING = "verbal_warning", _("Verbal warning")
        WRITTEN_WARNING = "written_warning", _("Written warning")
        FINAL_WARNING = "final_warning", _("Final warning")
        REPRIMAND = "reprimand", _("Reprimand")
        OTHER = "other", _("Other")

    class Category(models.TextChoices):
        LATENESS = "lateness", _("Lateness")
        ABSENCE = "absence", _("Absence")
        CONDUCT = "conduct", _("Conduct")
        POLICY_BREACH = "policy_breach", _("Breach of the rules")
        PERFORMANCE = "performance", _("Work quality")
        CASH_SHORTAGE = "cash_shortage", _("Cash shortage")
        SAFETY = "safety", _("Safety")
        STORAGE_BREACH = "storage_breach", _("Storage conditions breached")
        DISPENSING_ERROR = "dispensing_error", _("Dispensing error")
        RX_VIOLATION = "rx_violation", _("Prescription rules breached")
        EXPIRED_SALE = "expired_sale", _("Expired medicine sold")
        STOCK_SHORTAGE = "stock_shortage", _("Stock shortage")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        ISSUED = "issued", _("Issued")
        ACKNOWLEDGED = "acknowledged", _("Acknowledged")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="disciplinary_records"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    category = models.CharField(max_length=16, choices=Category.choices)
    incident_on = models.DateField()
    issued_on = models.DateField()
    issued_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    description = models.TextField()
    evidence = models.FileField(
        storage=private_storage, upload_to=private_upload_to("lifecycle/evidence"), blank=True
    )
    # Until when it counts (a verbal warning 3 months, a written one 6, a final one 12).
    expires_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ISSUED)
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    # The person's explanation, written in the mini app.
    employee_response = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    fine_id = models.PositiveBigIntegerField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    withdraw_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-issued_on", "-pk"]
        indexes = [
            models.Index(fields=["company", "issued_on"]),
            models.Index(fields=["company", "status"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.membership}"
