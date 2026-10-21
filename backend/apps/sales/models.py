"""Sales and cash: tills, payment methods, cashier shifts, cash movements and daily totals.

docs/PLAN-OWNER.md §3.8. Sales are recorded at shift level (the Z-report totals per payment
method, a blind cash count and photos), optionally as single receipts. Every closed shift books
into the finance ledger through `apps.sales.finance_bridge`; nothing here keeps a money balance
of its own. Expected cash, differences and "cash in branch" are derived:

    expected cash = opening float + cash sales - cash refunds + deposits + from safe
                    - payouts - handovers - to safe - to bank
    difference    = counted (or the manager's recount) - expected

Rows that can be wrong are voided, never deleted. Money is `Decimal(18, 2)`; the API sends it as
strings.
"""

from datetime import time

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.money import CurrencyField, MoneyField
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership


class Voidable(models.Model):
    """Rows that can be wrong are voided, never deleted."""

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    void_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        abstract = True

    @property
    def is_void(self) -> bool:
        return self.voided_at is not None


class SalesSettings(models.Model):
    """One row per company, made on first read by `apps.sales.conf.get_settings`."""

    class Mode(models.TextChoices):
        SHIFT_TOTALS = "shift_totals", _("Shift totals from the Z-report")
        RECEIPTS = "receipts", _("Single receipts")
        INVOICES = "invoices", _("Invoices")

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="sales_settings")
    business_day_ends_at = models.TimeField(
        default=time(4, 0),
        help_text=_("Sales before this time belong to the previous business day."),
    )
    cash_tolerance = MoneyField(
        default=5000, help_text=_("Cash differences up to this amount don't raise an alert.")
    )
    blind_cash_count = models.BooleanField(
        default=True,
        help_text=_("Cashiers count the cash without seeing how much there should be."),
    )
    require_z_photo = models.BooleanField(
        default=True, help_text=_("A photo of the Z-report is required to close a shift.")
    )
    require_terminal_photo = models.BooleanField(
        default=True,
        help_text=_("A photo of the terminal slip is required when the shift took card payments."),
    )
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.SHIFT_TOTALS)
    handover_confirm_hours = models.PositiveSmallIntegerField(
        default=2, help_text=_("Owners hear about a handover nobody confirmed after this long.")
    )
    big_payout_alert = MoneyField(
        null=True, blank=True, help_text=_("Owners hear about payouts from a till above this.")
    )
    late_open_minutes = models.PositiveSmallIntegerField(
        default=10,
        help_text=_("A branch with no open till this long after opening raises an alert."),
    )
    close_alert_minutes = models.PositiveSmallIntegerField(
        default=60, help_text=_("A till still open this long after closing time raises an alert.")
    )
    next_shift_number = models.PositiveIntegerField(
        default=1, help_text=_("Taken under a row lock when a shift opens.")
    )
    evening_posted_on = models.DateField(
        null=True,
        blank=True,
        help_text=_("The last business day whose sales were posted to groups."),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "sales settings"

    def __str__(self):
        return f"Sales settings of {self.company}"


class PaymentMethod(TenantModel):
    """How customers pay: cash, cards, QR wallets, transfers, credit (nasiya), instalments."""

    class Kind(models.TextChoices):
        CASH = "cash", _("Cash")
        CARD = "card", _("Card")
        QR = "qr", _("QR or wallet")
        TRANSFER = "transfer", _("Bank transfer")
        CREDIT = "credit", _("Credit (nasiya)")
        INSTALLMENT = "installment", _("Instalments")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=50)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    account = models.ForeignKey(
        "finance.MoneyAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_methods",
        help_text=_("Where non-cash money lands, e.g. the card terminal's clearing account."),
    )
    fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text=_("What the bank or provider keeps, booked as a bank fee when a shift closes."),
    )
    system_code = models.CharField(
        max_length=16, blank=True, help_text=_("Set on the default methods; never shown.")
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="sales_unique_method_name"),
            models.UniqueConstraint(
                fields=["company", "system_code"],
                condition=~Q(system_code=""),
                name="sales_unique_method_code",
            ),
            models.CheckConstraint(
                condition=Q(fee_percent__gte=0) & Q(fee_percent__lte=100),
                name="sales_method_fee_range",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_cash(self) -> bool:
        return self.kind == self.Kind.CASH

    @property
    def is_credit(self) -> bool:
        return self.kind == self.Kind.CREDIT


class Register(TenantModel):
    """A till in a branch. Its cash lives on a finance cash account made with it."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="registers")
    name = models.CharField(max_length=50)
    cash_account = models.ForeignKey(
        "finance.MoneyAccount", on_delete=models.PROTECT, related_name="registers"
    )
    fiscal_serial = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["branch__order", "branch__name", "order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name"], name="sales_unique_register_name"),
        ]

    def __str__(self):
        return f"{self.branch.name} · {self.name}"


class CashShift(TenantModel):
    """One cashier's turn at one till, from the float count to the close."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        VERIFIED = "verified", _("Verified")
        DISPUTED = "disputed", _("Disputed")

    class Source(models.TextChoices):
        MANUAL = "manual", _("Entered by the cashier")
        IMPORT = "import", _("Imported")

    number = models.PositiveIntegerField()
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="cash_shifts")
    register = models.ForeignKey(Register, on_delete=models.PROTECT, related_name="shifts")
    cashier = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="cash_shifts")
    business_day = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.MANUAL)

    opened_at = models.DateTimeField()
    opening_float = MoneyField(default=0)
    opening_count = models.JSONField(default=dict, blank=True)
    expected_float = MoneyField(
        null=True,
        blank=True,
        help_text=_("What the till should have held at opening (what the last shift left)."),
    )

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    forced = models.BooleanField(
        default=False, help_text=_("Closed by a manager, not the cashier.")
    )
    counted_cash = MoneyField(null=True, blank=True)
    closing_count = models.JSONField(default=dict, blank=True)
    expected_cash = MoneyField(null=True, blank=True)
    difference = MoneyField(null=True, blank=True)
    fiscal_cash_total = MoneyField(null=True, blank=True)
    fiscal_card_total = MoneyField(null=True, blank=True)
    z_number = models.CharField(max_length=32, blank=True)
    receipts = models.PositiveIntegerField(
        default=0, help_text=_("Receipts (checks) on the Z-report, for the average check.")
    )
    z_photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("sales/shifts"), blank=True
    )
    terminal_photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("sales/shifts"), blank=True
    )
    cashier_note = models.TextField(blank=True)

    ai_reading = models.JSONField(default=dict, blank=True)
    ai_mismatch = models.BooleanField(default=False)

    recount_cash = MoneyField(null=True, blank=True)
    verified_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, help_text=_("The manager's note or dispute reason."))

    class Meta:
        ordering = ["-opened_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="sales_unique_shift_number"),
            models.UniqueConstraint(
                fields=["register"], condition=Q(status="open"), name="sales_one_open_per_register"
            ),
            models.UniqueConstraint(
                fields=["cashier"], condition=Q(status="open"), name="sales_one_open_per_cashier"
            ),
        ]
        indexes = [
            models.Index(fields=["company", "business_day"], name="sales_shift_day"),
            models.Index(fields=["company", "cashier", "business_day"], name="sales_shift_cashier"),
            models.Index(fields=["company", "status"], name="sales_shift_status"),
        ]

    def __str__(self):
        return self.code

    @property
    def code(self) -> str:
        """ "CHL-1042": the branch code (or "S") and the company-wide number."""
        prefix = (self.branch.code or "S").upper() if self.branch_id else "S"
        return f"{prefix}-{self.number}"

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.OPEN

    @property
    def final_count(self):
        """The cash count that decides the difference: the manager's recount, else the cashier's."""
        return self.recount_cash if self.recount_cash is not None else self.counted_cash


