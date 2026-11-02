"""Payroll: pay setups, bonuses and fines, advances, monthly runs and payslips.

docs/PLAN-OWNER.md §3.13, §3.17 and §14.11. Rows are written only through
`apps.payroll.services`. Money is `Decimal(18, 2)` next to its currency and never a float. A run
belongs to one month (`period` is its first day); its payslips are recalculated freely while the
run is a draft. Finalizing locks what it used (pay setups, adjustments, advance repayments) and
books the accruals in the finance ledger; reopening voids those rows and unlocks them again.
"""

from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.companies.models import Company, TenantModel
from apps.core.money import CurrencyField, MoneyField, RateField
from apps.core.storage import private_storage, private_upload_to
from apps.hr.models import EmployeeProfile
from apps.members.models import Membership, Position

PERCENT = (MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100)))
DAY_OF_MONTH = (MinValueValidator(1), MaxValueValidator(28))
MULTIPLIER = (MinValueValidator(Decimal(1)), MaxValueValidator(Decimal(10)))


def _user_link(**kwargs) -> models.ForeignKey:
    """An actor field: who did it (kept when the user goes, rule 16)."""
    return models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        **kwargs,
    )


class PayType(models.TextChoices):
    MONTHLY = "monthly", pgettext_lazy("pay type", "Monthly")
    DAILY = "daily", pgettext_lazy("pay type", "Daily")
    HOURLY = "hourly", pgettext_lazy("pay type", "Hourly")
    PER_TASK = "per_task", pgettext_lazy("pay type", "Per task")


# How a person is paid: one list for the whole product, the HR profile's
# (cash, card, bank transfer).
PayoutMethod = EmployeeProfile.PayoutMethod


class PayrollSettings(models.Model):
    """One row per company, made on first read by `apps.payroll.conf.get_settings`."""

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="payroll_settings"
    )
    currency = CurrencyField(help_text=_("The currency payslips are paid in."))
    pay_day = models.PositiveSmallIntegerField(
        default=5, validators=DAY_OF_MONTH, help_text=_("Day of the month salaries are paid.")
    )
    advance_day = models.PositiveSmallIntegerField(
        default=20,
        null=True,
        blank=True,
        validators=DAY_OF_MONTH,
        help_text=_("Day of the month advances are usually paid. Empty: no fixed day."),
    )
    advance_cap_percent = models.PositiveSmallIntegerField(
        default=50,
        validators=(MaxValueValidator(100),),
        help_text=_("Advances may add up to this share of a month's pay."),
    )
    amounts_are_net = models.BooleanField(
        default=True,
        help_text=_("Pay amounts are what people receive; taxes come on top."),
    )
    taxes_enabled = models.BooleanField(
        default=False,
        help_text=_("Estimate income tax, pension and social tax. Check with your accountant."),
    )
    income_tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("12"), validators=PERCENT
    )
    social_tax_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("12"), validators=PERCENT
    )
    inps_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.1"), validators=PERCENT
    )
    deductions_cap_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20"),
        validators=PERCENT,
        help_text=_("Fines and deductions together never take more than this share of the pay."),
    )
    rounding_step = MoneyField(
        default=Decimal("1000"),
        validators=(MinValueValidator(Decimal(0)),),
        help_text=_("Net pay is rounded to a multiple of this. 0: no rounding."),
    )
    overtime_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("2"), validators=MULTIPLIER
    )
    holiday_work_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("2"), validators=MULTIPLIER
    )
    night_multiplier = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("1.50"),
        validators=MULTIPLIER,
        help_text=_(
            "Night hours are paid at this rate (the Labour Code asks for at least 1.5). "
            "The shorter night shift the law also asks for is not counted."
        ),
    )
    night_starts_at = models.TimeField(default=time(22, 0))
    night_ends_at = models.TimeField(default=time(6, 0))
    daily_hours = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("8"),
        validators=(MinValueValidator(Decimal(1)), MaxValueValidator(Decimal(24))),
        help_text=_(
            "Hours in a normal working day: turns monthly and daily pay into an hourly rate."
        ),
    )
    auto_prepare = models.BooleanField(
        default=True, help_text=_("Prepare last month's draft run on the 1st of each month.")
    )
    leave_payout_months = models.PositiveSmallIntegerField(
        default=12, validators=(MinValueValidator(1), MaxValueValidator(24))
    )
    # Pay day reminders: the last month a reminder went out for (once a month).
    reminded_period = models.DateField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "payroll settings"
        verbose_name_plural = "payroll settings"

    def __str__(self):
        return f"Payroll settings of {self.company}"


