"""Models of stock: the medicines catalogue and its batches (docs/PLAN-OWNER.md §14.6).

W2.a (§14.5) lands the catalogue (`Manufacturer`, `ProductCategory`, `Product` with every field
of §14.6.1) and `StockBatch`, so the sales lines (J2) and the people lifecycle (S) code against
committed models; J1 owns them afterwards and adds the rest of §14.6.1 (stock per batch,
movements, goods receipts, transfers, write-offs, counts, recalls, the journals).

Stock is counted in the **smallest part the pharmacy sells** (a blister, an ampoule, a tablet):
`units_per_pack` parts make one pack, prices are per pack. Every unit of stock belongs to a
batch (series, expiry date, supplier, cost), and deductions take the earliest-expiring sellable
batch first (FEFO).
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, TenantModel
from apps.core.money import CurrencyField, MoneyField
from apps.core.storage import private_storage, private_upload_to

QTY = {"max_digits": 14, "decimal_places": 3}
PERCENT = {"max_digits": 5, "decimal_places": 2}


def default_expiry_steps() -> list[int]:
    return [90, 60, 30]


def default_rx_keep_months() -> dict[str, int]:
    """How long a prescription is kept, by its kind (§14.4 row 11, read 21.10.2026)."""
    return {"regular": 3, "benefit": 36, "narcotic": 60, "psychotropic": 12, "listed": 12}


class StockSettings(models.Model):
    """The company's stock policy and its legal numbers. Lazy: `apps.inventory.conf.get_settings`.

    Every legal number defaults to the value docs/PLAN-OWNER.md §14.4 reports (read 21.10.2026);
    changing one is the company's decision. Where a rule applies is a branch setting
    (`Branch.controlled_licence`, `social_pharmacy`, `e_prescription_area`)."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="stock_settings")
    expiry_steps = ArrayField(
        models.PositiveSmallIntegerField(),
        default=default_expiry_steps,
        blank=True,
        help_text=_("Days before expiry to warn, e.g. 90, 60, 30. The expiry day always warns."),
    )
    min_shelf_days = models.PositiveSmallIntegerField(
        default=180, help_text=_("A delivery expiring sooner than this many days gets a warning.")
    )
    fefo_strict = models.BooleanField(
        default=True,
        help_text=_(
            "Taking a later-expiring batch while an earlier one is on sale needs a reason."
        ),
    )
    allow_negative = models.BooleanField(
        default=True,
        help_text=_(
            "Sales recorded before their delivery take stock below zero (flagged) instead of "
            "being refused."
        ),
    )
    default_markup_percent = models.DecimalField(
        **PERCENT, default=25, help_text=_("Markup on the purchase price for OTC goods.")
    )
    rx_max_markup_percent = models.DecimalField(
        **PERCENT,
        default=20,
        help_text=_(
            "Legal maximum retail markup of a prescription medicine on its purchase price."
        ),
    )
    social_max_markup_percent = models.DecimalField(
        **PERCENT,
        default=10,
        help_text=_("Legal maximum markup of a socially significant medicine."),
    )
    cap_enforced = models.BooleanField(
        default=True, help_text=_("A price above a legal cap is refused, not just flagged.")
    )
    price_rounding = MoneyField(
        default=100,
        help_text=_("Prices round up to this step, and down when a cap would be crossed."),
    )
    price_jump_percent = models.DecimalField(
        **PERCENT,
        default=10,
        help_text=_("A delivery cost higher than the last one by more than this warns."),
    )
    writeoff_approval = models.BooleanField(
        default=True, help_text=_("Write-offs wait for a manager's approval.")
    )
    show_other_branches = models.BooleanField(
        default=True, help_text=_("The app's stock lookup shows what the other pharmacies have.")
    )
    camera_scanning = models.BooleanField(
        default=True,
        help_text=_("The app offers barcode scanning with the camera where the phone supports it."),
    )
    rx_log = models.BooleanField(
        default=True, help_text=_("Keep the prescription log of dispensed prescriptions.")
    )
    count_tolerance = MoneyField(
        default=50000,
        help_text=_("A stock count shortage above this, at cost, notifies the owners."),
    )
    destroy_within_days = models.PositiveSmallIntegerField(
        default=30, help_text=_("Unfit goods are destroyed within this many days of approval.")
    )
    destroy_commission_min = models.PositiveSmallIntegerField(
        default=5, help_text=_("Members a destruction commission needs at least.")
    )
    rx_keep_months = models.JSONField(
        default=default_rx_keep_months,
        blank=True,
        help_text=_("Months a prescription is kept, by its kind."),
    )
    rx_destroy_commission_min = models.PositiveSmallIntegerField(
        default=3, help_text=_("Members needed to destroy narcotic and psychotropic prescriptions.")
    )
    narcotic_rx_valid_days = models.PositiveSmallIntegerField(
        default=7, help_text=_("Days a narcotic prescription is valid.")
    )
    psychotropic_rx_valid_months = models.PositiveSmallIntegerField(
        default=1, help_text=_("Months a psychotropic prescription is valid.")
    )
    psychotropic_stock_months = models.PositiveSmallIntegerField(
        default=1, help_text=_("Psychotropic stock on hand may cover at most this many months.")
    )
    controlled_close_day = models.PositiveSmallIntegerField(
        default=3, help_text=_("The controlled-substance month is closed by this day.")
    )
    controlled_report_days = models.PositiveSmallIntegerField(
        default=3, help_text=_("Days to report a controlled-substance difference.")
    )
    next_receipt_number = models.PositiveIntegerField(default=1)
    next_transfer_number = models.PositiveIntegerField(default=1)
    next_writeoff_number = models.PositiveIntegerField(default=1)
    # The daily scan's bookkeeping: the company day it last ran, and the month whose expiry
    # shelf-check tasks were made.
    scanned_on = models.DateField(null=True, blank=True, editable=False)
    shelf_check_month = models.DateField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "stock settings"

    def __str__(self):
        return f"Stock settings of {self.company}"

    def keep_months(self, rx_kind: str) -> int:
        months = (self.rx_keep_months or {}).get(rx_kind)
        if months is None:
            months = default_rx_keep_months().get(rx_kind, 3)
        return int(months)


