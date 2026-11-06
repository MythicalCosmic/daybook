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

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import TenantModel
from apps.core.money import MoneyField


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