class Compensation(TenantModel):
    """What a person is paid, from `effective_from` on. A change is a new row; a row a finalized
    run used is `locked` and never changes again."""

    class Proration(models.TextChoices):
        ATTENDANCE = "attendance", _("By attendance")
        CALENDAR = "calendar", _("By calendar days")
        NONE = "none", _("Full amount")

    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="compensations"
    )
    effective_from = models.DateField()
    pay_type = models.CharField(max_length=10, choices=PayType.choices, default=PayType.MONTHLY)
    amount = MoneyField(help_text=_("A month's, a day's or an hour's pay, or the pay per task."))
    currency = CurrencyField()
    proration = models.CharField(
        max_length=10, choices=Proration.choices, default=Proration.ATTENDANCE
    )
    pays_task_rates = models.BooleanField(
        default=False, help_text=_("Also earns the task rates for finished tasks.")
    )
    overtime_eligible = models.BooleanField(default=True)
    note = models.CharField(max_length=300, blank=True)
    created_by = _user_link()
    locked = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ("membership_id", "-effective_from")
        constraints = (
            models.UniqueConstraint(
                fields=("membership", "effective_from"), name="payroll_compensation_one_a_day"
            ),
            models.CheckConstraint(
                condition=Q(amount__gte=0), name="payroll_compensation_amount_not_negative"
            ),
        )
        indexes = (models.Index(fields=("company", "effective_from")),)

    def __str__(self):
        return f"Pay setup #{self.pk}"


class TaskRate(TenantModel):
    """A piece rate: what one finished task earns people whose pay setup pays task rates. The
    most specific active rate wins: routine and position, then routine, then position, then
    the company-wide rate."""

    template = models.ForeignKey(
        "tasks.TaskTemplate",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="payroll_rates",
    )
    position = models.ForeignKey(
        Position, on_delete=models.CASCADE, null=True, blank=True, related_name="payroll_rates"
    )
    amount = MoneyField()
    currency = CurrencyField()
    on_time_only = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("pk",)
        constraints = (
            models.CheckConstraint(condition=Q(amount__gt=0), name="payroll_task_rate_positive"),
        )

    def __str__(self):
        return f"Task rate #{self.pk}"


