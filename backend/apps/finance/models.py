"""The finance ledger: accounts, categories, counterparties, transactions, transfers, debts, rates.

docs/PLAN-OWNER.md §3.7. Rows are written only through `apps.finance.services`, which keeps the
cached balances and debt totals in step with the rows. Ledger rows are voided, never deleted,
and every link to them is `PROTECT`.

Money is `Decimal(18, 2)` next to its currency. A rate is UZS per 1 USD (1 for a row in the
company's base currency) and is frozen on the row when it's posted, together with
`base_amount`, the amount in the base currency. Reports add up `base_amount`; account balances
add up `amount`.
"""

from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Branch, Company, TenantModel
from apps.core.money import Currency, CurrencyField, MoneyField, RateField
from apps.core.storage import private_storage, private_upload_to
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

    class TaxRegime(models.TextChoices):
        TURNOVER = "turnover", _("Turnover tax")
        VAT = "vat", _("VAT 12 %")
        VAT_SIMPLIFIED = "vat_simplified", _("Simplified VAT 6 %")

    # The VAT rate each regime implies (the company may set another one).
    REGIME_VAT = {
        TaxRegime.TURNOVER: Decimal("0.00"),
        TaxRegime.VAT: Decimal("12.00"),
        TaxRegime.VAT_SIMPLIFIED: Decimal("6.00"),
    }

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
    # The tax regime (docs/PLAN-OWNER.md §14.8, §14.21). Every number below is the company's
    # own setting; the defaults are what the research note read on 21.10.2026 (confirm).
    tax_regime = models.CharField(
        max_length=16,
        choices=TaxRegime.choices,
        default=TaxRegime.TURNOVER,
        help_text=_("Which tax the company pays on its sales."),
    )
    vat_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal(0),
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))],
        help_text=_("The VAT rate on sales: 12 for VAT, 6 for simplified VAT, 0 otherwise."),
    )
    turnover_threshold = models.PositiveIntegerField(
        default=12000,
        help_text=_(
            "Turnover above which the turnover tax no longer applies, in base calculation "
            "values. Confirm with your accountant."
        ),
    )
    base_value = MoneyField(
        default=Decimal(412000),
        help_text=_("One base calculation value in so'm. Confirm with your accountant."),
    )
    tax_regime_set_at = models.DateTimeField(
        null=True, blank=True, help_text=_("When someone confirmed the tax regime.")
    )
    # Which set of default rows `defaults.ensure` has added (1: the pharmacy categories), so a
    # category the owner deleted never comes back on the next deploy.
    defaults_version = models.PositiveSmallIntegerField(default=0, editable=False)

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
    # RESTRICT, not PROTECT: a parent with children can't be deleted alone, but a company's
    # whole tree can go in one delete (seed_demo --reset).
    parent = models.ForeignKey(
        "self", on_delete=models.RESTRICT, null=True, blank=True, related_name="children"
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

# Rows that take part of a debt off it (`debt_amount` counts in `Debt.paid`): payments,
# write-offs, and credit notes (`services.credit_debt`: a contra income or expense on the debt
# with no account, which the accrual that opened a debt never is).
SETTLES_DEBT = Q(kind__in=("debt_payment", "write_off")) | Q(
    kind__in=("income", "expense"), is_contra=True, account__isnull=True, debt__isnull=False
)


def credits_debt(row) -> bool:
    """Whether `row` is a credit note on a debt (see SETTLES_DEBT)."""
    return (
        row.kind in ("income", "expense")
        and row.is_contra
        and row.account_id is None
        and row.debt_id is not None
    )


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
                condition=Q(exchange_rate__isnull=True) | Q(exchange_rate__gt=0),
                name="finance_transfer_rate_positive",
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
        # A cost that moves no money (depreciation, an asset written off): no account, in the
        # P&L only. Booked by `book_non_cash`, never by hand.
        NON_CASH = "non_cash", _("Non-cash cost")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        POSTED = "posted", _("Posted")
        REJECTED = "rejected", _("Rejected")
        VOID = "void", _("Void")

    # Kinds in the profit and loss statement.
    PNL_KINDS = (Kind.INCOME, Kind.EXPENSE, Kind.WRITE_OFF, Kind.FX, Kind.NON_CASH)

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
    # RESTRICT for the same reason as Category.parent.
    reverses = models.OneToOneField(
        "self", on_delete=models.RESTRICT, null=True, blank=True, related_name="reversed_by"
    )
    is_contra = models.BooleanField(
        default=False, help_text=_("Reduces its own kind: a refund reduces income.")
    )
    capitalized = models.BooleanField(
        default=False,
        help_text=_(
            "Bought as a fixed asset: the money left, but the cost reaches the P&L month by "
            "month as depreciation, not at once."
        ),
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
            # What a row settles or opens of a debt is a positive amount of that debt: voiding
            # takes it back off `Debt.paid`.
            models.CheckConstraint(
                condition=Q(debt_amount__isnull=True)
                | (Q(debt_amount__gt=0) & Q(debt__isnull=False)),
                name="finance_settled_amount_positive",
            ),
            # The base amount points the same way as the amount (it may round to zero).
            models.CheckConstraint(
                condition=Q(amount__gte=0, base_amount__gte=0)
                | Q(amount__lte=0, base_amount__lte=0),
                name="finance_base_amount_same_sign",
            ),
        ]

    def __str__(self):
        return f"{self.occurred_on} {self.get_kind_display()}: {self.amount} {self.currency}"


class Receipt(TenantModel):
    """A receipt photo or PDF behind a ledger entry, kept in private storage (§2.8).

    Uploaded files go through `apps.core.uploads.accept_document`: pictures are re-encoded as
    JPEG (with a small WebP thumbnail), PDFs are checked by their bytes, and the server picks the
    name. A receipt may be uploaded before its entry exists (quick add, AI reading) and is linked
    when the entry is recorded; `transaction` is empty until then.
    """

    class Extraction(models.TextChoices):
        NONE = "none", _("Not read")
        PENDING = "pending", _("Being read")
        DONE = "done", _("Read")
        FAILED = "failed", _("Couldn't be read")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="finance_receipts")
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="receipts",
    )
    # An expense claim's receipts belong to the claim from the start; once the claim is booked
    # they also point at its ledger row, so the entry shows them.
    claim = models.ForeignKey(
        "Claim",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="receipts",
    )
    file = models.FileField(storage=private_storage, upload_to=private_upload_to("receipts"))
    thumb = models.FileField(
        storage=private_storage,
        upload_to=private_upload_to("receipts/thumbs"),
        blank=True,
        help_text=_("A 400 px preview of a picture; empty for a PDF."),
    )
    content_type = models.CharField(max_length=64)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    extraction_status = models.CharField(
        max_length=10, choices=Extraction.choices, default=Extraction.NONE
    )
    extracted = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["pk"]
        indexes = [models.Index(fields=["company", "transaction"])]

    def __str__(self):
        return f"Receipt #{self.pk}"

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")