class Manufacturer(TenantModel):
    name = models.CharField(max_length=120)
    country = models.CharField(
        max_length=2, blank=True, help_text=_("Two-letter country code (ISO 3166-1), e.g. UZ.")
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="inventory_unique_manufacturer_name"
            ),
        ]

    def __str__(self):
        return self.name


class ProductCategory(TenantModel):
    """At most two levels: a group ("Antibiotics") and its subgroups."""

    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "product categories"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Product(TenantModel):
    """A medicine or another item the pharmacy holds: "Paratsetamol 500 mg tabletka №20"."""

    class Kind(models.TextChoices):
        MEDICINE = "medicine", _("Medicine")
        DEVICE = "device", _("Medical device")
        SUPPLEMENT = "supplement", _("Supplement")
        COSMETIC = "cosmetic", _("Cosmetics and hygiene")
        OTHER = "other", _("Other goods")
        SERVICE = "service", _("Service")

    class DosageForm(models.TextChoices):
        TABLET = "tablet", _("Tablet")
        CAPSULE = "capsule", _("Capsule")
        SYRUP = "syrup", _("Syrup")
        SUSPENSION = "suspension", _("Suspension")
        SOLUTION = "solution", _("Solution")
        INJECTION = "injection", _("Injection")
        POWDER = "powder", _("Powder")
        OINTMENT = "ointment", _("Ointment")
        CREAM = "cream", _("Cream")
        GEL = "gel", _("Gel")
        EYE_DROPS = "eye_drops", _("Eye drops")
        EAR_DROPS = "ear_drops", _("Ear drops")
        NASAL = "nasal", _("Nasal drops or spray")
        SPRAY = "spray", _("Spray")
        SUPPOSITORY = "suppository", _("Suppository")
        PATCH = "patch", _("Patch")
        OTHER = "other", _("Other form")

    class ControlClass(models.TextChoices):
        """Subject-quantitative accounting (§14.4 rows 22 and 23)."""

        NONE = "none", _("Not controlled")
        NARCOTIC = "narcotic", _("Narcotic")
        PSYCHOTROPIC = "psychotropic", _("Psychotropic")
        PRECURSOR = "precursor", _("Contains a precursor")
        STRONG = "strong", _("Strong-acting (listed)")

    class Storage(models.TextChoices):
        ROOM = "room", _("Room temperature, 15–25 °C")
        COOL = "cool", _("Cool place, 8–15 °C")
        COLD = "cold", _("Fridge, 2–8 °C")
        FROZEN = "frozen", _("Freezer, −18 °C or colder")

    name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=120, blank=True)
    inn = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text=_(
            "Active ingredient (INN), lowercase Latin; a combination sorted and joined with +."
        ),
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MEDICINE)
    dosage_form = models.CharField(max_length=16, choices=DosageForm.choices, blank=True)
    strength = models.CharField(max_length=40, blank=True, help_text=_('"500 mg", "250 mg/5 ml"'))
    units_per_pack = models.PositiveSmallIntegerField(
        default=1,
        help_text=_(
            "Parts sold separately in one pack (blisters, ampoules, tablets); 1 sells whole "
            "packs only. A part may be sold only when it shows the name, series, expiry and "
            "maker, never from a damaged pack."
        ),
    )
    part_label = models.CharField(
        max_length=12, blank=True, help_text=_('What one part is called: "blister", "ampoule".')
    )
    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.PROTECT, null=True, blank=True, related_name="products"
    )
    category = models.ForeignKey(
        ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    rx_required = models.BooleanField(
        default=False,
        help_text=_("Prescription only: everything not on the Ministry of Health's OTC list."),
    )
    e_rx_group = models.BooleanField(
        default=False, help_text=_("In a group that must be prescribed electronically.")
    )
    control_class = models.CharField(
        max_length=12, choices=ControlClass.choices, default=ControlClass.NONE
    )
    restricted_channel = models.BooleanField(
        default=False,
        help_text=_(
            "A starred strong-acting medicine: held only at licensed or social pharmacies."
        ),
    )
    storage = models.CharField(max_length=6, choices=Storage.choices, default=Storage.ROOM)
    light_sensitive = models.BooleanField(default=False)
    barcode = models.CharField(
        max_length=32, blank=True, db_index=True, help_text=_("The pack's main EAN-13.")
    )
    sku = models.CharField(max_length=64, blank=True)
    mxik_code = models.CharField(
        max_length=17, blank=True, help_text=_("The product code of tasnif.soliq.uz (MXIK).")
    )
    package_code = models.CharField(max_length=20, blank=True)
    registration_number = models.CharField(
        max_length=40, blank=True, help_text=_("The state registration certificate.")
    )
    registration_until = models.DateField(null=True, blank=True)
    marking_required = models.BooleanField(
        default=False, help_text=_("Carries a digital marking code (Asl belgisi).")
    )
    vat_percent = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Empty: the company's rate from its tax regime."),
    )
    socially_significant = models.BooleanField(
        default=False, help_text=_("A socially significant medicine: a lower markup cap.")
    )
    mandatory_list = models.BooleanField(
        default=False,
        help_text=_("On the Ministry of Health's list every pharmacy must keep in stock."),
    )
    reference_price = MoneyField(
        null=True,
        blank=True,
        help_text=_("The registry's maximum price per pack for a prescription medicine."),
    )
    reference_price_on = models.DateField(null=True, blank=True)
    sale_price = MoneyField(
        default=0,
        help_text=_(
            "Per pack: the price of the batch sold next, or the list price of an item without "
            "batches."
        ),
    )
    part_price = MoneyField(
        null=True,
        blank=True,
        help_text=_("Per part; empty: the pack price divided by the parts, rounded up."),
    )
    cost_price = MoneyField(null=True, blank=True, help_text=_("The last purchase cost per pack."))
    track_stock = models.BooleanField(default=True)
    image = models.ImageField(upload_to="products/", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "barcode"],
                condition=~Q(barcode=""),
                name="inventory_unique_product_barcode",
            ),
            models.UniqueConstraint(
                fields=["company", "sku"],
                condition=~Q(sku=""),
                name="inventory_unique_product_sku",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_controlled(self) -> bool:
        return self.control_class != self.ControlClass.NONE


class StockBatch(TenantModel):
    """One series of a product as it arrived: its expiry, supplier, cost and retail price.
    "Expired" is derived from `expires_on`, never stored."""

    class Status(models.TextChoices):
        SELLABLE = "sellable", _("On sale")
        QUARANTINE = "quarantine", _("In quarantine")
        RECALLED = "recalled", _("Recalled")

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="batches")
    series = models.CharField(max_length=40)
    expires_on = models.DateField()
    made_on = models.DateField(null=True, blank=True)
    supplier = models.ForeignKey(
        "finance.Counterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_batches",
    )
    unit_cost = MoneyField(
        help_text=_(
            "Per pack as the distributor's invoice charges it (VAT included), frozen when posted."
        )
    )
    retail_price = MoneyField(
        help_text=_("Per pack; a prescription batch is never priced above its legal cap.")
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SELLABLE)
    receipt_line = models.OneToOneField(
        "inventory.GoodsReceiptLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batch",
        help_text=_("The delivery line it came with; empty for opening stock or a count surplus."),
    )
    origin = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="twins",
        help_text=_("For refunded goods held apart in quarantine: the batch they were sold from."),
    )

    class Meta:
        verbose_name_plural = "stock batches"
        ordering = ["expires_on", "pk"]
        indexes = [
            models.Index(
                fields=["company", "product", "expires_on"], name="inventory_batch_fefo_idx"
            ),
        ]

    def __str__(self):
        return f"{self.product} · {self.series}"


