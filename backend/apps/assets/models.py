"""Fixed assets, equipment and depreciation (Amortizatsiya).

What a pharmacy owns and uses for more than a year: fridges for vaccines, air conditioners,
shelves and counters, computers and tills, the courier's car, the renovation of a rented
branch, licences for software. Each `Asset` is valued in the company's base currency, wears
out over its useful life by one of the methods the national accounting standard allows
(NSBU No. 5 "Asosiy vositalar", in force since 1 January 2025: straight line, units of output,
double declining balance, sum of the years' digits) and is booked month by month as
depreciation: a cost that moves no money, so profit is true in the month the fridge is bought
and in every month it works.

Small things (uniforms, keys, a kettle) are `low_value` items: tracked for who holds them, never
depreciated (their cost was an expense when bought).

The model keeps history, never rewrites it: every change is an `AssetEvent`, every month's
depreciation a `DepreciationEntry` that is never edited (a later change of estimate applies
from the first month not yet posted, as the standard asks for estimates).
"""

import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.money import CurrencyField, MoneyField, RateField
from apps.core.storage import private_storage, private_upload_to


def new_qr_token() -> str:
    """The unguessable part of an asset's label link (`startapp=asset_<token>`)."""
    return secrets.token_urlsafe(12)


class Method(models.TextChoices):
    """How an asset's cost wears out (NSBU No. 5)."""

    STRAIGHT_LINE = "straight_line", _("Straight line (equal monthly amounts)")
    DECLINING = "declining", _("Declining balance (double rate)")
    SUM_OF_YEARS = "sum_of_years", _("Sum of the years' digits")
    UNITS = "units", _("By units of output")
    NONE = "none", _("Not depreciated")


class StartRule(models.TextChoices):
    """When depreciation starts and stops (the company's accounting policy)."""

    NEXT_MONTH = "next_month", _("From the 1st of the month after it is put into service")
    DAILY = "daily", _("From the day it is put into service")


