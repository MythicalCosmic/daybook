"""Shapes of the payroll API (owner dashboard and mini app).

Money is a string with two decimals next to its `currency`; dates are company-local ISO days;
a period is the first day of its month ("2026-10-01"). Callers without `payroll.view` never
get an amount: `AmountsHidden` drops those fields before the response is built (the context's
`show_amounts`), so they are absent, not zero.
"""

from decimal import Decimal

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import Currency, MoneySerializerField
from apps.members.queries import person_ref
from apps.payroll import periods
from apps.payroll.models import (
    Adjustment,
    AdjustmentRule,
    Advance,
    Compensation,
    PayoutMethod,
    PayrollRun,
    PayrollSettings,
    Payslip,
    PayslipLine,
    PayType,
    TaskRate,
)

MONEY = {"coerce_to_string": True, "max_digits": 18, "decimal_places": 2}


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "PayrollPerson"


class PersonCardSerializer(PersonSerializer):
    position = serializers.CharField(allow_null=True)
    home_branch = serializers.CharField(allow_null=True)
    status = serializers.CharField()

    class Meta:
        ref_name = "PayrollPersonCard"


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "PayrollRef"


def person(member) -> dict | None:
    return person_ref(member)


def person_card(member) -> dict:
    return {
        **person_ref(member),
        "position": member.position.name if member.position_id else None,
        "home_branch": member.home_branch.name if member.home_branch_id else None,
        "status": member.status,
    }


