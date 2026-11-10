"""Models of the people lifecycle (docs/PLAN-OWNER.md §13.4, with the pharmacy categories of
§14.14): disciplinary records, leaving (terminations, with their handover list) and job changes.
Suspensions are the membership's own status (`members.services.suspend/reinstate`); equipment
is apps.assets; the org chart and reviews come later."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, TenantModel
from apps.core.money import CurrencyField, MoneyField
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Department, Membership, Position


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


class Termination(TenantModel):
    """Someone leaving: asked for in the mini app (a resignation) or started by a manager, a last
    working day agreed, the handover list ticked off, and on that day's evening the person
    leaves through the offboarding service (`members.services.complete_offboarding`), payroll
    preparing their final payslip (apps.lifecycle.terminations)."""

    class Kind(models.TextChoices):
        RESIGNATION = "resignation", _("Resignation")
        COMPANY = "company", _("By the company")
        CONTRACT_END = "contract_end", _("End of contract")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        AGREED = "agreed", _("Last day agreed")
        COMPLETED = "completed", _("Left")
        WITHDRAWN = "withdrawn", _("Withdrawn")
        DECLINED = "declined", _("Declined")

    class Rehire(models.TextChoices):
        YES = "yes", _("Yes")
        MAYBE = "maybe", _("Maybe")
        NO = "no", _("No")

    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="terminations"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.RESIGNATION)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    # In the person's own words (a resignation) or the manager's.
    reason = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    requested_at = models.DateTimeField()
    # The day the person asked for; the agreed one is `last_day` (their last working day).
    wished_last_day = models.DateField(null=True, blank=True)
    last_day = models.DateField(null=True, blank=True)
    agreed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    agreed_at = models.DateTimeField(null=True, blank=True)
    # Declined or withdrawn: by whom, when and why.
    closed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=300, blank=True)
    # Left: when (None `completed_by`: the evening job), and the day that was their last.
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    left_on = models.DateField(null=True, blank=True)
    # What payroll's final settlement gets on the last evening.
    final_payslip = models.BooleanField(default=True)
    leave_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    rehire = models.CharField(max_length=8, choices=Rehire.choices, blank=True)
    # HR's own notes, never shown to the person.
    notes = models.TextField(blank=True)
    # The person's answers before they go: {"reason", "better", "recommend", "answered_at"}.
    exit_interview = models.JSONField(default=dict, blank=True)
    # What happened, in order: [{"kind", "at", "by", "name", "day", "note"}].
    events = models.JSONField(default=list, blank=True)
    # Still open when they left: handover items and offboarding blockers (texts).
    left_open = models.JSONField(default=list, blank=True)
    # Why the evening job couldn't finish it (it waits for "Try again" then).
    error = models.CharField(max_length=300, blank=True)
    reminded_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership"],
                condition=Q(status__in=("requested", "agreed")),
                name="lifecycle_one_open_termination",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "last_day"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.membership}"

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.REQUESTED, self.Status.AGREED)


class HandoverItem(TenantModel):
    """One thing to hand over before someone leaves: equipment they hold (an apps.assets asset),
    their open tasks, keys, documents, or anything HR adds. Ticked off by HR."""

    class Kind(models.TextChoices):
        EQUIPMENT = "equipment", _("Equipment")
        TASKS = "tasks", _("Open tasks")
        KEYS = "keys", _("Keys")
        DOCUMENTS = "documents", _("Documents")
        OTHER = "other", _("Other")

    termination = models.ForeignKey(Termination, on_delete=models.CASCADE, related_name="handover")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    # Empty for the standard items (keys, documents, tasks): the apps name them in the reader's
    # language. Equipment carries the asset's number and name, other items HR's own words.
    title = models.CharField(max_length=200, blank=True)
    asset_id = models.PositiveBigIntegerField(null=True, blank=True)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note = models.CharField(max_length=300, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["termination", "asset_id"],
                condition=Q(asset_id__isnull=False),
                name="lifecycle_handover_one_item_an_asset",
            ),
        ]

    def __str__(self):
        return self.title or self.get_kind_display()


class JobChange(TenantModel):
    """A new position, home branch, department or pay for someone from a day: proposed,
    approved by someone who may (never about themselves), and applied on that day through the
    owning apps' services (apps.lifecycle.job_changes). `before` and `after` keep what it was
    and what it became, for the person's history."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        APPLIED = "applied", _("Applied")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="job_changes")
    effective_on = models.DateField()
    # Which of position, branch, department and pay change (a cleared department is
    # "department" with no `department`).
    parts = models.JSONField(default=list)
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # The new home branch: they move there from their old one.
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Payroll's pay type (blank keeps the current one) and the new amount.
    pay_type = models.CharField(max_length=10, blank=True)
    pay_amount = MoneyField(null=True, blank=True)
    pay_currency = CurrencyField()
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    proposed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    # {"position": {"id", "name"} | None, "branch": …, "branches": [names], "department": …,
    #  "role": name | None, "pay": {"amount", "currency", "pay_type"} | None}
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    # Why it couldn't be applied on its day (it waits for "Try again" then).
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-effective_on", "-pk"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "effective_on"]),
        ]

    def __str__(self):
        return f"{self.membership} · {self.effective_on}"