class AssetSettings(models.Model):
    """The company's asset policy. Lazy: `apps.assets.conf.get_settings(company)`."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="asset_settings")
    start_rule = models.CharField(
        max_length=12, choices=StartRule.choices, default=StartRule.NEXT_MONTH
    )
    number_prefix = models.CharField(
        max_length=8, default="AV", help_text=_("Inventory numbers look like AV-0001.")
    )
    next_number = models.PositiveIntegerField(default=1)
    capitalization_threshold = MoneyField(
        null=True,
        blank=True,
        help_text=_(
            "Cheaper things are suggested as low-value items: tracked, not depreciated "
            "(your accounting policy sets the amount)."
        ),
    )
    replacement_inflation = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        help_text=_("How much dearer a replacement gets each year, in percent (for planning)."),
    )
    tax_book = models.BooleanField(
        default=False,
        help_text=_(
            "Show the tax depreciation too (straight line at the Tax Code's annual rates), for "
            "companies that pay profit tax."
        ),
    )
    remind_days = models.PositiveSmallIntegerField(
        default=30, help_text=_("Days ahead to warn about warranties, checks and insurance.")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "asset settings"

    def __str__(self):
        return f"Asset settings of {self.company}"


class AssetCategory(TenantModel):
    """A kind of asset with its defaults (useful life, method, tax group): "Pharmacy fridges"."""

    class Kind(models.TextChoices):
        FIXED = "fixed", _("Fixed asset")
        INTANGIBLE = "intangible", _("Intangible asset")
        LOW_VALUE = "low_value", _("Low-value item")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="asset_categories")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.FIXED)
    life_months = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("Default useful life, in months.")
    )
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.STRAIGHT_LINE)
    salvage_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=_("Default residual value, in percent of the cost."),
    )
    tax_group = models.CharField(
        max_length=8, blank=True, help_text=_("The Tax Code group (I–VI), for the tax book.")
    )
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Annual tax depreciation rate, in percent (at most the Tax Code's)."),
    )
    service_months = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("Default months between services.")
    )
    verify_months = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_("Default months between official instrument checks.")
    )
    icon = models.CharField(max_length=40, blank=True, help_text=_("A lucide icon name."))
    system_code = models.CharField(max_length=32, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "asset categories"
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="assets_unique_category_name"),
            models.UniqueConstraint(
                fields=["company", "system_code"],
                condition=~Q(system_code=""),
                name="assets_unique_category_code",
            ),
        ]

    def __str__(self):
        return self.name


class Asset(TenantModel):
    """One thing the company owns, with its value, where it is, who holds it and its upkeep."""

    class Status(models.TextChoices):
        IN_USE = "in_use", _("In use")
        IN_STORAGE = "in_storage", _("In storage")
        REPAIR = "repair", _("Under repair")
        SUSPENDED = "suspended", _("Mothballed")
        DISPOSED = "disposed", _("Disposed of")

    class Condition(models.TextChoices):
        NEW = "new", _("New")
        GOOD = "good", _("Good")
        WORN = "worn", _("Worn")
        DAMAGED = "damaged", _("Damaged")

    class Disposal(models.TextChoices):
        SOLD = "sold", _("Sold")
        WRITTEN_OFF = "written_off", _("Written off (broken, worn out)")
        LOST = "lost", _("Lost or stolen")
        DONATED = "donated", _("Given away")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="assets")
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name="assets")
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="assets"
    )
    number = models.CharField(max_length=24, help_text=_("Inventory number, unique per company."))
    name = models.CharField(max_length=120)
    model = models.CharField(max_length=80, blank=True, help_text=_("Brand and model."))
    serial = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_USE)
    condition = models.CharField(max_length=8, choices=Condition.choices, default=Condition.GOOD)

    # Value. `cost` is in the base currency, frozen at purchase; the original price stays too.
    purchased_on = models.DateField(null=True, blank=True)
    in_service_on = models.DateField(
        null=True, blank=True, help_text=_("Put into service: depreciation starts from it.")
    )
    cost = MoneyField(help_text=_("What it cost to buy and set up, in the base currency."))
    price = MoneyField(null=True, blank=True, help_text=_("The price in its own currency."))
    price_currency = CurrencyField()
    price_rate = RateField(default=1)
    salvage_value = MoneyField(default=0, help_text=_("What it will still be worth at the end."))
    life_months = models.PositiveSmallIntegerField(null=True, blank=True)
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.STRAIGHT_LINE)
    declining_factor = models.DecimalField(max_digits=4, decimal_places=2, default=2)
    total_units = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("For the units method: everything it will produce or run in its life."),
    )
    unit = models.CharField(max_length=16, blank=True, help_text=_("Units of output: km, hours…"))
    opening_accumulated = MoneyField(
        null=True,
        blank=True,
        help_text=_("Depreciation before it was entered here (from the old books)."),
    )
    books_depreciation = models.BooleanField(
        default=True, help_text=_("Book its monthly depreciation in Finance.")
    )
    supplier = models.ForeignKey(
        "finance.Counterparty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplied_assets",
    )
    supplier_name = models.CharField(max_length=120, blank=True)
    purchase_transaction = models.ForeignKey(
        "finance.Transaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fixed_assets",
    )

    # Who has it: the person using it, and the one accountable for it (moddiy javobgar).
    custodian = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets_held",
    )
    responsible = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets_responsible",
    )

    # Upkeep.
    warranty_until = models.DateField(null=True, blank=True)
    insurance_until = models.DateField(null=True, blank=True)
    service_months = models.PositiveSmallIntegerField(null=True, blank=True)
    next_service_on = models.DateField(null=True, blank=True)
    verify_months = models.PositiveSmallIntegerField(null=True, blank=True)
    next_verification_on = models.DateField(null=True, blank=True)

    # Disposal.
    disposed_on = models.DateField(null=True, blank=True)
    disposal = models.CharField(max_length=12, choices=Disposal.choices, blank=True)
    disposal_amount = MoneyField(null=True, blank=True)
    disposal_reason = models.CharField(max_length=300, blank=True)
    disposal_transaction = models.ForeignKey(
        "finance.Transaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="disposed_assets",
    )

    qr_token = models.CharField(max_length=24, unique=True, default=new_qr_token, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="assets_unique_number"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "branch"]),
            models.Index(fields=["company", "category"]),
            models.Index(fields=["company", "custodian"]),
        ]

    def __str__(self):
        return f"{self.number} {self.name}"

    @property
    def depreciates(self) -> bool:
        return (
            self.method != Method.NONE
            # Units of output run on the units recorded: their useful life is optional.
            and (bool(self.life_months) or self.method == Method.UNITS)
            and self.category.kind != AssetCategory.Kind.LOW_VALUE
        )


class AssetEvent(TenantModel):
    """Something that happened to an asset: the timeline on its page, and what the depreciation
    of later months depends on (additions, impairments, changes of estimate, mothballing)."""

    class Kind(models.TextChoices):
        CREATED = "created", _("Added")
        IN_SERVICE = "in_service", _("Put into service")
        MOVED = "moved", _("Moved")
        ISSUED = "issued", _("Given to someone")
        RETURNED = "returned", _("Returned")
        REPAIR = "repair", _("Repaired")
        SERVICE = "service", _("Serviced")
        VERIFICATION = "verification", _("Instrument check")
        ADDITION = "addition", _("Improvement added to its cost")
        IMPAIRMENT = "impairment", _("Value written down")
        ESTIMATE = "estimate", _("Useful life or residual value changed")
        SUSPENDED = "suspended", _("Mothballed")
        RESUMED = "resumed", _("Back in use")
        USAGE = "usage", _("Units of output recorded")
        PROBLEM = "problem", _("Problem reported")
        COUNTED = "counted", _("Found in a count")
        DISPOSED = "disposed", _("Disposed of")
        NOTE = "note", _("Note")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="asset_events")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    on = models.DateField()
    amount = MoneyField(null=True, blank=True)
    units = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    from_branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asset_events",
    )
    details = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=500, blank=True)
    transaction = models.ForeignKey(
        "finance.Transaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_events",
    )
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="asset_events"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["on", "pk"]
        indexes = [models.Index(fields=["company", "asset", "on"])]

    def __str__(self):
        return f"{self.asset} {self.kind} {self.on}"


class DepreciationEntry(TenantModel):
    """One month's depreciation of one asset, posted once and never edited."""

    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="depreciation_entries"
    )
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="entries")
    month = models.DateField(help_text=_("The first day of the month."))
    amount = MoneyField()
    book_value = MoneyField(help_text=_("Net book value after this month."))
    opening = models.BooleanField(
        default=False, help_text=_("Before the asset was entered here: never booked in Finance.")
    )
    transaction = models.ForeignKey(
        "finance.Transaction",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="depreciation_entries",
    )
    booked_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["asset", "month"]
        verbose_name_plural = "depreciation entries"
        constraints = [
            models.UniqueConstraint(fields=["asset", "month"], name="assets_one_entry_a_month"),
        ]
        indexes = [models.Index(fields=["company", "month"])]

    def __str__(self):
        return f"{self.asset} {self.month:%Y-%m} {self.amount}"


