"""The finance ledger: accounts, categories, counterparties, transactions, transfers, debts, rates.

docs/PLAN-OWNER.md §3.7. Rows are written only through `apps.finance.services`, which keeps the
cached balances and debt totals in step with the rows. Ledger rows are voided, never deleted,
and every link to them is `PROTECT`.

Money is `Decimal(18, 2)` next to its currency. A rate is UZS per 1 USD (1 for a row in the
company's base currency) and is frozen on the row when it's posted, together with
`base_amount`, the amount in the base currency. Reports add up `base_amount`; account balances
add up `amount`.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.money import Currency, CurrencyField, MoneyField, RateField
from apps.members.models import Membership

PHONE_PATTERN = r"^\+998\d{9}$"
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


def color_field() -> models.CharField:
    return models.CharField(
        max_length=7,
        blank=True,
        validators=[RegexValidator(COLOR_PATTERN, _("A colour like #1f8a70."))],
    )


class RateSource(models.TextChoices):
    CBU = "cbu", _("Central Bank of Uzbekistan")
    MANUAL = "manual", _("Entered by hand")


class Voidable(models.Model):
    """Rows that can be wrong are voided, never deleted. A rejection uses the same fields."""

    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    void_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        abstract = True


class FinanceSettings(models.Model):
    """One row per company, made on first read by `apps.finance.conf.get_settings`."""

    class ReimburseVia(models.TextChoices):
        PAYROLL = "payroll", _("With the next payroll")
        CASH = "cash", _("In cash by whoever approves")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="finance_settings"
    )
    locked_until = models.DateField(
        null=True,
        blank=True,
        help_text=_("Nothing dated on or before this day can be added, edited or voided."),
    )
    rate_source = models.CharField(
        max_length=8,
        choices=RateSource.choices,
        default=RateSource.CBU,
        help_text=_("Where exchange rates come from when nobody entered one for the day."),
    )
    approval_threshold = MoneyField(
        null=True,
        blank=True,
        help_text=_("Expense claims at or above this wait for approval. Empty: every claim waits."),
    )
    receipt_required_over = MoneyField(
        null=True, blank=True, help_text=_("Expenses above this need a receipt.")
    )
    large_expense_alert = MoneyField(
        null=True,
        blank=True,
        help_text=_("Owners hear about it when someone else records an expense above this."),
    )
    reimburse_via = models.CharField(
        max_length=8,
        choices=ReimburseVia.choices,
        default=ReimburseVia.PAYROLL,
        help_text=_('How approved "paid from my own money" claims are paid back.'),
    )

    class Meta:
        verbose_name = "finance settings"
        verbose_name_plural = "finance settings"

    def __str__(self):
        return str(self.company)


class ExchangeRate(models.Model):
    """A rate for everyone: fetched from the Central Bank, or entered by a platform admin."""

    currency = CurrencyField(default=Currency.USD)
    date = models.DateField()
    rate = RateField(help_text=_("UZS per 1 unit of the currency."))
    source = models.CharField(max_length=8, choices=RateSource.choices, default=RateSource.CBU)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-date", "currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["currency", "date", "source"], name="finance_unique_exchange_rate"
            ),
            models.CheckConstraint(condition=Q(rate__gt=0), name="finance_exchange_rate_positive"),
            models.CheckConstraint(
                condition=~Q(currency=Currency.UZS), name="finance_exchange_rate_not_uzs"
            ),
        ]

    def __str__(self):
        return f"{self.currency} {self.date}: {self.rate} ({self.source})"


class CompanyRate(TenantModel):
    """The company's own rate for a day. It beats the Central Bank's rate for that day."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="finance_rates")
    currency = CurrencyField(default=Currency.USD)
    date = models.DateField()
    rate = RateField(help_text=_("UZS per 1 unit of the currency."))
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-date", "currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "currency", "date"], name="finance_unique_company_rate"
            ),
            models.CheckConstraint(condition=Q(rate__gt=0), name="finance_company_rate_positive"),
            models.CheckConstraint(
                condition=~Q(currency=Currency.UZS), name="finance_company_rate_not_uzs"
            ),
        ]

    def __str__(self):
        return f"{self.currency} {self.date}: {self.rate}"