def user_name(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or str(user)


class AmountsHidden:
    """Drops `amount_fields` from the output unless the context's `show_amounts` is true."""

    amount_fields: tuple[str, ...] = ()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context.get("show_amounts", False):
            for name in self.amount_fields:
                data.pop(name, None)
        return data


class PeriodField(serializers.Field):
    """A month: "2026-10" or any day in it in, its first day ("2026-10-01") out."""

    def to_internal_value(self, data):
        from apps.core.exceptions import DomainError

        try:
            return periods.parse_period(data)
        except DomainError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def to_representation(self, value):
        return value.isoformat() if value else None


extend_schema_field({"type": "string", "example": "2026-10-01"})(PeriodField)


# Settings -------------------------------------------------------------------------------


class SettingsSerializer(serializers.ModelSerializer):
    rounding_step = MoneySerializerField(positive=False, min_value=0)

    class Meta:
        model = PayrollSettings
        fields = (
            "currency",
            "pay_day",
            "advance_day",
            "advance_cap_percent",
            "amounts_are_net",
            "taxes_enabled",
            "income_tax_percent",
            "social_tax_percent",
            "inps_percent",
            "deductions_cap_percent",
            "rounding_step",
            "overtime_multiplier",
            "holiday_work_multiplier",
            "night_multiplier",
            "night_starts_at",
            "night_ends_at",
            "daily_hours",
            "auto_prepare",
            "leave_payout_months",
        )
        ref_name = "PayrollSettings"


# Pay setups -----------------------------------------------------------------------------


class CompensationSerializer(AmountsHidden, serializers.ModelSerializer):
    amount_fields = ("amount",)

    member = serializers.SerializerMethodField()
    amount = MoneySerializerField(positive=False, required=False)
    created_by = serializers.SerializerMethodField()
    locked_reason = serializers.SerializerMethodField()

    class Meta:
        model = Compensation
        fields = (
            "id",
            "member",
            "effective_from",
            "pay_type",
            "amount",
            "currency",
            "proration",
            "pays_task_rates",
            "overtime_eligible",
            "note",
            "locked",
            "locked_reason",
            "created_by",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(PersonSerializer)
    def get_member(self, row):
        return person(row.membership)

    def get_created_by(self, row) -> str | None:
        return user_name(row.created_by)

    def get_locked_reason(self, row) -> str | None:
        if not row.locked:
            return None
        return _("A finalized payroll used it. Add a new pay setup to change the pay.")


class CompensationWriteSerializer(serializers.Serializer):
    membership = serializers.IntegerField()
    effective_from = serializers.DateField()
    pay_type = serializers.ChoiceField(choices=PayType.choices, default=PayType.MONTHLY)
    amount = MoneySerializerField(positive=False, min_value=0)
    currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    proration = serializers.ChoiceField(
        choices=Compensation.Proration.choices, default=Compensation.Proration.ATTENDANCE
    )
    pays_task_rates = serializers.BooleanField(default=False)
    overtime_eligible = serializers.BooleanField(default=True)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "PayrollCompensationWrite"


class CompensationUpdateSerializer(serializers.Serializer):
    effective_from = serializers.DateField(required=False)
    pay_type = serializers.ChoiceField(choices=PayType.choices, required=False)
    amount = MoneySerializerField(positive=False, min_value=0, required=False)
    currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    proration = serializers.ChoiceField(choices=Compensation.Proration.choices, required=False)
    pays_task_rates = serializers.BooleanField(required=False)
    overtime_eligible = serializers.BooleanField(required=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        ref_name = "PayrollCompensationUpdate"


class PaySetupRowSerializer(serializers.Serializer):
    """A person on the Pay setups page: the setup in force today and the next one planned."""

    member = PersonCardSerializer()
    current = CompensationSerializer(allow_null=True)
    next = CompensationSerializer(allow_null=True)

    class Meta:
        ref_name = "PayrollPaySetupRow"


# Task rates -----------------------------------------------------------------------------


class TaskRateSerializer(AmountsHidden, serializers.ModelSerializer):
    amount_fields = ("amount",)

    template = serializers.SerializerMethodField()
    position = serializers.SerializerMethodField()
    amount = MoneySerializerField(positive=False, required=False)

    class Meta:
        model = TaskRate
        fields = ("id", "template", "position", "amount", "currency", "on_time_only", "is_active")
        read_only_fields = fields

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_template(self, row):
        return {"id": row.template_id, "name": row.template.title} if row.template_id else None

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_position(self, row):
        return {"id": row.position_id, "name": row.position.name} if row.position_id else None


class TaskRateWriteSerializer(serializers.Serializer):
    template = serializers.IntegerField(required=False, allow_null=True)
    position = serializers.IntegerField(required=False, allow_null=True)
    amount = MoneySerializerField(required=False)
    currency = serializers.ChoiceField(choices=Currency.choices, required=False)
    on_time_only = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "PayrollTaskRateWrite"


# Bonuses and fines ----------------------------------------------------------------------


class AdjustmentSerializer(AmountsHidden, serializers.ModelSerializer):
    amount_fields = ("amount",)

    member = serializers.SerializerMethodField()
    period = PeriodField()
    amount = MoneySerializerField(positive=False, required=False)
    rule = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()
    proposed_by = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    dispute_open = serializers.BooleanField()
    locked = serializers.BooleanField(source="is_locked")
    payslip = serializers.IntegerField(source="payslip_id", allow_null=True)

    class Meta:
        model = Adjustment
        fields = (
            "id",
            "member",
            "period",
            "kind",
            "amount",
            "currency",
            "reason",
            "source",
            "rule",
            "task",
            "status",
            "proposed_by",
            "created_at",
            "decided_by",
            "decided_at",
            "decision_note",
            "disputed_at",
            "dispute_text",
            "dispute_answer",
            "dispute_answered_at",
            "dispute_open",
            "locked",
            "payslip",
        )
        read_only_fields = fields

    @extend_schema_field(PersonSerializer)
    def get_member(self, row):
        return person(row.membership)

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_rule(self, row):
        return {"id": row.rule_id, "name": row.rule.name} if row.rule_id else None

    @extend_schema_field(RefSerializer(allow_null=True))
    def get_task(self, row):
        return {"id": row.task_id, "name": row.task.title} if row.task_id else None

    def get_proposed_by(self, row) -> str | None:
        return user_name(row.proposed_by)

    def get_decided_by(self, row) -> str | None:
        return user_name(row.decided_by)


class AdjustmentWriteSerializer(serializers.Serializer):
    membership = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=Adjustment.Kind.choices)
    amount = MoneySerializerField()
    reason = serializers.CharField(max_length=300)
    period = PeriodField(required=False)
    approve = serializers.BooleanField(default=False, help_text="Approve at once (payroll.manage).")

    class Meta:
        ref_name = "PayrollAdjustmentWrite"


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    class Meta:
        ref_name = "PayrollReason"


class RequiredReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "PayrollRequiredReason"


class AnswerDisputeSerializer(serializers.Serializer):
    answer = serializers.CharField(max_length=500, required=False, allow_blank=True)
    reason = serializers.CharField(
        max_length=500, required=False, allow_blank=True, help_text="Same as answer (Needs you)."
    )
    void = serializers.BooleanField(default=False, help_text="Also take the fine back.")

    class Meta:
        ref_name = "PayrollAnswerDispute"


class BulkDecideSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=200)
    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    class Meta:
        ref_name = "PayrollBulkDecide"


class BulkResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    ok = serializers.BooleanField()
    status = serializers.CharField(required=False)
    error = serializers.CharField(required=False)

    class Meta:
        ref_name = "PayrollBulkResult"


# Advances -------------------------------------------------------------------------------


class RepaymentSerializer(AmountsHidden, serializers.Serializer):
    amount_fields = ("amount",)

    id = serializers.IntegerField()
    amount = MoneySerializerField(positive=False, required=False)
    paid_on = serializers.DateField()
    note = serializers.CharField()
    payslip = serializers.SerializerMethodField()
    how = serializers.SerializerMethodField()

    class Meta:
        ref_name = "PayrollRepayment"

    def get_payslip(self, row) -> int | None:
        return row.payslip_line.payslip_id if row.payslip_line_id else None

    def get_how(self, row) -> str:
        return "payslip" if row.payslip_line_id else "money"


class AdvanceSerializer(AmountsHidden, serializers.ModelSerializer):
    amount_fields = ("amount", "repaid", "left")

    member = serializers.SerializerMethodField()
    amount = MoneySerializerField(positive=False, required=False)
    first_period = PeriodField()
    repaid = serializers.SerializerMethodField()
    left = serializers.SerializerMethodField()
    repayments = serializers.SerializerMethodField()
    requested_by = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    paid_by = serializers.SerializerMethodField()
    debt = serializers.IntegerField(source="debt_id", allow_null=True)

    class Meta:
        model = Advance
        fields = (
            "id",
            "member",
            "amount",
            "currency",
            "installments",
            "first_period",
            "reason",
            "status",
            "requested_by",
            "created_at",
            "decided_by",
            "decided_at",
            "decision_note",
            "paid_at",
            "paid_by",
            "payout_method",
            "repaid",
            "left",
            "repayments",
            "debt",
        )
        read_only_fields = fields

    @extend_schema_field(PersonSerializer)
    def get_member(self, row):
        return person(row.membership)

    def _repaid(self, row):
        return sum((r.amount for r in row.repayments.all()), Decimal(0))

    @extend_schema_field({"type": "string", "example": "500000.00"})
    def get_repaid(self, row):
        return f"{self._repaid(row):.2f}"

    @extend_schema_field({"type": "string", "example": "500000.00"})
    def get_left(self, row):
        if row.status not in (Advance.Status.PAID, Advance.Status.REPAID):
            return f"{row.amount:.2f}"
        return f"{row.amount - self._repaid(row):.2f}"

    @extend_schema_field(RepaymentSerializer(many=True))
    def get_repayments(self, row):
        rows = sorted(row.repayments.all(), key=lambda r: (r.paid_on, r.pk))
        return RepaymentSerializer(rows, many=True, context=self.context).data

    def get_requested_by(self, row) -> str | None:
        return user_name(row.requested_by)

    def get_decided_by(self, row) -> str | None:
        return user_name(row.decided_by)

    def get_paid_by(self, row) -> str | None:
        return user_name(row.paid_by)


class AdvanceWriteSerializer(serializers.Serializer):
    membership = serializers.IntegerField()
    amount = MoneySerializerField()
    installments = serializers.IntegerField(min_value=1, max_value=12, default=1)
    first_period = PeriodField(required=False)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    class Meta:
        ref_name = "PayrollAdvanceWrite"


class AdvanceDecideSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    installments = serializers.IntegerField(min_value=1, max_value=12, required=False)
    first_period = PeriodField(required=False)

    class Meta:
        ref_name = "PayrollAdvanceDecide"


class AdvancePaySerializer(serializers.Serializer):
    account = serializers.IntegerField()
    method = serializers.ChoiceField(choices=PayoutMethod.choices, default=PayoutMethod.CASH)
    paid_on = serializers.DateField(required=False)

    class Meta:
        ref_name = "PayrollAdvancePay"


class AdvanceRepaySerializer(serializers.Serializer):
    amount = MoneySerializerField()
    account = serializers.IntegerField()
    paid_on = serializers.DateField(required=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    class Meta:
        ref_name = "PayrollAdvanceRepay"


# The mini app ---------------------------------------------------------------------------


class AdvanceCapSerializer(serializers.Serializer):
    currency = serializers.CharField()
    percent = serializers.IntegerField()
    cap = serializers.DecimalField(**MONEY)
    used = serializers.DecimalField(**MONEY)
    available = serializers.DecimalField(**MONEY)

    class Meta:
        ref_name = "PayrollAdvanceCap"


class MyAdvancesSerializer(serializers.Serializer):
    cap = AdvanceCapSerializer()
    advances = AdvanceSerializer(many=True)

    class Meta:
        ref_name = "PayrollMyAdvances"


class AdvanceRequestSerializer(serializers.Serializer):
    amount = MoneySerializerField()
    installments = serializers.IntegerField(min_value=1, max_value=12, default=1)
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    class Meta:
        ref_name = "PayrollAdvanceRequest"


class DisputeSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500)

    class Meta:
        ref_name = "PayrollDispute"


class RuleRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdjustmentRule
        fields = ("id", "name")
        ref_name = "PayrollRuleRef"


# Runs and payslips ----------------------------------------------------------------------


class RunTotalsSerializer(serializers.Serializer):
    currency = serializers.CharField()
    people = serializers.IntegerField()
    gross = serializers.CharField()
    deductions = serializers.CharField()
    net = serializers.CharField()
    bonuses = serializers.CharField()
    fines = serializers.CharField()
    advances = serializers.CharField()
    reimbursements = serializers.CharField()
    taxes = serializers.DictField(child=serializers.CharField())
    paid = serializers.IntegerField()
    published = serializers.IntegerField()

    class Meta:
        ref_name = "PayrollRunTotals"


class WarningSerializer(serializers.Serializer):
    code = serializers.CharField()
    level = serializers.CharField()
    text = serializers.CharField()
    member = PersonSerializer(allow_null=True, required=False)
    count = serializers.IntegerField(required=False)

    class Meta:
        ref_name = "PayrollWarning"


def warnings_out(run) -> list[dict]:
    from apps.payroll import labels

    rows = []
    for warning in run.warnings or []:
        rows.append(
            {
                "code": warning.get("code", ""),
                "level": warning.get("level", "warning"),
                "text": labels.warning_text(warning),
                "member": warning.get("member"),
                **({"count": warning["count"]} if "count" in warning else {}),
            }
        )
    return rows


class RunSerializer(serializers.ModelSerializer):
    """A run. Its totals (money) reach only payroll.view holders, who alone read runs."""

    period = PeriodField()
    month = serializers.SerializerMethodField()
    member = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()
    usd_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, coerce_to_string=True, allow_null=True
    )
    finalized_by = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = (
            "id",
            "period",
            "month",
            "kind",
            "status",
            "member",
            "usd_rate",
            "calculated_at",
            "totals",
            "warnings",
            "finalized_at",
            "finalized_by",
            "paid_at",
            "notes",
            "created_at",
            "actions",
        )
        read_only_fields = fields

    def get_month(self, run) -> str:
        from apps.payroll import queries

        return queries.month_label(run.period)

    @extend_schema_field(PersonSerializer(allow_null=True))
    def get_member(self, run):
        return person(run.membership) if run.membership_id else None

    @extend_schema_field(RunTotalsSerializer)
    def get_totals(self, run):
        return run.totals or {}

    @extend_schema_field(WarningSerializer(many=True))
    def get_warnings(self, run):
        return warnings_out(run)

    def get_finalized_by(self, run) -> str | None:
        return user_name(run.finalized_by)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_actions(self, run):
        """What the caller may do with the run now: calculate, finalize, reopen, cancel,
        publish, mark_paid."""
        member = self.context.get("membership")
        if member is None:
            return []
        status = run.status
        found = []
        if status == PayrollRun.Status.DRAFT:
            if member.has_perm("payroll.manage"):
                found += ["calculate", "cancel"]
            if member.has_perm("payroll.finalize"):
                found.append("finalize")
        elif status == PayrollRun.Status.FINALIZED:
            if member.has_perm("payroll.finalize"):
                if not (run.totals or {}).get("paid"):
                    found.append("reopen")
                found.append("publish")
            if member.has_perm("payroll.pay"):
                found.append("mark_paid")
        elif status == PayrollRun.Status.PAID and member.has_perm("payroll.finalize"):
            found.append("publish")
        return found