class AdjustmentRule(TenantModel):
    """An automatic bonus or fine: a metric of a person's month (or day) against a threshold,
    proposing `Adjustment` rows with a `rule_key`, so evaluating it again never doubles."""

    class Kind(models.TextChoices):
        BONUS = "bonus", pgettext_lazy("payroll", "Bonus")
        FINE = "fine", pgettext_lazy("payroll", "Fine")

    class Metric(models.TextChoices):
        TASKS_ON_TIME_PERCENT = "tasks.on_time_percent", _("Tasks on time, %")
        TASKS_DONE = "tasks.done", _("Tasks done")
        TASKS_LATE = "tasks.late", _("Tasks done late")
        TASKS_MISSED = "tasks.missed", _("Tasks missed")
        TASKS_REMINDERS_PER_TASK = "tasks.reminders_per_task", _("Reminders per task")
        TASKS_AVG_DELAY = "tasks.avg_delay_minutes", _("Average delay, minutes")
        LATE_ARRIVALS = "attendance.late_arrivals", _("Late arrivals")
        LATE_MINUTES = "attendance.late_minutes", _("Minutes late")
        ABSENCES = "attendance.absences", _("Absences")
        EARLY_LEAVES = "attendance.early_leaves", _("Early leaves")
        HOURS = "attendance.hours", _("Hours worked")
        SALES_NET = "sales.net", _("Net sales")

    class Mode(models.TextChoices):
        ONCE = "once", _("Once")
        PER_UNIT = "per_unit", _("Per unit")
        TIERED = "tiered", _("Tiered")

    class Op(models.TextChoices):
        GTE = "gte", _("at least")
        GT = "gt", _("more than")
        LTE = "lte", _("at most")
        LT = "lt", _("less than")

    class AmountType(models.TextChoices):
        FIXED = "fixed", _("Fixed amount")
        PERCENT = "percent", _("Percent")

    class Evaluate(models.TextChoices):
        DAILY = "daily", _("Every day")
        MONTHLY = "monthly", _("Once a month")

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    metric = models.CharField(max_length=32, choices=Metric.choices)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.ONCE)
    op = models.CharField(max_length=3, choices=Op.choices, default=Op.GTE)
    threshold = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    free_units = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal(0),
        help_text=_("Per unit: this many units a month are free."),
    )
    tiers = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Tiered: thresholds, each with its own amount."),
    )
    amount_type = models.CharField(
        max_length=8, choices=AmountType.choices, default=AmountType.FIXED
    )
    amount = MoneyField(
        null=True,
        blank=True,
        help_text=_("The amount, or with a percent rule the percent (1.00 = 1%)."),
    )
    cap = MoneyField(null=True, blank=True, help_text=_("At most this much per person a month."))
    min_tasks = models.PositiveSmallIntegerField(
        default=10, help_text=_("Task metrics count only for people with at least this many tasks.")
    )
    positions = models.ManyToManyField(Position, blank=True, related_name="payroll_rules")
    evaluate = models.CharField(max_length=8, choices=Evaluate.choices, default=Evaluate.MONTHLY)
    auto_approve = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    example_key = models.CharField(
        max_length=32, blank=True, editable=False, help_text="Shipped example this row came from."
    )
    created_by = _user_link()

    class Meta:
        ordering = ("pk",)
        constraints = (
            models.UniqueConstraint(
                fields=("company", "example_key"),
                condition=~Q(example_key=""),
                name="payroll_rule_one_example",
            ),
        )

    def __str__(self):
        return self.name