class DebtInstallment(models.Model):
    """One planned payment of a debt (an instalment plan). The schedule is a plan: payments
    settle the debt as a whole, and each instalment counts as paid once the payments so far
    cover it and the ones before it."""

    debt = models.ForeignKey(Debt, on_delete=models.CASCADE, related_name="installments")
    due_on = models.DateField()
    amount = MoneyField(help_text=_("In the debt's currency."))
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["due_on", "position", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="finance_installment_amount_positive"
            ),
        ]

    def __str__(self):
        return f"{self.due_on}: {self.amount}"


class RecurringRule(TenantModel):
    """A payment that comes back: rent, utilities, internet, a tax (Package I, §3.7).

    A `bill` is a reminder: each occurrence stays open (in Upcoming, and reminded to the payer)
    until someone pays it, with the real amount, or skips it. An `auto` rule posts itself on
    its due day on `account`. Occurrences follow `frequency` times `interval` from `starts_on` on
    `day` (a weekday for weekly rules, else a day of the month, the last day when the month is
    shorter); one that falls on a company holiday moves to the working day before or after
    (`on_holiday`).

    `next_due_on` is the scheduled day of the open occurrence, before any holiday move: it is the
    occurrence's identity, so what it books is idempotent per due date (the ledger source key)
    even when a holiday added later moves the day it is due.
    """

    class Mode(models.TextChoices):
        BILL = "bill", _("Reminder: pay it yourself")
        AUTO = "auto", _("Posted automatically")

    class Frequency(models.TextChoices):
        WEEKLY = "weekly", _("Weekly")
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")
        YEARLY = "yearly", _("Yearly")

    class OnHoliday(models.TextChoices):
        BEFORE = "before", _("The working day before")
        AFTER = "after", _("The working day after")
        KEEP = "keep", _("Keep the day")

    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="finance_recurring_rules"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=8, choices=Category.Kind.choices, default=Category.Kind.EXPENSE
    )
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.BILL)
    frequency = models.CharField(
        max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY
    )
    interval = models.PositiveSmallIntegerField(default=1, help_text=_("Every how many periods."))
    day = models.PositiveSmallIntegerField(
        default=1,
        help_text=_("Weekly: 1 (Monday) to 7 (Sunday). Otherwise the day of the month, 1 to 31."),
    )
    on_holiday = models.CharField(max_length=8, choices=OnHoliday.choices, default=OnHoliday.BEFORE)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="recurring_rules")
    counterparty = models.ForeignKey(
        Counterparty,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_rules",
    )
    account = models.ForeignKey(
        MoneyAccount,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recurring_rules",
        help_text=_("Where an automatic rule posts; the usual account of a bill."),
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="recurring_rules"
    )
    amount = MoneyField(default=0, help_text=_("The usual amount; an estimate when it varies."))
    currency = CurrencyField()
    amount_varies = models.BooleanField(
        default=False, help_text=_("The amount changes every time (utilities, taxes).")
    )
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    next_due_on = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_("The scheduled day of the open occurrence; empty once the rule has ended."),
    )
    remind_days_before = models.PositiveSmallIntegerField(default=3)
    payer = models.ForeignKey(
        Membership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=_("Who is reminded to pay it."),
    )
    create_task = models.BooleanField(default=False)
    template_key = models.CharField(
        max_length=32, blank=True, help_text=_("Set on rules made from a tax calendar template.")
    )
    is_active = models.BooleanField(default=True)
    last_done_on = models.DateField(
        null=True, blank=True, help_text=_("The last occurrence paid, posted or skipped.")
    )
    last_reminded_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["next_due_on", "name", "pk"]
        indexes = [models.Index(fields=["company", "is_active", "next_due_on"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(interval__gte=1), name="finance_recurring_interval_positive"
            ),
            models.CheckConstraint(
                condition=Q(day__gte=1, day__lte=31), name="finance_recurring_day_in_month"
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0) | Q(amount=0, amount_varies=True),
                name="finance_recurring_amount",
            ),
            models.CheckConstraint(
                condition=~Q(mode="auto")
                | Q(account__isnull=False, amount_varies=False, amount__gt=0),
                name="finance_recurring_auto_needs_account",
            ),
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True) | Q(ends_on__gte=F("starts_on")),
                name="finance_recurring_ends_after_start",
            ),
            models.UniqueConstraint(
                fields=["company", "template_key"],
                condition=~Q(template_key="") & Q(is_active=True),
                name="finance_unique_recurring_template",
            ),
        ]

    def __str__(self):
        return self.name


