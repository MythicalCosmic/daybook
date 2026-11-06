"""Serializers of the money-planning endpoints (Package I, `planning_api.py`): recurring
payments and the tax calendar, upcoming payments, the forecast, budgets, payables and claims.

Money is a string ("1250000.00"), days are company-local `YYYY-MM-DD`, months `YYYY-MM`.
"""

from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import MoneySerializerField
from apps.finance import recurring
from apps.finance.models import Category, Claim, RecurringRule
from apps.finance.owner_serializers import (
    FinanceAccountRefSerializer,
    FinanceRefSerializer,
    account_ref,
    category_ref,
    money_out,
)
from apps.members.queries import person_ref


class PlanningCategoryRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    color = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
    parent_name = serializers.CharField(allow_null=True)


class PlanningPersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)


def category_out(category) -> dict | None:
    if category is None:
        return None
    return {**category_ref(category), "parent_id": category.parent_id}


def ref(row) -> dict | None:
    return {"id": row.pk, "name": str(row)} if row is not None else None


# Recurring payments ---------------------------------------------------------------------------


class RecurringRuleSerializer(serializers.ModelSerializer):
    """A recurring payment, its open occurrence (after the holiday move) and the next three."""

    category = serializers.SerializerMethodField()
    counterparty = serializers.SerializerMethodField()
    account = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    payer = serializers.SerializerMethodField()
    amount = money_out()
    next_due_on = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()
    is_tax = serializers.SerializerMethodField()
    upcoming = serializers.SerializerMethodField()

    class Meta:
        model = RecurringRule
        fields = (
            "id",
            "name",
            "kind",
            "mode",
            "frequency",
            "interval",
            "day",
            "on_holiday",
            "category",
            "counterparty",
            "account",
            "branch",
            "amount",
            "currency",
            "amount_varies",
            "starts_on",
            "ends_on",
            "next_due_on",
            "overdue",
            "remind_days_before",
            "payer",
            "template_key",
            "is_tax",
            "is_active",
            "last_done_on",
            "upcoming",
            "created_at",
        )

    def _days_off(self) -> set:
        return self.context.get("days_off") or set()

    def _dates(self, rule) -> list:
        cache = self.context.setdefault("_dates", {})
        if rule.pk not in cache:
            cache[rule.pk] = (
                recurring.next_dates(rule, 3, self._days_off()) if rule.is_active else []
            )
        return cache[rule.pk]

    @extend_schema_field(PlanningCategoryRefSerializer)
    def get_category(self, rule):
        return category_out(rule.category)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_counterparty(self, rule):
        return ref(rule.counterparty)

    @extend_schema_field(FinanceAccountRefSerializer(allow_null=True))
    def get_account(self, rule):
        return account_ref(rule.account)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_branch(self, rule):
        return ref(rule.branch)

    @extend_schema_field(PlanningPersonRefSerializer(allow_null=True))
    def get_payer(self, rule):
        return person_ref(rule.payer)

    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_next_due_on(self, rule):
        dates = self._dates(rule)
        return dates[0].isoformat() if dates else None

    def get_overdue(self, rule) -> bool:
        dates = self._dates(rule)
        return (
            bool(dates)
            and rule.mode == RecurringRule.Mode.BILL
            and dates[0] < self.context["today"]
        )

    def get_is_tax(self, rule) -> bool:
        return rule.template_key.startswith("tax.")

    @extend_schema_field(serializers.ListField(child=serializers.DateField()))
    def get_upcoming(self, rule):
        return [day.isoformat() for day in self._dates(rule)]


class RecurringRuleWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(Category.Kind.choices, default=Category.Kind.EXPENSE)
    mode = serializers.ChoiceField(RecurringRule.Mode.choices, default=RecurringRule.Mode.BILL)
    frequency = serializers.ChoiceField(RecurringRule.Frequency.choices)
    interval = serializers.IntegerField(min_value=1, max_value=24, default=1)
    day = serializers.IntegerField(min_value=1, max_value=31)
    on_holiday = serializers.ChoiceField(
        RecurringRule.OnHoliday.choices, default=RecurringRule.OnHoliday.BEFORE
    )
    category = serializers.IntegerField()
    counterparty = serializers.IntegerField(required=False, allow_null=True)
    account = serializers.IntegerField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)
    amount = MoneySerializerField(positive=False, required=False)
    amount_varies = serializers.BooleanField(default=False)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(required=False, allow_null=True)
    remind_days_before = serializers.IntegerField(min_value=0, max_value=30, default=3)
    payer = serializers.IntegerField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)