class RunCreateSerializer(serializers.Serializer):
    period = PeriodField()
    usd_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, min_value=Decimal("0.000001"), required=False
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    class Meta:
        ref_name = "PayrollRunCreate"


class RunCalculateSerializer(serializers.Serializer):
    usd_rate = serializers.DecimalField(
        max_digits=18, decimal_places=6, min_value=Decimal("0.000001"), required=False
    )

    class Meta:
        ref_name = "PayrollRunCalculate"


class PublishSerializer(serializers.Serializer):
    payslip_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True, max_length=1000
    )

    class Meta:
        ref_name = "PayrollPublish"


class MarkPaidSerializer(serializers.Serializer):
    payslip_ids = serializers.ListField(
        child=serializers.IntegerField(), min_length=1, max_length=1000
    )
    method = serializers.ChoiceField(choices=PayoutMethod.choices, default=PayoutMethod.CASH)
    account = serializers.IntegerField()
    paid_on = serializers.DateField(required=False)

    class Meta:
        ref_name = "PayrollMarkPaid"


class LineSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    amount = MoneySerializerField(positive=False)
    rate = MoneySerializerField(positive=False, allow_null=True)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True, allow_null=True
    )
    adjustment = serializers.IntegerField(source="adjustment_id", allow_null=True)
    advance = serializers.IntegerField(source="advance_id", allow_null=True)
    manual = serializers.SerializerMethodField()

    class Meta:
        model = PayslipLine
        fields = (
            "id",
            "kind",
            "label",
            "quantity",
            "rate",
            "amount",
            "params",
            "adjustment",
            "advance",
            "manual",
        )
        read_only_fields = fields

    def get_label(self, line) -> str:
        from apps.payroll import labels

        return labels.line_label(line)

    def get_manual(self, line) -> bool:
        return line.kind == PayslipLine.Kind.MANUAL