class Adjustment(TenantModel):
    """A bonus, fine, allowance or deduction of one person for one month. Proposed, then
    approved (it lands on that month's payslip) or rejected; `payslip` is set when the run is
    finalized, and from then on the row is locked."""

    class Kind(models.TextChoices):
        BONUS = "bonus", pgettext_lazy("payroll", "Bonus")
        FINE = "fine", pgettext_lazy("payroll", "Fine")
        ALLOWANCE = "allowance", pgettext_lazy("payroll", "Allowance")
        DEDUCTION = "deduction", pgettext_lazy("payroll", "Deduction")

    class Source(models.TextChoices):
        MANUAL = "manual", pgettext_lazy("payroll source", "Added by hand")
        RULE = "rule", pgettext_lazy("payroll source", "Automatic rule")
        TASK = "task", pgettext_lazy("payroll source", "Task")
        ATTENDANCE = "attendance", pgettext_lazy("payroll source", "Attendance")
        DISCIPLINE = "discipline", pgettext_lazy("payroll source", "Disciplinary record")

    class Status(models.TextChoices):
        PROPOSED = "proposed", pgettext_lazy("payroll status", "Proposed")
        APPROVED = "approved", pgettext_lazy("payroll status", "Approved")
        REJECTED = "rejected", pgettext_lazy("payroll status", "Rejected")
        VOID = "void", pgettext_lazy("payroll status", "Void")

    POSITIVE = (Kind.BONUS, Kind.ALLOWANCE)
    NEGATIVE = (Kind.FINE, Kind.DEDUCTION)

    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="payroll_adjustments"
    )
    period = models.DateField(help_text=_("The first day of the month it belongs to."))
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = MoneyField()
    currency = CurrencyField()
    reason = models.CharField(max_length=300)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    rule = models.ForeignKey(
        AdjustmentRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
    )
    rule_key = models.CharField(max_length=64, blank=True)
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    attendance = models.ForeignKey(
        "attendance.AttendanceRecord",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    proposed_by = _user_link()
    decided_by = _user_link()
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    disputed_at = models.DateTimeField(null=True, blank=True)
    dispute_text = models.CharField(max_length=500, blank=True)
    dispute_answer = models.CharField(max_length=500, blank=True)
    dispute_answered_at = models.DateTimeField(null=True, blank=True)
    dispute_answered_by = _user_link()
    payslip = models.ForeignKey(
        "payroll.Payslip",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
    )

    class Meta:
        ordering = ("-period", "-pk")
        constraints = (
            models.UniqueConstraint(
                fields=("company", "rule_key"),
                condition=~Q(rule_key=""),
                name="payroll_adjustment_one_per_rule_key",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="payroll_adjustment_amount_positive"
            ),
        )
        indexes = (models.Index(fields=("company", "membership", "period", "status")),)

    def __str__(self):
        return f"Adjustment #{self.pk}"

    @property
    def is_locked(self) -> bool:
        return self.payslip_id is not None

    @property
    def dispute_open(self) -> bool:
        return self.disputed_at is not None and self.dispute_answered_at is None

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.kind in self.POSITIVE else -self.amount


class Advance(TenantModel):
    """Money paid ahead of payday, repaid from the next payslips in `installments` parts
    starting with `first_period`. Paying it opens a receivable in finance (kind advance)."""

    class Status(models.TextChoices):
        REQUESTED = "requested", pgettext_lazy("payroll status", "Requested")
        APPROVED = "approved", pgettext_lazy("payroll status", "Approved")
        REJECTED = "rejected", pgettext_lazy("payroll status", "Rejected")
        PAID = "paid", pgettext_lazy("payroll status", "Paid")
        REPAID = "repaid", pgettext_lazy("payroll status", "Repaid")
        CANCELLED = "cancelled", pgettext_lazy("payroll status", "Cancelled")

    OPEN_STATUSES = (Status.REQUESTED, Status.APPROVED, Status.PAID)

    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="payroll_advances"
    )
    amount = MoneyField()
    currency = CurrencyField()
    installments = models.PositiveSmallIntegerField(
        default=1, validators=(MinValueValidator(1), MaxValueValidator(12))
    )
    first_period = models.DateField(help_text=_("The first month it is deducted from."))
    reason = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    requested_by = _user_link()
    decided_by = _user_link()
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = _user_link()
    payout_method = models.CharField(max_length=8, choices=PayoutMethod.choices, blank=True)
    debt = models.ForeignKey(
        "finance.Debt", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ("-pk",)
        constraints = (
            models.CheckConstraint(condition=Q(amount__gt=0), name="payroll_advance_positive"),
        )
        indexes = (models.Index(fields=("company", "membership", "status")),)

    def __str__(self):
        return f"Advance #{self.pk}"


class AdvanceRepayment(models.Model):
    """A part of an advance paid back: deducted on a payslip (`payslip_line`) or handed back
    to an account (`transaction`)."""

    advance = models.ForeignKey(Advance, on_delete=models.CASCADE, related_name="repayments")
    amount = MoneyField()
    paid_on = models.DateField()
    payslip_line = models.OneToOneField(
        "payroll.PayslipLine",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="repayment",
    )
    transaction = models.ForeignKey(
        "finance.Transaction", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    note = models.CharField(max_length=300, blank=True)
    created_by = _user_link()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("paid_on", "pk")
        constraints = (
            models.CheckConstraint(condition=Q(amount__gt=0), name="payroll_repayment_positive"),
        )

    def __str__(self):
        return f"Repayment #{self.pk}"


class PayrollRun(TenantModel):
    """One month's payroll (`kind=regular`), or one leaver's final settlement (`kind=final`)."""

    class Kind(models.TextChoices):
        REGULAR = "regular", pgettext_lazy("payroll", "Monthly")
        FINAL = "final", pgettext_lazy("payroll", "Final settlement")

    class Status(models.TextChoices):
        DRAFT = "draft", pgettext_lazy("payroll status", "Draft")
        FINALIZED = "finalized", pgettext_lazy("payroll status", "Finalized")
        PAID = "paid", pgettext_lazy("payroll status", "Paid")
        CANCELLED = "cancelled", pgettext_lazy("payroll status", "Cancelled")

    period = models.DateField(help_text=_("The first day of the month."))
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.REGULAR)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    usd_rate = RateField(null=True, blank=True, help_text=_("Som per dollar for dollar pay."))
    membership = models.ForeignKey(
        Membership,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="final_runs",
    )
    calculated_at = models.DateTimeField(null=True, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    totals = models.JSONField(default=dict, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = _user_link()
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = _user_link()

    class Meta:
        ordering = ("-period", "-pk")
        constraints = (
            models.UniqueConstraint(
                fields=("company", "period"),
                condition=Q(kind="regular") & ~Q(status="cancelled"),
                name="payroll_one_regular_run_a_month",
            ),
            models.UniqueConstraint(
                fields=("membership",),
                condition=Q(kind="final") & ~Q(status="cancelled"),
                name="payroll_one_final_run_a_person",
            ),
        )

    def __str__(self):
        return f"Payroll {self.period:%Y-%m}"

    @property
    def is_locked(self) -> bool:
        return self.status in (self.Status.FINALIZED, self.Status.PAID)


class Payslip(TenantModel):
    """One person's pay for a run. The lines are the truth: every total is their sum."""

    class Status(models.TextChoices):
        DRAFT = "draft", pgettext_lazy("payroll status", "Draft")
        PUBLISHED = "published", pgettext_lazy("payroll status", "Published")
        PAID = "paid", pgettext_lazy("payroll status", "Paid")

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="payslips")
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="payslips")
    currency = CurrencyField()
    pay_type = models.CharField(max_length=10, choices=PayType.choices)
    base_pay = MoneyField(default=Decimal(0))
    scheduled_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal(0))
    paid_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal(0))
    paid_leave_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal(0))
    unpaid_leave_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal(0))
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal(0))
    worked_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    night_minutes = models.PositiveIntegerField(default=0)
    late_arrivals = models.PositiveIntegerField(default=0)
    task_stats = models.JSONField(default=dict, blank=True)
    gross = MoneyField(default=Decimal(0))
    deductions = MoneyField(default=Decimal(0))
    net = MoneyField(default=Decimal(0))
    carried_debt = MoneyField(default=Decimal(0))
    taxes = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    viewed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = _user_link()
    payout_method = models.CharField(max_length=8, choices=PayoutMethod.choices, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    salary_debt = models.ForeignKey(
        "finance.Debt", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    pdf = models.FileField(
        storage=private_storage, upload_to=private_upload_to("payslips"), blank=True
    )

    class Meta:
        ordering = ("run_id", "membership__first_name", "membership__last_name", "pk")
        constraints = (
            models.UniqueConstraint(fields=("run", "membership"), name="payroll_one_payslip_each"),
        )

    def __str__(self):
        return f"Payslip #{self.pk}"


class PayslipLine(models.Model):
    """One line of a payslip, with what it was worked out from (`params`, `quantity` times `rate`).
    `amount` is signed: earnings are positive, deductions negative."""

    class Kind(models.TextChoices):
        BASE = "base", pgettext_lazy("payslip line", "Base pay")
        PRORATION = "proration", pgettext_lazy("payslip line", "Days not paid")
        OVERTIME = "overtime", pgettext_lazy("payslip line", "Overtime")
        HOLIDAY_WORK = "holiday_work", pgettext_lazy("payslip line", "Holiday work")
        NIGHT_WORK = "night_work", pgettext_lazy("payslip line", "Night work")
        PIECE = "piece", pgettext_lazy("payslip line", "Task pay")
        TASK_REWARD = "task_reward", pgettext_lazy("payslip line", "Task reward")
        BONUS = "bonus", pgettext_lazy("payslip line", "Bonus")
        ALLOWANCE = "allowance", pgettext_lazy("payslip line", "Allowance")
        REIMBURSEMENT = "reimbursement", pgettext_lazy("payslip line", "Expenses paid back")
        FINE = "fine", pgettext_lazy("payslip line", "Fine")
        DEDUCTION = "deduction", pgettext_lazy("payslip line", "Deduction")
        ADVANCE = "advance", pgettext_lazy("payslip line", "Advance repaid")
        LOAN = "loan", pgettext_lazy("payslip line", "Loan repaid")
        INCOME_TAX = "income_tax", pgettext_lazy("payslip line", "Income tax")
        INPS = "inps", pgettext_lazy("payslip line", "Pension contribution")
        LEAVE_COMPENSATION = "leave_compensation", pgettext_lazy("payslip line", "Paid leave")
        LEAVE_PAYOUT = "leave_payout", pgettext_lazy("payslip line", "Unused leave paid out")
        ROUNDING = "rounding", pgettext_lazy("payslip line", "Rounding")
        MANUAL = "manual", pgettext_lazy("payslip line", "Added by hand")

    # Lines that are pay for work; reimbursements and rounding are neither pay nor a deduction.
    EARNINGS = (
        Kind.BASE,
        Kind.PRORATION,
        Kind.OVERTIME,
        Kind.HOLIDAY_WORK,
        Kind.NIGHT_WORK,
        Kind.PIECE,
        Kind.TASK_REWARD,
        Kind.BONUS,
        Kind.ALLOWANCE,
        Kind.LEAVE_COMPENSATION,
        Kind.LEAVE_PAYOUT,
    )
    DEDUCTIONS = (
        Kind.FINE,
        Kind.DEDUCTION,
        Kind.ADVANCE,
        Kind.LOAN,
        Kind.INCOME_TAX,
        Kind.INPS,
    )
    CAPPED = (Kind.FINE, Kind.DEDUCTION)
    # A payslip row's parts (the run table's columns, signed like the lines). Every kind is in
    # exactly one and a line added by hand goes by its sign (pay to extras, a deduction to
    # fines), so the parts always add up to the net amount. The rounding of the net sits with
    # extras: it is never more than the rounding step, and the row's numbers stay whole.
    ROW_PARTS = {
        "base_pay": (Kind.BASE, Kind.PRORATION),
        "extras": (
            Kind.OVERTIME,
            Kind.HOLIDAY_WORK,
            Kind.NIGHT_WORK,
            Kind.PIECE,
            Kind.LEAVE_COMPENSATION,
            Kind.LEAVE_PAYOUT,
            Kind.ROUNDING,
        ),
        "bonuses": (Kind.BONUS, Kind.ALLOWANCE, Kind.TASK_REWARD),
        "fines": (Kind.FINE, Kind.DEDUCTION),
        "advances": (Kind.ADVANCE, Kind.LOAN),
        "taxes_withheld": (Kind.INCOME_TAX, Kind.INPS),
        "reimbursements": (Kind.REIMBURSEMENT,),
    }

    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    label = models.CharField(max_length=200)
    params = models.JSONField(default=dict, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    rate = MoneyField(null=True, blank=True)
    amount = MoneyField()
    adjustment = models.ForeignKey(
        Adjustment, on_delete=models.SET_NULL, null=True, blank=True, related_name="lines"
    )
    advance = models.ForeignKey(
        Advance, on_delete=models.SET_NULL, null=True, blank=True, related_name="lines"
    )
    debt = models.ForeignKey(
        "finance.Debt", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    order = models.PositiveSmallIntegerField(default=0)
    created_by = _user_link()

    class Meta:
        ordering = ("payslip_id", "order", "pk")

    def __str__(self):
        return f"Payslip line #{self.pk}"

    @classmethod
    def row_part(cls, kind: str, amount: Decimal) -> str:
        """The part of a payslip row a line adds to (see ROW_PARTS)."""
        if kind == cls.Kind.MANUAL:
            return "extras" if amount >= 0 else "fines"
        return next(part for part, kinds in cls.ROW_PARTS.items() if kind in kinds)

    @classmethod
    def row_parts(cls, lines) -> dict[str, Decimal]:
        """A payslip's lines summed by ROW_PARTS: every part, zero when it has no line."""
        parts = dict.fromkeys(cls.ROW_PARTS, Decimal(0))
        for line in lines:
            parts[cls.row_part(line.kind, line.amount)] += line.amount
        return parts