class RecurringPaySerializer(serializers.Serializer):
    account = serializers.IntegerField()
    amount = MoneySerializerField(required=False, allow_null=True)
    paid_on = serializers.DateField(required=False, allow_null=True)


class RecurringPaymentSerializer(serializers.Serializer):
    rule = RecurringRuleSerializer()
    transaction_id = serializers.IntegerField(allow_null=True)


class TemplateItemSerializer(serializers.Serializer):
    template_key = serializers.CharField()
    name = serializers.CharField()
    frequency = serializers.CharField()
    day = serializers.IntegerField()
    category_code = serializers.CharField()
    applied = serializers.BooleanField()
    rule_id = serializers.IntegerField(allow_null=True)


class TemplateSetSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    current = serializers.BooleanField()
    note = serializers.CharField()
    items = TemplateItemSerializer(many=True)


# Upcoming and the forecast --------------------------------------------------------------------


class UpcomingItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField()
    date = serializers.DateField()
    amount = serializers.CharField(allow_null=True)
    currency = serializers.CharField()
    direction = serializers.CharField()
    overdue = serializers.BooleanField()
    estimate = serializers.BooleanField()
    rule_id = serializers.IntegerField(allow_null=True)
    debt_id = serializers.IntegerField(allow_null=True)
    url = serializers.CharField()


class UpcomingSerializer(serializers.Serializer):
    today = serializers.DateField()
    days = serializers.IntegerField()
    currency = serializers.CharField()
    items = UpcomingItemSerializer(many=True)
    totals = serializers.DictField(child=serializers.CharField())


class ForecastEventSerializer(serializers.Serializer):
    date = serializers.DateField()
    title = serializers.CharField()
    amount = serializers.CharField()
    direction = serializers.CharField()


class ForecastSerializer(serializers.Serializer):
    today = serializers.DateField()
    days = serializers.IntegerField()
    currency = serializers.CharField()
    start = serializers.CharField()
    end = serializers.CharField()
    # {date, balance, in, out} per day ("in" can't be a serializer field name).
    points = serializers.ListField(child=serializers.DictField())
    low = serializers.DictField()
    below_zero_on = serializers.DateField(allow_null=True)
    basis = serializers.DictField()
    events = ForecastEventSerializer(many=True)


# Budgets --------------------------------------------------------------------------------------


class BudgetRowSerializer(serializers.Serializer):
    category = PlanningCategoryRefSerializer()
    budget = serializers.CharField(allow_null=True)
    actual = serializers.CharField()
    share = serializers.CharField(allow_null=True)
    status = serializers.CharField()


class BudgetMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    currency = serializers.CharField()
    days_left = serializers.IntegerField()
    days_in_month = serializers.IntegerField()
    rows = BudgetRowSerializer(many=True)
    totals = serializers.DictField(child=serializers.CharField())


class BudgetInputRowSerializer(serializers.Serializer):
    category = serializers.IntegerField()
    amount = MoneySerializerField(required=False, allow_null=True)

    def to_internal_value(self, data):
        if isinstance(data, dict) and data.get("amount") == "":
            data = {**data, "amount": None}
        return super().to_internal_value(data)


class BudgetPutSerializer(serializers.Serializer):
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$")
    rows = BudgetInputRowSerializer(many=True)


class BudgetCopySerializer(serializers.Serializer):
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$")


# Payables -------------------------------------------------------------------------------------


class PayablesSerializer(serializers.Serializer):
    today = serializers.DateField()
    currency = serializers.CharField()
    # [{counterparty, total, overdue, debts: [Debt + bucket, bank_only]}]
    groups = serializers.ListField(child=serializers.DictField())
    totals = serializers.DictField(child=serializers.CharField())


class PayablesPayDebtSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = MoneySerializerField()


