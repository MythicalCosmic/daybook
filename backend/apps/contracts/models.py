"""The business's own contracts: leases, supply and service contracts, licences and franchises,
insurance. Who with, where, when they start and end, auto-renewal and its notice, the money, and
the signed scan with its annexes. Employment contracts are HR's (`apps.hr.models.Contract`).

A contract's `status` is kept by `services.refresh_status` from its dates: `active` while in
force, `ending` once its end is within the company's warning days (or a termination date is
set), `ended` after its last day, `terminated` from the day it was stopped early. `draft` is set
by hand and stays until someone makes it active. An auto-renewing contract never ends by itself:
the daily job (`watch.maintain`) moves its end on by `renewal_months` the day after it.
"""

from datetime import date, timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.money import CurrencyField, MoneyField
from apps.core.storage import private_storage, private_upload_to


class ContractSettings(models.Model):
    """The company's contract reminders. Lazy: `apps.contracts.conf.get_settings(company)`."""

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="contract_settings"
    )
    remind_days = models.PositiveSmallIntegerField(
        default=30, help_text=_("Days before a contract ends to warn.")
    )
    notice_remind_days = models.PositiveSmallIntegerField(
        default=14,
        help_text=_("Days before the notice deadline of an auto-renewing contract to warn."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "contract settings"

    def __str__(self):
        return f"Contract settings of {self.company}"


class BusinessContract(TenantModel):
    """One contract of the business with someone else (not an employment contract)."""

    class Kind(models.TextChoices):
        LEASE = "lease", _("Lease")
        SUPPLY = "supply", _("Supply")
        SERVICE = "service", _("Service")
        LICENCE = "licence", _("Licence or franchise")
        INSURANCE = "insurance", _("Insurance")
        OTHER = "other", _("Other")

    class Period(models.TextChoices):
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")
        YEARLY = "yearly", _("Yearly")
        ONCE = "once", _("Once")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        ENDING = "ending", _("Ending")
        ENDED = "ended", _("Ended")
        TERMINATED = "terminated", _("Terminated")

    # In force: reminders, the forecast's payment rule and the insight read these.
    IN_FORCE = (Status.ACTIVE, Status.ENDING)

    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="business_contracts"
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_contracts",
        help_text=_("Empty: the whole company."),
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=200)
    counterparty = models.ForeignKey(
        "finance.Counterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="business_contracts",
    )
    number = models.CharField(max_length=64, blank=True)
    signed_on = models.DateField(null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(
        null=True, blank=True, help_text=_("The last day in force. Empty: no end date.")
    )
    auto_renews = models.BooleanField(
        default=False, help_text=_("Renews by itself unless one side gives notice.")
    )
    renewal_months = models.PositiveSmallIntegerField(
        default=12, help_text=_("How long each renewal lasts, in months.")
    )
    notice_days = models.PositiveSmallIntegerField(
        default=30, help_text=_("How many days before the end notice must be given.")
    )
    amount = MoneyField(null=True, blank=True)
    period = models.CharField(max_length=10, choices=Period.choices, default=Period.MONTHLY)
    currency = CurrencyField()
    payment_day = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("The day of the month it is paid, 1 to 31.")
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    responsible = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_contracts",
        help_text=_("Who looks after it; they hear about its dates too."),
    )
    in_forecast = models.BooleanField(
        default=False,
        help_text=_("Its payment is a recurring payment in Finance, so the cash forecast sees it."),
    )
    rule = models.ForeignKey(
        "finance.RecurringRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_contracts",
    )
    terminated_on = models.DateField(null=True, blank=True)
    termination_reason = models.CharField(max_length=300, blank=True)
    last_renewed_on = models.DateField(
        null=True,
        blank=True,
        help_text=_("When its end date last moved on (by itself or by hand)."),
    )
    renewal_confirmed_for = models.DateField(
        null=True,
        blank=True,
        help_text=_("The end date whose renewal the owner confirmed: the decision is made."),
    )
    # Reminders already sent, as "<what>:<day>:<step>" (the day makes a renewed term's
    # reminders new ones).
    reminders_sent = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["ends_on", "title", "pk"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "ends_on"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True)
                | Q(starts_on__isnull=True)
                | Q(ends_on__gte=F("starts_on")),
                name="contracts_ends_after_start",
            ),
            models.CheckConstraint(
                condition=Q(payment_day__isnull=True) | Q(payment_day__gte=1, payment_day__lte=31),
                name="contracts_payment_day_in_month",
            ),
            models.CheckConstraint(
                condition=Q(amount__isnull=True) | Q(amount__gte=0),
                name="contracts_amount_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(renewal_months__gte=1, renewal_months__lte=120),
                name="contracts_renewal_months_range",
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def notice_deadline(self) -> date | None:
        """The last day to tell the other side it shouldn't renew (auto-renewing only)."""
        if not self.auto_renews or self.ends_on is None:
            return None
        return self.ends_on - timedelta(days=self.notice_days)


class ContractFile(TenantModel):
    """The signed contract, an annex or another paper of it (a PDF or a picture). Private:
    opened through signed links by people who may see the contract."""

    class Kind(models.TextChoices):
        SIGNED = "signed", _("Signed contract")
        ANNEX = "annex", _("Annex")
        OTHER = "other", _("Other document")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="contract_files")
    contract = models.ForeignKey(BusinessContract, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.SIGNED)
    file = models.FileField(storage=private_storage, upload_to=private_upload_to("contracts"))
    label = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["kind", "created_at", "pk"]

    def __str__(self):
        return f"{self.contract} {self.kind}"