PAYSLIP_AMOUNTS = ("base_pay", "gross", "deductions", "net", "carried_debt")


class PayslipRowSerializer(serializers.ModelSerializer):
    """A row of a run's payslip table: the person and their sums by kind."""

    member = serializers.SerializerMethodField()
    base_pay = MoneySerializerField(positive=False)
    gross = MoneySerializerField(positive=False)
    deductions = MoneySerializerField(positive=False)
    net = MoneySerializerField(positive=False)
    bonuses = serializers.SerializerMethodField()
    fines = serializers.SerializerMethodField()
    advances = serializers.SerializerMethodField()
    reimbursements = serializers.SerializerMethodField()
    period = serializers.SerializerMethodField()

    class Meta:
        model = Payslip
        fields = (
            "id",
            "member",
            "period",
            "pay_type",
            "currency",
            "base_pay",
            "bonuses",
            "fines",
            "advances",
            "reimbursements",
            "gross",
            "deductions",
            "net",
            "status",
            "published_at",
            "viewed_at",
            "paid_at",
            "received_at",
            "payout_method",
        )
        read_only_fields = fields

    @extend_schema_field(PersonCardSerializer)
    def get_member(self, payslip):
        return person_card(payslip.membership)

    def get_period(self, payslip) -> str:
        return payslip.run.period.isoformat()

    def _sum(self, payslip, kinds) -> str:
        lines = getattr(payslip, "_lines_cache", None)
        if lines is None:
            lines = list(payslip.lines.all())
            payslip._lines_cache = lines
        return f"{sum((line.amount for line in lines if line.kind in kinds), Decimal(0)):.2f}"

    def get_bonuses(self, payslip) -> str:
        Kind = PayslipLine.Kind
        return self._sum(payslip, (Kind.BONUS, Kind.ALLOWANCE, Kind.TASK_REWARD))

    def get_fines(self, payslip) -> str:
        Kind = PayslipLine.Kind
        return self._sum(payslip, (Kind.FINE, Kind.DEDUCTION))

    def get_advances(self, payslip) -> str:
        return self._sum(payslip, (PayslipLine.Kind.ADVANCE,))

    def get_reimbursements(self, payslip) -> str:
        return self._sum(payslip, (PayslipLine.Kind.REIMBURSEMENT,))


