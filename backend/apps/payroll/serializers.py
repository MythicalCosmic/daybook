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
    PayrollSettings,
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