class AssetAssignment(TenantModel):
    """Who held an asset when: given out with its condition, confirmed, handed back."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="asset_assignments")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="assignments")
    membership = models.ForeignKey(
        "members.Membership", on_delete=models.CASCADE, related_name="asset_assignments"
    )
    issued_on = models.DateField()
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    condition_out = models.CharField(max_length=8, choices=Asset.Condition.choices, blank=True)
    note_out = models.CharField(max_length=300, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    returned_on = models.DateField(null=True, blank=True)
    condition_in = models.CharField(max_length=8, choices=Asset.Condition.choices, blank=True)
    note_in = models.CharField(max_length=300, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-issued_on", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset"],
                condition=Q(returned_on__isnull=True),
                name="assets_one_holder_at_a_time",
            ),
        ]
        indexes = [models.Index(fields=["company", "membership", "returned_on"])]

    def __str__(self):
        return f"{self.asset} → {self.membership}"


class AssetCount(TenantModel):
    """An inventory count (inventarizatsiya) of a branch's assets: each one found or not."""

    class Status(models.TextChoices):
        OPEN = "open", _("In progress")
        CLOSED = "closed", _("Closed")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="asset_counts")
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="asset_counts"
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    started_on = models.DateField()
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_on", "-pk"]

    def __str__(self):
        return f"Count {self.started_on} {self.branch or ''}"


class AssetCountLine(TenantModel):
    class Result(models.TextChoices):
        PENDING = "pending", _("Not checked yet")
        FOUND = "found", _("Found")
        DAMAGED = "damaged", _("Found damaged")
        MISSING = "missing", _("Missing")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="asset_count_lines")
    count = models.ForeignKey(AssetCount, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="count_lines")
    result = models.CharField(max_length=8, choices=Result.choices, default=Result.PENDING)
    checked_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["asset__number"]
        constraints = [
            models.UniqueConstraint(fields=["count", "asset"], name="assets_one_line_per_asset"),
        ]

    def __str__(self):
        return f"{self.count}: {self.asset} {self.result}"


class AssetFile(TenantModel):
    """A photo of the asset or a document (invoice, warranty card, act). Private: opened through
    signed links for people who may see the asset."""

    class Kind(models.TextChoices):
        PHOTO = "photo", _("Photo")
        DOCUMENT = "document", _("Document")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="asset_files")
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    file = models.FileField(storage=private_storage, upload_to=private_upload_to("assets"))
    label = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["kind", "-created_at"]

    def __str__(self):
        return f"{self.asset} {self.kind}"


class Permit(TenantModel):
    """A licence, permit or contract the business must keep valid (the pharmacy licence, the
    controlled-substances licence, the lease, fire safety and sanitary approvals, the cash
    register's registration, insurance), with what it is, where it applies and when it ends."""

    class Kind(models.TextChoices):
        PHARMACY_LICENCE = "pharmacy_licence", _("Pharmacy licence")
        CONTROLLED_LICENCE = "controlled_licence", _("Controlled substances licence")
        LEASE = "lease", _("Lease agreement")
        FIRE_SAFETY = "fire_safety", _("Fire safety approval")
        SANITARY = "sanitary", _("Sanitary approval")
        CASH_REGISTER = "cash_register", _("Cash register registration")
        INSURANCE = "insurance", _("Insurance policy")
        OTHER = "other", _("Other")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="permits")
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="permits"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    name = models.CharField(max_length=120)
    number = models.CharField(max_length=64, blank=True)
    issuer = models.CharField(max_length=150, blank=True, help_text=_("Who issued it."))
    issued_on = models.DateField(null=True, blank=True)
    valid_until = models.DateField(
        null=True, blank=True, help_text=_("Empty: it doesn't end (renewed by hand).")
    )
    remind_days = models.PositiveSmallIntegerField(
        default=60, help_text=_("Days ahead to start warning (renewals take time).")
    )
    responsible = models.ForeignKey(
        "members.Membership",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="permits_responsible",
    )
    notes = models.TextField(blank=True)
    file = models.FileField(
        storage=private_storage, upload_to=private_upload_to("assets/permits"), blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["valid_until", "name"]
        indexes = [models.Index(fields=["company", "valid_until"])]

    def __str__(self):
        return self.name