class ProductCode(TenantModel):
    """Another code that names a product: a second barcode, a distributor's own item code
    (price lists, invoices), or the code of the pharmacy's cash-register program."""

    class Kind(models.TextChoices):
        BARCODE = "barcode", _("Barcode")
        SUPPLIER = "supplier", _("Distributor's code")
        POS = "pos", _("Cash register code")

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="codes")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    code = models.CharField(max_length=64)
    supplier = models.ForeignKey(
        "finance.Counterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="product_codes",
    )

    class Meta:
        ordering = ["kind", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "supplier", "code"],
                nulls_distinct=False,
                name="inventory_unique_product_code",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.code}"


class SupplierProfile(TenantModel):
    """What stock needs to know about a distributor (a supplier counterparty)."""

    class Channel(models.TextChoices):
        TELEGRAM = "telegram", _("Telegram")
        EMAIL = "email", _("Email")
        PHONE = "phone", _("Phone")
        PORTAL = "portal", _("Their website")
        OTHER = "other", _("Other")

    counterparty = models.OneToOneField(
        "finance.Counterparty", on_delete=models.PROTECT, related_name="supplier_profile"
    )
    payment_terms_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=_("Days to pay for a delivery: its due date. Empty: paid on delivery."),
    )
    official_dealer = models.BooleanField(
        default=False,
        help_text=_("The importer or an official dealer of the imported medicines it brings."),
    )
    delivery_days = models.PositiveSmallIntegerField(default=1)
    min_order = MoneyField(null=True, blank=True)
    order_channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.PHONE)
    telegram_username = models.CharField(max_length=64, blank=True)
    price_list_mapping = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["counterparty__name"]

    def __str__(self):
        return str(self.counterparty)