class ShiftPayment(models.Model):
    """A shift's totals for one payment method, as the cashier typed them at close."""

    shift = models.ForeignKey(CashShift, on_delete=models.CASCADE, related_name="payments")
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    sales = MoneyField(default=0)
    refunds = MoneyField(default=0)
    receipts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["method__order", "method_id"]
        constraints = [
            models.UniqueConstraint(fields=["shift", "method"], name="sales_unique_shift_method"),
            models.CheckConstraint(
                condition=Q(sales__gte=0) & Q(refunds__gte=0), name="sales_shift_payment_positive"
            ),
        ]

    def __str__(self):
        return f"{self.method_id}: {self.sales - self.refunds}"

    @property
    def net(self):
        return self.sales - self.refunds


class Sale(TenantModel, Voidable):
    """A single receipt (receipts mode, the dashboard, imports)."""

    class Kind(models.TextChoices):
        SALE = "sale", _("Sale")
        REFUND = "refund", _("Refund")

    class Source(models.TextChoices):
        APP = "app", _("Mini app")
        DASHBOARD = "dashboard", _("Dashboard")
        BOT = "bot", _("Bot")
        IMPORT = "import", _("Import")

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="sales")
    shift = models.ForeignKey(
        CashShift, on_delete=models.PROTECT, null=True, blank=True, related_name="sales"
    )
    register = models.ForeignKey(
        Register, on_delete=models.PROTECT, null=True, blank=True, related_name="sales"
    )
    cashier = models.ForeignKey(
        Membership, on_delete=models.PROTECT, null=True, blank=True, related_name="sales"
    )
    performed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    sold_at = models.DateTimeField()
    business_day = models.DateField()
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.SALE)
    number = models.CharField(max_length=32, blank=True)
    total = MoneyField()
    discount = MoneyField(default=0)
    counterparty = models.ForeignKey(
        "finance.Counterparty",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
    )
    note = models.CharField(max_length=300, blank=True)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.APP)
    external_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-sold_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "source", "external_id"],
                condition=~Q(external_id=""),
                name="sales_unique_sale_external",
            ),
            models.CheckConstraint(condition=Q(total__gt=0), name="sales_sale_total_positive"),
        ]
        indexes = [
            models.Index(fields=["company", "business_day"], name="sales_sale_day"),
            models.Index(fields=["company", "sold_at"], name="sales_sale_time"),
        ]

    def __str__(self):
        return self.number or f"#{self.pk}"