class PayslipSerializer(PayslipRowSerializer):
    """A payslip with every line and how it was worked out."""

    lines = serializers.SerializerMethodField()
    month = serializers.SerializerMethodField()
    run = serializers.IntegerField(source="run_id")
    run_status = serializers.CharField(source="run.status")
    taxes = serializers.DictField()
    task_stats = serializers.DictField()
    scheduled_days = serializers.DecimalField(max_digits=5, decimal_places=1, coerce_to_string=True)
    paid_days = serializers.DecimalField(max_digits=5, decimal_places=1, coerce_to_string=True)
    paid_leave_days = serializers.DecimalField(
        max_digits=5, decimal_places=1, coerce_to_string=True
    )
    unpaid_leave_days = serializers.DecimalField(
        max_digits=5, decimal_places=1, coerce_to_string=True
    )
    absent_days = serializers.DecimalField(max_digits=5, decimal_places=1, coerce_to_string=True)

    class Meta(PayslipRowSerializer.Meta):
        fields = (
            *PayslipRowSerializer.Meta.fields,
            "run",
            "run_status",
            "month",
            "scheduled_days",
            "paid_days",
            "paid_leave_days",
            "unpaid_leave_days",
            "absent_days",
            "worked_minutes",
            "overtime_minutes",
            "night_minutes",
            "late_arrivals",
            "task_stats",
            "taxes",
            "lines",
        )
        read_only_fields = fields
        ref_name = "PayrollPayslip"

    def get_month(self, payslip) -> str:
        from apps.payroll import queries

        return queries.month_label(payslip.run.period)

    @extend_schema_field(LineSerializer(many=True))
    def get_lines(self, payslip):
        lines = payslip.lines.select_related("adjustment", "payslip").order_by("order", "pk")
        return LineSerializer(lines, many=True, context=self.context).data


class ManualLineSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    label = serializers.CharField(max_length=200)
    amount = MoneySerializerField(positive=False)

    class Meta:
        ref_name = "PayrollManualLine"


class PayslipPatchSerializer(serializers.Serializer):
    manual_lines = ManualLineSerializer(many=True, max_length=20)

    class Meta:
        ref_name = "PayrollPayslipPatch"


class FileLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    name = serializers.CharField()
    expires_in = serializers.IntegerField()

    class Meta:
        ref_name = "PayrollFileLink"


# Rules ----------------------------------------------------------------------------------


class TierSerializer(serializers.Serializer):
    threshold = serializers.DecimalField(max_digits=16, decimal_places=2, coerce_to_string=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, coerce_to_string=True)

    class Meta:
        ref_name = "PayrollRuleTier"


class RuleSerializer(AmountsHidden, serializers.ModelSerializer):
    amount_fields = ("amount", "cap", "tiers")

    threshold = serializers.DecimalField(
        max_digits=16, decimal_places=2, coerce_to_string=True, allow_null=True
    )
    free_units = serializers.DecimalField(max_digits=10, decimal_places=2, coerce_to_string=True)
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, coerce_to_string=True, allow_null=True, required=False
    )
    cap = MoneySerializerField(positive=False, allow_null=True, required=False)
    tiers = TierSerializer(many=True, required=False)
    positions = serializers.SerializerMethodField()
    example = serializers.SerializerMethodField()

    class Meta:
        model = AdjustmentRule
        fields = (
            "id",
            "name",
            "kind",
            "metric",
            "mode",
            "op",
            "threshold",
            "free_units",
            "tiers",
            "amount_type",
            "amount",
            "cap",
            "min_tasks",
            "positions",
            "evaluate",
            "auto_approve",
            "is_active",
            "example",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(RefSerializer(many=True))
    def get_positions(self, rule):
        return [{"id": p.pk, "name": p.name} for p in rule.positions.all()]

    def get_example(self, rule) -> bool:
        return bool(rule.example_key)


class RuleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    kind = serializers.ChoiceField(choices=AdjustmentRule.Kind.choices, required=False)
    metric = serializers.ChoiceField(choices=AdjustmentRule.Metric.choices, required=False)
    mode = serializers.ChoiceField(choices=AdjustmentRule.Mode.choices, required=False)
    op = serializers.ChoiceField(choices=AdjustmentRule.Op.choices, required=False)
    threshold = serializers.DecimalField(
        max_digits=16, decimal_places=2, allow_null=True, required=False
    )
    free_units = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), required=False
    )
    tiers = TierSerializer(many=True, required=False, max_length=10)
    amount_type = serializers.ChoiceField(choices=AdjustmentRule.AmountType.choices, required=False)
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True, required=False
    )
    cap = serializers.DecimalField(max_digits=18, decimal_places=2, allow_null=True, required=False)
    min_tasks = serializers.IntegerField(min_value=0, max_value=1000, required=False)
    positions = serializers.ListField(child=serializers.IntegerField(), required=False)
    evaluate = serializers.ChoiceField(choices=AdjustmentRule.Evaluate.choices, required=False)
    auto_approve = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)

    class Meta:
        ref_name = "PayrollRuleWrite"