class BatchStock(models.Model):
    """What one branch holds of one batch, in parts. Changed only by `inventory.services`,
    under `select_for_update`."""

    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(StockBatch, on_delete=models.CASCADE, related_name="stocks")
    quantity = models.DecimalField(**QTY, default=0)
    # The tightest expiry step this branch was already told about for this batch (0: expired).
    notified_step = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "batch"], name="inventory_unique_batch_stock"
            ),
        ]

    def __str__(self):
        return f"{self.batch} @ {self.branch_id}: {self.quantity}"


class StockLevel(models.Model):
    """What a branch holds of a product: the sum of its batches, less a shortfall (parts sold
    before their delivery was recorded, settled by the next delivery). A cache kept by the
    services."""

    branch = models.ForeignKey("companies.Branch", on_delete=models.CASCADE, related_name="+")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="levels")
    quantity = models.DecimalField(**QTY, default=0)
    shortfall = models.DecimalField(
        **QTY, default=0, help_text=_("Parts sold without stock, waiting for a delivery.")
    )
    min_qty = models.DecimalField(**QTY, null=True, blank=True)
    max_qty = models.DecimalField(**QTY, null=True, blank=True)
    low_since = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["branch", "product"], name="inventory_unique_level"),
        ]

    def __str__(self):
        return f"{self.product} @ {self.branch_id}: {self.quantity}"