class Budget(TenantModel):
    """What the company means to spend on an expense category in a month (Package I).

    Actuals come from the profit and loss numbers, so a budget counts what the P&L counts.
    `alerted_80_at` and `alerted_100_at` make each alert go out once per month and threshold.
    """

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="finance_budgets")
    month = models.DateField(help_text=_("The first day of the month."))
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="budgets")
    amount = MoneyField(help_text=_("In the base currency."))
    alerted_80_at = models.DateTimeField(null=True, blank=True)
    alerted_100_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-month", "category_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "month", "category"], name="finance_unique_budget"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_budget_positive"),
        ]

    def __str__(self):
        return f"{self.month:%Y-%m} {self.category_id}: {self.amount}"


class Claim(TenantModel):
    """An expense someone paid for the company (Package I, §3.7): from their own money (the
    company owes it back) or from company cash they hold (an expense on their account).

    Booking: own money, on approval, opens a `reimbursement` payable to the person with the
    expense as its accrual (paid back by payroll or in cash, `FinanceSettings.reimburse_via`);
    held cash records the expense on the account the person holds, pending until approved.
    Below `approval_threshold` a claim is booked at once. Nobody approves their own claim.
    """

    class PaidFrom(models.TextChoices):
        OWN_MONEY = "own_money", _("My own money")
        HELD_CASH = "held_cash", _("Company cash I hold")

    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        PAID = "paid", _("Paid back")
        CANCELLED = "cancelled", _("Cancelled")

    class Via(models.TextChoices):
        BOT = "bot", _("Telegram bot")
        MINIAPP = "miniapp", _("Mini app")
        DASHBOARD = "dashboard", _("Dashboard")

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="finance_claims")
    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="finance_claims"
    )
    amount = MoneyField()
    currency = CurrencyField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="claims")
    spent_on = models.DateField()
    description = models.CharField(max_length=300, blank=True)
    paid_from = models.CharField(max_length=10, choices=PaidFrom.choices)
    branch = models.ForeignKey(
        Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="finance_claims"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    transaction = models.ForeignKey(
        Transaction, on_delete=models.PROTECT, null=True, blank=True, related_name="claims"
    )
    debt = models.ForeignKey(
        Debt, on_delete=models.PROTECT, null=True, blank=True, related_name="claims"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=300, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    via = models.CharField(max_length=10, choices=Via.choices, default=Via.MINIAPP)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["membership", "status"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="finance_claim_positive"),
        ]

    def __str__(self):
        return f"Claim #{self.pk}: {self.amount} {self.currency}"