class RulePreviewRequestSerializer(serializers.Serializer):
    period = PeriodField(required=False)

    class Meta:
        ref_name = "PayrollRulePreviewRequest"


class RulePreviewRowSerializer(AmountsHidden, serializers.Serializer):
    amount_fields = ("amount",)

    member = PersonSerializer()
    value = serializers.CharField(allow_null=True)
    amount = serializers.CharField(allow_null=True, required=False)
    units = serializers.CharField(allow_null=True)
    tier = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "PayrollRulePreviewRow"


class RulePreviewSerializer(serializers.Serializer):
    period = serializers.CharField()
    to = serializers.CharField()
    currency = serializers.CharField()
    total = serializers.CharField(required=False)
    rows = RulePreviewRowSerializer(many=True)

    class Meta:
        ref_name = "PayrollRulePreview"


# Overview and the wallet ----------------------------------------------------------------


class OverviewMonthSerializer(serializers.Serializer):
    period = serializers.CharField()
    label = serializers.CharField()
    status = serializers.CharField()
    people = serializers.IntegerField()
    gross = serializers.CharField()
    net = serializers.CharField()
    bonuses = serializers.CharField()
    fines = serializers.CharField()
    advances = serializers.CharField()

    class Meta:
        ref_name = "PayrollOverviewMonth"


class OverviewGroupSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    people = serializers.IntegerField()
    gross = serializers.CharField()

    class Meta:
        ref_name = "PayrollOverviewGroup"


class OverviewProjectedSerializer(serializers.Serializer):
    period = serializers.CharField()
    label = serializers.CharField()
    source = serializers.ChoiceField(choices=("run", "estimate"))
    people = serializers.IntegerField()
    gross = serializers.CharField()
    net = serializers.CharField()

    class Meta:
        ref_name = "PayrollOverviewProjected"


class OverviewPendingSerializer(serializers.Serializer):
    adjustments = serializers.IntegerField()
    disputes = serializers.IntegerField()
    advances = serializers.IntegerField()

    class Meta:
        ref_name = "PayrollOverviewPending"


class OverviewSerializer(serializers.Serializer):
    currency = serializers.CharField()
    months = OverviewMonthSerializer(many=True)
    latest = serializers.DictField(allow_null=True)
    by_position = OverviewGroupSerializer(many=True)
    by_branch = OverviewGroupSerializer(many=True)
    projected = OverviewProjectedSerializer()
    headcount = serializers.IntegerField()
    pending = OverviewPendingSerializer()

    class Meta:
        ref_name = "PayrollOverview"


class EarningsSumsSerializer(serializers.Serializer):
    base = serializers.CharField()
    extra = serializers.CharField()
    pieces = serializers.CharField()
    bonuses = serializers.CharField()
    fines = serializers.CharField()
    taxes = serializers.CharField()
    advances = serializers.CharField()
    reimbursements = serializers.CharField()
    net = serializers.CharField()

    class Meta:
        ref_name = "PayrollEarningsSums"


class EarningsProposedSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    amount = serializers.CharField()
    reason = serializers.CharField()
    source = serializers.CharField()

    class Meta:
        ref_name = "PayrollEarningsProposed"


class EarningsProgressSerializer(serializers.Serializer):
    rule = serializers.IntegerField()
    name = serializers.CharField()
    metric = serializers.CharField()
    value = serializers.CharField()
    earned = serializers.CharField()
    target = serializers.CharField(allow_null=True)
    target_amount = serializers.CharField(allow_null=True)
    min_tasks = serializers.IntegerField(allow_null=True)
    tasks = serializers.IntegerField(allow_null=True)

    class Meta:
        ref_name = "PayrollEarningsProgress"


class EarningsSerializer(serializers.Serializer):
    period = serializers.CharField()
    as_of = serializers.CharField()
    currency = serializers.CharField()
    has_pay_setup = serializers.BooleanField()
    pay_type = serializers.CharField(allow_null=True)
    so_far = EarningsSumsSerializer()
    estimate = EarningsSumsSerializer()
    worked_minutes = serializers.IntegerField()
    scheduled_days = serializers.IntegerField()
    absent_days = serializers.IntegerField()
    proposed = EarningsProposedSerializer(many=True)
    progress = EarningsProgressSerializer(many=True)

    class Meta:
        ref_name = "PayrollEarnings"