class StockMovement(TenantModel):
    """One change of stock, in parts (signed). The sum of a batch's movements at a branch is
    its stock there; movements without a batch are a shortfall and its settlement. Quarantine
    and release change no quantity (0): they record a batch leaving or coming back to sale."""

    class Kind(models.TextChoices):
        OPENING = "opening", _("Opening stock")
        RECEIPT = "receipt", _("Delivery")
        SALE = "sale", _("Sale")
        REFUND = "refund", _("Refund")
        WRITEOFF = "writeoff", _("Write-off")
        TRANSFER_OUT = "transfer_out", _("Sent to another pharmacy")
        TRANSFER_IN = "transfer_in", _("Received from another pharmacy")
        COUNT_ADJUSTMENT = "count_adjustment", _("Count adjustment")
        QUARANTINE = "quarantine", _("Quarantine")
        RELEASE = "release", _("Back on sale")

    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="movements"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    quantity = models.DecimalField(**QTY)
    unit_cost = MoneyField(null=True, blank=True, help_text=_("Per part, at the batch's cost."))
    document_type = models.CharField(max_length=32, blank=True)
    document_id = models.PositiveBigIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=16, blank=True)
    created_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-at", "-pk"]
        indexes = [
            models.Index(fields=["company", "product", "at"], name="inventory_move_product_idx"),
            models.Index(fields=["company", "branch", "at"], name="inventory_move_branch_idx"),
            models.Index(fields=["document_type", "document_id"], name="inventory_move_doc_idx"),
        ]

    def __str__(self):
        return f"{self.kind} {self.quantity} {self.product}"