class SalePayment(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="+")
    amount = MoneyField()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="sales_sale_payment_positive"),
        ]

    def __str__(self):
        return f"{self.method_id}: {self.amount}"


class CashMovement(TenantModel, Voidable):
    """Cash leaving or entering a till during the day; each one is provable in the ledger."""

    class Kind(models.TextChoices):
        PAYOUT = "payout", _("Payout")
        DEPOSIT = "deposit", _("Deposit")
        HANDOVER = "handover", _("Handover")
        TO_SAFE = "to_safe", _("To the safe")
        FROM_SAFE = "from_safe", _("From the safe")
        TO_BANK = "to_bank", _("To the bank")

    INCOMING = (Kind.DEPOSIT, Kind.FROM_SAFE)

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="cash_movements")
    register = models.ForeignKey(Register, on_delete=models.PROTECT, related_name="movements")
    shift = models.ForeignKey(
        CashShift, on_delete=models.PROTECT, null=True, blank=True, related_name="movements"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = MoneyField()
    currency = CurrencyField()
    receiver = models.ForeignKey(
        Membership, on_delete=models.PROTECT, null=True, blank=True, related_name="received_cash"
    )
    to_account = models.ForeignKey(
        "finance.MoneyAccount",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("The other account: where the money went (to bank) or came from (deposit)."),
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    declined_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.CharField(max_length=200, blank=True)
    transaction = models.ForeignKey(
        "finance.Transaction", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    transfer = models.ForeignKey(
        "finance.Transfer", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    category = models.ForeignKey(
        "finance.Category", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reason = models.CharField(max_length=200, blank=True)
    photo = models.FileField(
        storage=private_storage, upload_to=private_upload_to("sales/movements"), blank=True
    )
    created_by = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="sales_movement_positive"),
            models.CheckConstraint(
                condition=~Q(kind="handover") | Q(receiver__isnull=False),
                name="sales_handover_receiver",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "kind", "confirmed_at"], name="sales_movement_kind"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount}"

    @property
    def status(self) -> str:
        """void, declined, pending (a handover nobody confirmed yet) or done."""
        if self.voided_at is not None:
            return "void"
        if self.declined_at is not None:
            return "declined"
        if self.kind == self.Kind.HANDOVER and self.confirmed_at is None:
            return "pending"
        return "done"

    @property
    def sign(self) -> int:
        """+1 for cash coming into the till, -1 for cash leaving it."""
        return 1 if self.kind in self.INCOMING else -1


class DailySales(TenantModel):
    """Per branch and business day, rebuilt from shifts and receipts (never edited by hand)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="daily_sales")
    day = models.DateField()
    sales = MoneyField(default=0)
    refunds = MoneyField(default=0)
    net = MoneyField(default=0)
    receipts = models.PositiveIntegerField(default=0)
    avg_check = MoneyField(default=0)
    by_method = models.JSONField(default=dict, blank=True)
    shifts = models.PositiveSmallIntegerField(default=0)
    cash_difference = MoneyField(default=0)
    computed_at = models.DateTimeField()

    class Meta:
        ordering = ["-day", "branch_id"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "day"], name="sales_unique_daily"),
        ]
        indexes = [models.Index(fields=["company", "day"], name="sales_daily_day")]

    def __str__(self):
        return f"{self.branch} {self.day}"


class SalesTarget(TenantModel):
    """A monthly sales goal for the company, a branch or one person."""

    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, null=True, blank=True, related_name="sales_targets"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, null=True, blank=True, related_name="sales_targets"
    )
    month = models.DateField(help_text=_("The first day of the month."))
    amount = MoneyField()

    class Meta:
        ordering = ["-month", "branch_id", "membership_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "month", "branch", "membership"],
                nulls_distinct=False,
                name="sales_unique_target",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="sales_target_positive"),
        ]

    def __str__(self):
        return f"{self.month:%Y-%m} {self.amount}"