class MoneyAccount(TenantModel):
    """Somewhere money is: a cash desk, a bank account, a card, a wallet, a safe, a person."""

    class Kind(models.TextChoices):
        CASH = "cash", _("Cash desk")
        BANK = "bank", _("Bank account")
        CARD = "card", _("Card")
        WALLET = "wallet", _("E-wallet")
        CLEARING = "clearing", _("Terminal clearing")
        SAFE = "safe", _("Safe")
        EMPLOYEE = "employee", _("Held by an employee")
        OWNER = "owner", _("Owner's money")

    HOLDER_KINDS = (Kind.EMPLOYEE, Kind.OWNER)

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="money_accounts")
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    currency = CurrencyField()
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="money_accounts",
        help_text=_(
            "Empty for company-level accounts, which only people who see every branch see."
        ),
    )
    holder = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="held_accounts",
        help_text=_("The person holding the money. Required for employee and owner accounts."),
    )
    operators = models.ManyToManyField(
        Membership,
        blank=True,
        related_name="operated_accounts",
        help_text=_("People who may record on this account with finance.record."),
    )
    bank_name = models.CharField(max_length=100, blank=True)
    number_last4 = models.CharField(
        max_length=4,
        blank=True,
        validators=[RegexValidator(r"^\d{4}$", _("Only the last 4 digits."))],
        help_text=_("Never the full number."),
    )
    balance = MoneyField(
        default=0,
        editable=False,
        help_text=_("Sum of the posted rows, kept up to date by the ledger services."),
    )
    allow_negative = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    color = color_field()

    class Meta:
        ordering = ["order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="finance_unique_account_name"),
            models.CheckConstraint(
                condition=~Q(kind__in=["employee", "owner"]) | Q(holder__isnull=False),
                name="finance_account_holder_required",
            ),
            # One safe per branch and currency.
            models.UniqueConstraint(
                fields=["branch", "kind", "currency"],
                condition=Q(kind="safe"),
                name="finance_unique_branch_safe",
            ),
            models.UniqueConstraint(
                fields=["holder", "kind", "currency"],
                condition=Q(holder__isnull=False),
                name="finance_unique_holder_account",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        for field in ("branch", "holder"):
            related = getattr(self, field)
            if related is not None and related.company_id != self.company_id:
                raise ValidationError({field: _("Must belong to the same company.")})
        if self.kind in self.HOLDER_KINDS and self.holder_id is None:
            raise ValidationError({"holder": _("Pick the person who holds this money.")})


class Category(TenantModel):
    """What money was earned or spent on, in at most two levels."""

    class Kind(models.TextChoices):
        INCOME = "income", _("Income")
        EXPENSE = "expense", _("Expense")

    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="finance_categories"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    system_code = models.CharField(
        max_length=32,
        blank=True,
        help_text=_("Set on the categories the system books into; they can't be deleted."),
    )
    is_sensitive = models.BooleanField(
        default=False, help_text=_("Per-person detail needs payroll.view (salaries).")
    )
    is_capex = models.BooleanField(
        default=False, help_text=_("Equipment and other long-term purchases.")
    )
    color = color_field()
    icon = models.CharField(max_length=40, blank=True, help_text=_("A lucide icon name."))
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["kind", "order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "parent", "name"],
                nulls_distinct=False,
                name="finance_unique_category_name",
            ),
            models.UniqueConstraint(
                fields=["company", "system_code"],
                condition=~Q(system_code=""),
                name="finance_unique_category_code",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        parent = self.parent
        if parent is None:
            return
        if parent.company_id != self.company_id:
            raise ValidationError({"parent": _("Must belong to the same company.")})
        if parent.parent_id is not None:
            raise ValidationError({"parent": _("Categories go two levels deep at most.")})
        if parent.kind != self.kind:
            raise ValidationError({"parent": _("A subcategory has its parent's kind.")})
        if self.pk is not None and (parent.pk == self.pk or self.children.exists()):
            raise ValidationError({"parent": _("Categories go two levels deep at most.")})


class Counterparty(TenantModel):
    """The one party directory: customers, suppliers, the landlord, the tax office."""

    class Kind(models.TextChoices):
        CUSTOMER = "customer", _("Customer")
        SUPPLIER = "supplier", _("Supplier")
        BOTH = "both", _("Customer and supplier")
        STATE = "state", _("State body")
        OTHER = "other", _("Other")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="counterparties")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CUSTOMER)
    phone = models.CharField(
        max_length=16,
        blank=True,
        validators=[RegexValidator(PHONE_PATTERN, _("A number like +998901234567."))],
    )
    tin = models.CharField(max_length=14, blank=True, help_text=_("Taxpayer number (INN)."))
    contact_person = models.CharField(max_length=100, blank=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    address = models.CharField(max_length=255, blank=True)
    bank_details = models.TextField(blank=True, help_text=_("Printed on invoices."))
    notes = models.TextField(blank=True)
    default_category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    credit_limit = MoneyField(null=True, blank=True)
    credit_blocked = models.BooleanField(default=False)
    birthday = models.DateField(null=True, blank=True)
    tags = ArrayField(models.CharField(max_length=32), default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "counterparties"
        ordering = ["name"]
        indexes = [models.Index(fields=["company", "name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "tin"], condition=~Q(tin=""), name="finance_unique_party_tin"
            ),
            models.UniqueConstraint(
                fields=["company", "phone"],
                condition=~Q(phone=""),
                name="finance_unique_party_phone",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        category = self.default_category
        if category is not None and category.company_id != self.company_id:
            raise ValidationError({"default_category": _("Must belong to the same company.")})


# Statuses whose rows still count (or will, once approved). A void or rejected row frees its
# source, so a module can void a booking and book it again under the same source.
LIVE_STATUSES = ("pending", "posted")


class Debt(TenantModel):
    """Money owed to the company (receivable) or by it (payable), settled by payments."""

    class Direction(models.TextChoices):
        RECEIVABLE = "receivable", _("Owed to us")
        PAYABLE = "payable", _("We owe")

    class Kind(models.TextChoices):
        TRADE = "trade", _("Goods or services on credit")
        BILL = "bill", _("Bill")
        LOAN = "loan", _("Loan")
        ADVANCE = "advance", _("Salary advance")
        SALARY = "salary", _("Salary")
        REIMBURSEMENT = "reimbursement", _("Reimbursement")
        TAX = "tax", _("Tax")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        PAID = "paid", _("Paid")
        WRITTEN_OFF = "written_off", _("Written off")
        CANCELLED = "cancelled", _("Cancelled")

    # Debts whose per-person detail needs payroll.view.
    SENSITIVE_KINDS = (Kind.SALARY, Kind.ADVANCE, Kind.REIMBURSEMENT)

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="debts")
    direction = models.CharField(max_length=10, choices=Direction.choices)
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.OTHER)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    counterparty = models.ForeignKey(
        Counterparty, on_delete=models.PROTECT, null=True, blank=True, related_name="debts"
    )
    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, null=True, blank=True, related_name="debts"
    )
    currency = CurrencyField()
    amount = MoneyField(help_text=_("What was owed, in the debt's currency."))
    paid = MoneyField(
        default=0,
        editable=False,
        help_text=_("Settled so far by payments and write-offs, in the debt's currency."),
    )
    rate = RateField(
        default=1,
        help_text=_(
            "UZS per 1 USD when the debt was opened (1 in the base currency). Values what is "
            "settled, so a payment at another rate books the exchange difference."
        ),
    )
    issued_on = models.DateField()
    due_on = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="debts"
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="debts",
    )
    responsible = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_debts",
        help_text=_("Who chases it."),
    )
    is_opening = models.BooleanField(
        default=False, help_text=_("Owed from before the company kept its books here.")
    )
    last_reminded_on = models.DateField(null=True, blank=True)
    source_type = models.CharField(max_length=32, blank=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_key = models.CharField(max_length=32, blank=True)
    locked_by_type = models.CharField(
        max_length=32,
        blank=True,
        help_text=_("Reserved by this source (e.g. a finalized payslip); only it may pay."),
    )
    locked_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-issued_on", "-id"]
        indexes = [
            models.Index(fields=["company", "direction", "status", "due_on"]),
            models.Index(fields=["company", "membership", "kind", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_debt_amount_positive"),
            models.CheckConstraint(
                condition=Q(paid__gte=0) & Q(paid__lte=F("amount")),
                name="finance_debt_paid_within_amount",
            ),
            models.CheckConstraint(condition=Q(rate__gt=0), name="finance_debt_rate_positive"),
            models.CheckConstraint(
                condition=Q(counterparty__isnull=False, membership__isnull=True)
                | Q(counterparty__isnull=True, membership__isnull=False),
                name="finance_debt_one_party",
            ),
            models.CheckConstraint(
                condition=Q(due_on__isnull=True) | Q(due_on__gte=F("issued_on")),
                name="finance_debt_due_after_issue",
            ),
            models.CheckConstraint(
                condition=Q(source_type="", source_id__isnull=True, source_key="")
                | (~Q(source_type="") & Q(source_id__isnull=False)),
                name="finance_debt_source_complete",
            ),
            models.CheckConstraint(
                condition=Q(locked_by_type="", locked_by_id__isnull=True)
                | (~Q(locked_by_type="") & Q(locked_by_id__isnull=False)),
                name="finance_debt_lock_complete",
            ),
            models.UniqueConstraint(
                fields=["company", "source_type", "source_id", "source_key"],
                condition=~Q(source_type="") & ~Q(status="cancelled"),
                name="finance_unique_debt_source",
            ),
        ]

    def __str__(self):
        return f"{self.get_direction_display()}: {self.amount} {self.currency}"

    @property
    def outstanding(self):
        """What is still owed, in the debt's currency (`queries.open_debts` also annotates it)."""
        return self.amount - self.paid

    @outstanding.setter
    def outstanding(self, value):
        pass  # the annotation of open_debts; the value is always amount - paid

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_by_type)


class Transfer(Voidable, TenantModel):
    """Money moved between two of the company's accounts, possibly changing currency."""

    class Status(models.TextChoices):
        POSTED = "posted", _("Posted")
        VOID = "void", _("Void")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="finance_transfers")
    occurred_on = models.DateField()
    from_account = models.ForeignKey(
        MoneyAccount, on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_account = models.ForeignKey(
        MoneyAccount, on_delete=models.PROTECT, related_name="transfers_in"
    )
    amount_out = MoneyField(help_text=_("Left the first account, in its currency."))
    amount_in = MoneyField(help_text=_("Reached the second account, in its currency."))
    exchange_rate = RateField(
        null=True, blank=True, help_text=_("UZS per 1 USD, when the currencies differ.")
    )
    fee = MoneyField(
        default=0, help_text=_("Charged on the first account, booked as a bank fee expense.")
    )
    description = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.POSTED)
    source_type = models.CharField(max_length=32, blank=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_key = models.CharField(max_length=32, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-occurred_on", "-id"]
        indexes = [models.Index(fields=["company", "occurred_on"])]
        constraints = [
            models.CheckConstraint(
                condition=~Q(from_account=F("to_account")), name="finance_transfer_two_accounts"
            ),
            models.CheckConstraint(
                condition=Q(amount_out__gt=0) & Q(amount_in__gt=0) & Q(fee__gte=0),
                name="finance_transfer_amounts_positive",
            ),
            models.CheckConstraint(
                condition=Q(source_type="", source_id__isnull=True, source_key="")
                | (~Q(source_type="") & Q(source_id__isnull=False)),
                name="finance_transfer_source_complete",
            ),
            models.UniqueConstraint(
                fields=["company", "source_type", "source_id", "source_key"],
                condition=~Q(source_type="") & Q(status="posted"),
                name="finance_unique_transfer_source",
            ),
        ]

    def __str__(self):
        return f"{self.from_account_id} → {self.to_account_id}: {self.amount_out}"


class Transaction(Voidable, TenantModel):
    """One row of the ledger. `amount` is signed in `currency`: + money in, - money out."""

    class Kind(models.TextChoices):
        INCOME = "income", _("Income")
        EXPENSE = "expense", _("Expense")
        TRANSFER = "transfer", _("Transfer")
        DEBT_OPEN = "debt_open", _("Debt opened")
        DEBT_PAYMENT = "debt_payment", _("Debt payment")
        WRITE_OFF = "write_off", _("Write-off")
        FX = "fx", _("Exchange difference")
        OWNER = "owner", _("Owner contribution or draw")
        OPENING = "opening", _("Opening balance")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        POSTED = "posted", _("Posted")
        REJECTED = "rejected", _("Rejected")
        VOID = "void", _("Void")

    # Kinds in the profit and loss statement.
    PNL_KINDS = (Kind.INCOME, Kind.EXPENSE, Kind.WRITE_OFF, Kind.FX)

    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="finance_transactions"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.POSTED)
    occurred_on = models.DateField(help_text=_("Company-local day; every report groups by it."))
    account = models.ForeignKey(
        MoneyAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    amount = MoneyField(help_text=_("Signed, in the row's currency: + in, - out."))
    currency = CurrencyField()
    rate = RateField(default=1, help_text=_("UZS per 1 USD used (1 in the base currency)."))
    rate_stale = models.BooleanField(
        default=False, help_text=_("No rate for the day; an older or later one was used.")
    )
    base_amount = MoneyField(
        help_text=_("Signed, in the base currency, frozen at posting. Reports add this up.")
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    counterparty = models.ForeignKey(
        Counterparty,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_transactions",
        help_text=_("The employee it concerns."),
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_transactions",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_transactions",
    )
    debt = models.ForeignKey(
        Debt, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    debt_amount = MoneyField(
        null=True,
        blank=True,
        help_text=_("How much of the debt it settles or opens, in its currency."),
    )
    transfer = models.ForeignKey(
        Transfer, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversed_by"
    )
    is_contra = models.BooleanField(
        default=False, help_text=_("Reduces its own kind: a refund reduces income.")
    )
    description = models.CharField(max_length=300, blank=True)
    source_type = models.CharField(max_length=32, blank=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_key = models.CharField(max_length=32, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    ai_suggestion = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_on", "-id"]
        indexes = [
            models.Index(fields=["company", "occurred_on"]),
            models.Index(fields=["company", "account", "occurred_on"]),
            models.Index(fields=["company", "category", "occurred_on"]),
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "counterparty"]),
            models.Index(fields=["company", "branch", "occurred_on"]),
            models.Index(fields=["debt"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "source_type", "source_id", "source_key"],
                condition=~Q(source_type="") & Q(status__in=LIVE_STATUSES),
                name="finance_unique_transaction_source",
            ),
            models.CheckConstraint(
                condition=Q(source_type="", source_id__isnull=True, source_key="")
                | (~Q(source_type="") & Q(source_id__isnull=False)),
                name="finance_transaction_source_complete",
            ),
            models.CheckConstraint(
                condition=Q(rate__gt=0), name="finance_transaction_rate_positive"
            ),
            models.CheckConstraint(
                condition=Q(kind="fx") | ~Q(amount=0), name="finance_transaction_amount_nonzero"
            ),
            models.CheckConstraint(
                condition=~Q(kind="income")
                | Q(amount__gt=0)
                | Q(reverses__isnull=False)
                | Q(is_contra=True),
                name="finance_income_positive",
            ),
            models.CheckConstraint(
                condition=~Q(kind="expense")
                | Q(amount__lt=0)
                | Q(reverses__isnull=False)
                | Q(is_contra=True),
                name="finance_expense_negative",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=["transfer", "opening", "owner", "debt_open"])
                | Q(account__isnull=False),
                name="finance_transaction_needs_account",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=["debt_open", "debt_payment", "write_off"])
                | Q(debt__isnull=False),
                name="finance_transaction_needs_debt",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=["income", "expense"])
                | Q(account__isnull=False)
                | Q(debt__isnull=False),
                name="finance_transaction_account_or_debt",
            ),
            models.CheckConstraint(
                condition=~Q(kind__in=["income", "expense", "write_off", "fx"])
                | Q(category__isnull=False),
                name="finance_transaction_needs_category",
            ),
            models.CheckConstraint(
                condition=~Q(kind="fx") | Q(account__isnull=True),
                name="finance_fx_has_no_account",
            ),
            models.CheckConstraint(
                condition=~Q(kind="transfer") | Q(transfer__isnull=False),
                name="finance_transfer_row_has_transfer",
            ),
        ]

    def __str__(self):
        return f"{self.occurred_on} {self.get_kind_display()}: {self.amount} {self.currency}"