class GoodsReceipt(TenantModel):
    """A delivery from a distributor against its invoice (Kirim, nakladnoy). A draft is
    submitted by the pharmacist and posted by someone with stock.manage: posting makes the
    batches, puts them on stock and opens the payable."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Waiting for posting")
        POSTED = "posted", _("Posted")
        VOID = "void", _("Void")

    class Marking(models.TextChoices):
        NONE = "none", _("Not needed")
        PENDING = "pending", _("Waiting")
        ACCEPTED = "accepted", _("Accepted")

    number = models.CharField(max_length=24, blank=True)
    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    supplier = models.ForeignKey(
        "finance.Counterparty", on_delete=models.PROTECT, related_name="goods_receipts"
    )
    supplier_invoice_number = models.CharField(max_length=40, blank=True)
    supplier_invoice_date = models.DateField()
    currency = CurrencyField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    total = MoneyField(default=0)
    vat_total = MoneyField(default=0)
    due_on = models.DateField(null=True, blank=True)
    file = models.FileField(
        storage=private_storage, upload_to=private_upload_to("inventory/receipts"), blank=True
    )
    note = models.TextField(blank=True)
    received_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    debt = models.ForeignKey(
        "finance.Debt", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    e_invoice_ref = models.CharField(max_length=64, blank=True)
    marking_state = models.CharField(max_length=10, choices=Marking.choices, default=Marking.NONE)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    void_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-supplier_invoice_date", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "number"],
                condition=~Q(number=""),
                name="inventory_unique_receipt_number",
            ),
            models.UniqueConstraint(
                fields=["company", "supplier", "supplier_invoice_number"],
                condition=~Q(status="void") & ~Q(supplier_invoice_number=""),
                name="inventory_unique_supplier_invoice",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "status"], name="inventory_receipt_status_idx"),
        ]

    def __str__(self):
        return self.number or f"#{self.pk}"


class GoodsReceiptLine(models.Model):
    """One line of a delivery: a product, its series and expiry, packs and the cost per pack.
    Posting turns it into one batch."""

    class Warning(models.TextChoices):
        SHORT_SHELF_LIFE = "short_shelf_life", _("Short shelf life")
        COST_JUMP = "cost_jump", _("Cost jumped")
        RECALLED_SERIES = "recalled_series", _("Recalled series")
        OVER_PRICE_CAP = "over_price_cap", _("Price lowered to the legal cap")
        REGISTRATION_EXPIRED = "registration_expired", _("Registration expired")
        RX_FLAG_MISMATCH = "rx_flag_mismatch", _("Prescription flag differs")
        NOT_OFFICIAL_DEALER = "not_official_dealer", _("Not an official dealer")
        OVER_MONTH_NEED = "over_month_need", _("More than a month's need")
        NOT_LICENSED_BRANCH = "not_licensed_branch", _("Branch not licensed for it")

    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    series = models.CharField(max_length=40)
    expires_on = models.DateField()
    made_on = models.DateField(null=True, blank=True)
    packs = models.DecimalField(max_digits=12, decimal_places=3)
    quantity = models.DecimalField(**QTY, help_text=_("Parts: packs times parts per pack."))
    unit_cost = MoneyField(help_text=_("Per pack, as the invoice charges it (VAT included)."))
    vat_percent = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    total = MoneyField(default=0)
    retail_price = MoneyField(null=True, blank=True)
    supplier_rx = models.BooleanField(
        null=True, blank=True, help_text=_("What the distributor's file says about prescription.")
    )
    warnings = ArrayField(models.CharField(max_length=24), default=list, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.product} · {self.series}"


class StockTransfer(TenantModel):
    """Goods sent from one pharmacy to another: the same batches leave and arrive."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SENT = "sent", _("On the way")
        RECEIVED = "received", _("Received")
        DISPUTED = "disputed", _("Disputed")
        VOID = "void", _("Void")

    class Resolution(models.TextChoices):
        SHORTAGE = "shortage", _("Lost on the way: written off")
        FOUND = "found", _("Found at the receiving pharmacy")
        RETURNED = "returned", _("Back at the sending pharmacy")

    number = models.CharField(max_length=24, blank=True)
    from_branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    to_branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(max_length=10, choices=Resolution.choices, blank=True)
    resolved_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(from_branch=models.F("to_branch")),
                name="inventory_transfer_two_branches",
            ),
            models.UniqueConstraint(
                fields=["company", "number"],
                condition=~Q(number=""),
                name="inventory_unique_transfer_number",
            ),
        ]

    def __str__(self):
        return self.number or f"#{self.pk}"


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantity_sent = models.DecimalField(**QTY)
    quantity_received = models.DecimalField(**QTY, null=True, blank=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.product_id} × {self.quantity_sent}"