class PayablesPaySerializer(serializers.Serializer):
    account = serializers.IntegerField()
    paid_on = serializers.DateField()
    debts = PayablesPayDebtSerializer(many=True)

    def validate_debts(self, value):
        if not value:
            raise serializers.ValidationError(_("Pick at least one debt."))
        if len(value) > 100:
            raise serializers.ValidationError(_("Pay at most 100 debts at once."))
        ids = [row["id"] for row in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError(_("Each debt only once."))
        return value


class PayablesPaidSerializer(serializers.Serializer):
    paid = serializers.ListField(child=serializers.DictField())
    warnings = serializers.ListField(child=serializers.CharField())


class CreditSerializer(serializers.Serializer):
    amount = MoneySerializerField()
    reason = serializers.CharField(max_length=300)
    credited_on = serializers.DateField(required=False, allow_null=True)


# Claims ---------------------------------------------------------------------------------------


class ClaimReceiptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField()
    thumb_url = serializers.CharField(allow_null=True)
    content_type = serializers.CharField()
    is_image = serializers.BooleanField()


class ClaimSerializer(serializers.ModelSerializer):
    """An expense claim, with what the viewer may do with it (`context["membership"]`)."""

    member = serializers.SerializerMethodField()
    amount = money_out()
    category = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    branch = serializers.SerializerMethodField()
    receipts = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    reimburse_via = serializers.SerializerMethodField()
    transaction_id = serializers.IntegerField(allow_null=True, read_only=True)
    debt_id = serializers.IntegerField(allow_null=True, read_only=True)
    can_decide = serializers.SerializerMethodField()
    can_pay = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = (
            "id",
            "member",
            "amount",
            "currency",
            "category",
            "spent_on",
            "description",
            "paid_from",
            "status",
            "status_label",
            "branch",
            "receipts",
            "created_at",
            "decided_by",
            "decided_at",
            "reject_reason",
            "reimburse_via",
            "transaction_id",
            "debt_id",
            "can_decide",
            "can_pay",
            "can_cancel",
        )

    def _status(self, claim) -> str:
        from apps.finance import claims

        return claims.effective_status(claim)

    @extend_schema_field(PlanningPersonRefSerializer)
    def get_member(self, claim):
        return person_ref(claim.membership)

    @extend_schema_field(PlanningCategoryRefSerializer)
    def get_category(self, claim):
        return category_out(claim.category)

    def get_status(self, claim) -> str:
        return self._status(claim)

    def get_status_label(self, claim) -> str:
        return str(Claim.Status(self._status(claim)).label)

    @extend_schema_field(FinanceRefSerializer(allow_null=True))
    def get_branch(self, claim):
        return ref(claim.branch)

    @extend_schema_field(ClaimReceiptSerializer(many=True))
    def get_receipts(self, claim):
        from apps.finance import claims

        user = self.context["membership"].user
        return claims.receipt_links(claim, user=user)

    @extend_schema_field(PlanningPersonRefSerializer(allow_null=True))
    def get_decided_by(self, claim):
        if claim.decided_by_id is None:
            return None
        member = claim.company.memberships.filter(user_id=claim.decided_by_id).first()
        if member is not None:
            return person_ref(member)
        return {"id": 0, "name": str(claim.decided_by), "photo_url": None}

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reimburse_via(self, claim):
        from apps.finance import claims

        if claim.paid_from != Claim.PaidFrom.OWN_MONEY:
            return None
        return claims.reimburse_route(claim.company)

    def get_can_decide(self, claim) -> bool:
        from apps.finance import claims

        return claims.can_decide(self.context["membership"], claim)

    def get_can_pay(self, claim) -> bool:
        from apps.finance import claims

        return claims.can_pay(self.context["membership"], claim)

    def get_can_cancel(self, claim) -> bool:
        return (
            claim.status == Claim.Status.SUBMITTED
            and claim.membership_id == self.context["membership"].pk
        )


class ClaimRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class ClaimPaySerializer(serializers.Serializer):
    account = serializers.IntegerField()
    paid_on = serializers.DateField(required=False, allow_null=True)


class ClaimCreateSerializer(serializers.Serializer):
    amount = MoneySerializerField()
    category = serializers.IntegerField()
    spent_on = serializers.DateField()
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    paid_from = serializers.ChoiceField(Claim.PaidFrom.choices)
    receipts = serializers.ListField(
        child=serializers.FileField(), required=False, max_length=5, allow_empty=True
    )


class ClaimCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    parent_id = serializers.IntegerField(allow_null=True)
    icon = serializers.CharField()
    color = serializers.CharField()


class HeldAccountSerializer(serializers.Serializer):
    account_id = serializers.IntegerField()
    name = serializers.CharField()
    balance = serializers.CharField()
    currency = serializers.CharField()


class WalletSerializer(serializers.Serializer):
    currency = serializers.CharField()
    held = HeldAccountSerializer(many=True)
    held_total = serializers.CharField()
    owed_to_me = serializers.CharField()
    approval_threshold = serializers.CharField(allow_null=True)
    receipt_required_over = serializers.CharField(allow_null=True)