class WriteOff(TenantModel):
    """Goods taken off stock (Hisobdan chiqarish): proposed with a reason and photos, approved
    by a manager (which deducts the batches at their cost), and for unfit goods destroyed by a
    commission with an act. Never a ledger row: the cost was booked when the goods arrived."""

    class Reason(models.TextChoices):
        EXPIRED = "expired", _("Expired")
        DAMAGED = "damaged", _("Damaged")
        RECALL = "recall", _("Recalled series")
        QUALITY = "quality", _("Quality defect")
        SHORTAGE = "shortage", _("Shortage")
        INTERNAL_USE = "internal_use", _("Used by the pharmacy")
        OTHER = "other", _("Other")

    UNFIT = ("expired", "damaged", "recall", "quality")

    class Status(models.TextChoices):
        PROPOSED = "proposed", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        DESTROYED = "destroyed", _("Destroyed")
        VOID = "void", _("Void")

    class Method(models.TextChoices):
        CRUSH = "crush", _("Crushing")
        DILUTE = "dilute", _("Dilution")
        INCINERATE = "incinerate", _("Incineration")
        DISPOSAL = "disposal", _("Handed to a disposal company")
        DECONTAMINATE = "decontaminate", _("Decontamination")
        OTHER = "other", _("Other method")

    number = models.CharField(max_length=24, blank=True)
    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=16, choices=Reason.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    note = models.TextField(blank=True)
    proposed_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    value = MoneyField(default=0, help_text=_("At the batches' cost, frozen when approved."))
    destroy_by = models.DateField(null=True, blank=True)
    responsible = models.CharField(max_length=150, blank=True)
    order_number = models.CharField(max_length=40, blank=True)
    commission = models.JSONField(default=list, blank=True)
    method = models.CharField(max_length=16, choices=Method.choices, blank=True)
    place = models.CharField(max_length=200, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)
    destroyed_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    act_pdf = models.FileField(
        storage=private_storage, upload_to=private_upload_to("inventory/acts"), blank=True
    )
    sent_to = models.JSONField(default=list, blank=True)
    recall = models.ForeignKey(
        "inventory.RecallNotice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="writeoffs",
    )
    transfer = models.ForeignKey(
        StockTransfer, on_delete=models.SET_NULL, null=True, blank=True, related_name="writeoffs"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "number"],
                condition=~Q(number=""),
                name="inventory_unique_writeoff_number",
            ),
        ]

    def __str__(self):
        return self.number or f"#{self.pk}"

    @property
    def needs_destruction(self) -> bool:
        return self.reason in self.UNFIT


class WriteOffLine(models.Model):
    writeoff = models.ForeignKey(WriteOff, on_delete=models.CASCADE, related_name="lines")
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(**QTY)
    unit_cost = MoneyField(default=0, help_text=_("Per part, at the batch's cost."))
    value = MoneyField(default=0)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.batch_id} × {self.quantity}"


class WriteOffFile(models.Model):
    class Kind(models.TextChoices):
        PHOTO = "photo", _("Photo")
        VIDEO = "video", _("Video")
        SIGNED_ACT = "signed_act", _("Signed act")
        ORDER = "order", _("Order")
        OTHER = "other", _("Other")

    writeoff = models.ForeignKey(WriteOff, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(
        storage=private_storage,
        upload_to=private_upload_to("inventory/writeoffs", company_attr="writeoff.company_id"),
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PHOTO)
    uploaded_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return f"{self.kind} #{self.pk}"


class StockCount(TenantModel):
    """Inventarizatsiya: counters see product, series and expiry, never the expected
    quantity. Applying books the differences per batch at its cost."""

    class Kind(models.TextChoices):
        FULL = "full", _("Full count")
        PARTIAL = "partial", _("Partial count")
        HANDOVER = "handover", _("Handover count")

    class Status(models.TextChoices):
        OPEN = "open", _("Counting")
        SUBMITTED = "submitted", _("Counted")
        APPLIED = "applied", _("Applied")

    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PARTIAL)
    category = models.ForeignKey(
        ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note = models.TextField(blank=True)
    started_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    value_difference = MoneyField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk}"


class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # A line the counter added for goods the system didn't know: their series and expiry.
    series = models.CharField(max_length=40, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    expected = models.DecimalField(**QTY, default=0, help_text=_("Never shown to counters."))
    counted = models.DecimalField(**QTY, null=True, blank=True)
    difference = models.DecimalField(**QTY, null=True, blank=True)
    counted_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.product_id} · {self.batch_id}"


class RecallNotice(TenantModel):
    """A series the regulator rejected or a distributor recalled: every matching batch in
    every branch leaves sale (`recalled`) until it is written off."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")

    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="recalls"
    )
    inn_or_name = models.CharField(max_length=200, blank=True)
    series = models.CharField(max_length=40)
    reason = models.CharField(max_length=200)
    source = models.CharField(
        max_length=200, help_text=_("The regulator's list or letter: its number and date.")
    )
    received_on = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    file = models.FileField(
        storage=private_storage, upload_to=private_upload_to("inventory/recalls"), blank=True
    )
    found = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_on", "-pk"]

    def __str__(self):
        return f"{self.inn_or_name or self.product} · {self.series}"


class ControlledPeriod(TenantModel):
    """A closed month of the controlled-substance register at a licensed branch: the balance
    computed from movements and the counted one. A difference is reported to the authorities."""

    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    month = models.DateField(help_text=_("The first day of the month."))
    opening = models.DecimalField(**QTY, default=0)
    received = models.DecimalField(**QTY, default=0)
    issued = models.DecimalField(**QTY, default=0)
    written_off = models.DecimalField(**QTY, default=0)
    closing = models.DecimalField(**QTY, default=0)
    counted = models.DecimalField(**QTY, default=0)
    difference = models.DecimalField(**QTY, default=0)
    note = models.TextField(blank=True)
    closed_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    reported_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-month", "product__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "product", "month"], name="inventory_unique_controlled_month"
            ),
        ]

    def __str__(self):
        return f"{self.product} {self.month:%m.%Y}"


class PricingRule(TenantModel):
    """A markup band: goods of a category (or every category) costing within a range."""

    category = models.ForeignKey(
        ProductCategory, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    cost_from = MoneyField(null=True, blank=True)
    cost_to = MoneyField(null=True, blank=True)
    markup_percent = models.DecimalField(**PERCENT)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.markup_percent}%"


class MissingRequest(TenantModel):
    """Defektura: something a customer asked for that the pharmacy couldn't give."""

    class Source(models.TextChoices):
        COUNTER = "counter", _("Asked at the counter")
        MANDATORY = "mandatory", _("Mandatory list")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        ORDERED = "ordered", _("Ordered")
        FULFILLED = "fulfilled", _("Arrived")
        CANCELLED = "cancelled", _("Cancelled")

    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(
        Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    name = models.CharField(max_length=200, blank=True)
    packs = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.COUNTER)
    requested_at = models.DateTimeField(default=timezone.now)
    requested_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    customer_phone = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["-requested_at", "-pk"]

    def __str__(self):
        return self.name or str(self.product)


class RxRecord(TenantModel):
    """A line of the prescription log. Never a patient's name, ID or PINFL."""

    class RxKind(models.TextChoices):
        REGULAR = "regular", _("Regular")
        BENEFIT = "benefit", _("Preferential")
        NARCOTIC = "narcotic", _("Narcotic")
        PSYCHOTROPIC = "psychotropic", _("Psychotropic")
        LISTED = "listed", _("Strong-acting (listed)")

    class Status(models.TextChoices):
        DISPENSED = "dispensed", _("Dispensed")
        INVALID = "invalid", _("Invalid prescription")

    branch = models.ForeignKey("companies.Branch", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantity = models.DecimalField(**QTY, default=1)
    document_type = models.CharField(max_length=32, blank=True)
    document_id = models.PositiveBigIntegerField(null=True, blank=True)
    prescription_number = models.CharField(max_length=40, blank=True)
    prescribed_on = models.DateField(null=True, blank=True)
    prescriber = models.CharField(max_length=120, blank=True)
    facility = models.CharField(max_length=120, blank=True)
    rx_kind = models.CharField(max_length=12, choices=RxKind.choices, default=RxKind.REGULAR)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DISPENSED)
    invalid_reason = models.CharField(max_length=200, blank=True)
    facility_notified_at = models.DateTimeField(null=True, blank=True)
    e_prescription_id = models.CharField(max_length=64, blank=True)
    photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("inventory/rx"), blank=True
    )
    keep_until = models.DateField()
    recorded_by = models.ForeignKey(
        "members.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-recorded_at", "-pk"]
        indexes = [
            models.Index(
                fields=["company", "branch", "recorded_at"], name="inventory_rx_branch_idx"
            ),
            models.Index(fields=["document_type", "document_id"], name="inventory_rx_doc_idx"),
        ]

    def __str__(self):
        return f"{self.product} · {self.prescription_number or self.pk}"
