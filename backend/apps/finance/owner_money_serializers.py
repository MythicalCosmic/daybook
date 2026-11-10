"""Serializers of the owner's money endpoints (v11): the safe amount to take out with its
reasons, draws and contributions, planned purchases, partners and dividends. Money goes out as
strings, days as ISO dates; inputs are validated here and the rules live in the services."""

from rest_framework import serializers

from apps.core.money import MoneySerializerField
from apps.finance import partners as partners_service
from apps.finance.models import Dividend, DividendLine, Partner, PlannedPurchase


def money_out(**kwargs):
    return serializers.DecimalField(
        max_digits=18, decimal_places=2, coerce_to_string=True, **kwargs
    )


# The safe amount ----------------------------------------------------------------------------


class ReasonSerializer(serializers.Serializer):
    key = serializers.CharField()
    kind = serializers.ChoiceField(
        ["bill", "auto", "tax", "payable", "payroll", "loan", "installment"]
    )
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    date = serializers.DateField()
    amount = money_out(allow_null=True)
    count = serializers.IntegerField()
    overdue = serializers.BooleanField()
    estimate = serializers.BooleanField()
    url = serializers.CharField(allow_blank=True)


class BufferSerializer(serializers.Serializer):
    amount = money_out()
    auto = serializers.BooleanField()
    fixed_costs = money_out()


class PurchaseSerializer(serializers.ModelSerializer):
    amount = money_out()
    branch = serializers.SerializerMethodField()
    done = serializers.SerializerMethodField()

    class Meta:
        model = PlannedPurchase
        ref_name = "FinancePlannedPurchase"
        fields = ("id", "title", "amount", "due_on", "branch", "done")

    def get_branch(self, row) -> dict | None:
        return {"id": row.branch_id, "name": row.branch.name} if row.branch_id else None

    def get_done(self, row) -> bool:
        return row.done_at is not None


class PurchasesSerializer(serializers.Serializer):
    kept = PurchaseSerializer(many=True)
    later = PurchaseSerializer(many=True)


class FlowAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()


class FlowRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    occurred_on = serializers.DateField()
    direction = serializers.ChoiceField(["in", "out"])
    amount = money_out()
    currency = serializers.CharField()
    base_amount = money_out()
    account = FlowAccountSerializer()
    description = serializers.CharField(allow_blank=True)
    person = serializers.CharField(allow_null=True)
    dividend = serializers.BooleanField()
    created_by = serializers.CharField(allow_null=True)


class FlowsSerializer(serializers.Serializer):
    locals()["from"] = serializers.DateField()
    to = serializers.DateField()
    drawn = money_out()
    put_in = money_out()
    net = money_out()
    count = serializers.IntegerField()
    rows = FlowRowSerializer(many=True)


class LowPointSerializer(serializers.Serializer):
    date = serializers.DateField(allow_null=True)
    balance = money_out()


class SuggestionSerializer(serializers.Serializer):
    today = serializers.DateField()
    currency = serializers.CharField()
    days = serializers.IntegerField()
    monthly = money_out()
    dates = serializers.ListField(child=serializers.DateField())
    buffer = money_out()
    low = LowPointSerializer()
    below_buffer_on = serializers.DateField(allow_null=True)
    profit_average = money_out(help_text="Net profit per month over the last 3 full months.")
    above_profit = serializers.BooleanField(help_text="The monthly amount is more than that.")
    basis = serializers.DictField()


class MonthSerializer(serializers.Serializer):
    month = serializers.DateField()
    profit = money_out()
    drawn = money_out()
    put_in = money_out()


class DrawAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    currency = serializers.CharField()
    balance = money_out()
    branch_id = serializers.IntegerField(allow_null=True)


class OwnerMoneySettingsSerializer(serializers.Serializer):
    cash_buffer = money_out(allow_null=True)
    draw_horizon_days = serializers.IntegerField()


class OwnerMoneySerializer(serializers.Serializer):
    """The owner's money page in one call."""

    today = serializers.DateField()
    currency = serializers.CharField()
    horizon_days = serializers.IntegerField()
    until = serializers.DateField()
    cash = money_out()
    personal = money_out()
    complete = serializers.BooleanField()
    due = money_out()
    reasons = ReasonSerializer(many=True)
    unknown = serializers.IntegerField()
    buffer = BufferSerializer()
    planned = money_out()
    purchases = PurchasesSerializer()
    safe = money_out()
    short = money_out()
    month = FlowsSerializer()
    suggestion = SuggestionSerializer()
    history = MonthSerializer(many=True)
    accounts = DrawAccountSerializer(many=True)
    settings = OwnerMoneySettingsSerializer()
    partners = serializers.IntegerField(help_text="How many partners there are now.")
    is_owner = serializers.BooleanField()


class MoveInputSerializer(serializers.Serializer):
    account = serializers.IntegerField()
    amount = MoneySerializerField()
    occurred_on = serializers.DateField(required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=300)
    confirmed = serializers.BooleanField(required=False, default=False)


class MoveResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    occurred_on = serializers.DateField()
    amount = money_out()
    account = serializers.IntegerField()
    safe = money_out()


class SettingsInputSerializer(serializers.Serializer):
    cash_buffer = MoneySerializerField(positive=False, required=False, allow_null=True)
    draw_horizon_days = serializers.IntegerField(required=False, min_value=7, max_value=90)


class PurchaseInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    amount = MoneySerializerField()
    due_on = serializers.DateField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)


class PurchasePatchSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    amount = MoneySerializerField(required=False)
    due_on = serializers.DateField(required=False, allow_null=True)
    branch = serializers.IntegerField(required=False, allow_null=True)
    done = serializers.BooleanField(required=False)


# Partners ----------------------------------------------------------------------------------------


class PersonRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PartnerSerializer(serializers.ModelSerializer):
    share = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    member = serializers.SerializerMethodField()
    key = serializers.SerializerMethodField()

    class Meta:
        model = Partner
        ref_name = "FinancePartner"
        fields = ("id", "key", "name", "member", "share", "starts_on", "ends_on")

    def get_member(self, row) -> dict | None:
        if row.membership_id is None:
            return None
        return {"id": row.membership_id, "name": str(row.membership)}

    def get_key(self, row) -> str:
        return partners_service.identity(row)


class PartnersSerializer(serializers.Serializer):
    current = PartnerSerializer(many=True)
    history = PartnerSerializer(many=True)
    since = serializers.DateField(allow_null=True)
    people = PersonRefSerializer(many=True)


class PartnerRowInputSerializer(serializers.Serializer):
    member = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    share = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100)


class PartnersInputSerializer(serializers.Serializer):
    effective_on = serializers.DateField()
    partners = PartnerRowInputSerializer(many=True)


class ProfitSharePartnerSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    membership_id = serializers.IntegerField(allow_null=True)
    share = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    profit = money_out()
    dividends_paid = money_out()
    dividends_due = money_out()


class ProfitShareSerializer(serializers.Serializer):
    locals()["from"] = serializers.DateField()
    to = serializers.DateField()
    currency = serializers.CharField()
    profit = money_out()
    partners = ProfitSharePartnerSerializer(many=True)
    unassigned_share = serializers.DecimalField(
        max_digits=5, decimal_places=2, coerce_to_string=True
    )


# Dividends -----------------------------------------------------------------------------------


class DividendLineSerializer(serializers.ModelSerializer):
    partner = serializers.SerializerMethodField()
    share = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    amount = money_out()
    paid = serializers.SerializerMethodField()
    account = serializers.SerializerMethodField()
    transaction_id = serializers.SerializerMethodField()

    class Meta:
        model = DividendLine
        ref_name = "FinanceDividendLine"
        fields = (
            "id",
            "partner",
            "share",
            "amount",
            "paid",
            "paid_on",
            "account",
            "transaction_id",
        )

    def get_partner(self, line) -> dict:
        partner = line.partner
        return {
            "id": partner.pk,
            "name": partner.name,
            "member_id": partner.membership_id,
        }

    def get_paid(self, line) -> bool:
        return line.is_paid

    def get_account(self, line) -> dict | None:
        if not line.is_paid:
            return None
        account = line.transaction.account
        return {"id": account.pk, "name": account.name} if account else None

    def get_transaction_id(self, line) -> int | None:
        return line.transaction_id if line.is_paid else None


class DividendSerializer(serializers.ModelSerializer):
    amount = money_out()
    profit = money_out(allow_null=True)
    status = serializers.SerializerMethodField()
    lines = DividendLineSerializer(many=True, read_only=True)
    paid_amount = serializers.SerializerMethodField()

    class Meta:
        model = Dividend
        ref_name = "FinanceDividend"
        fields = (
            "id",
            "period_start",
            "period_end",
            "amount",
            "profit",
            "status",
            "note",
            "paid_amount",
            "paid_at",
            "created_at",
            "lines",
        )

    def get_status(self, dividend) -> str:
        return partners_service.state(dividend)

    def get_paid_amount(self, dividend) -> str:
        total = sum((line.amount for line in dividend.lines.all() if line.is_paid), 0)
        return f"{total:.2f}"


class SplitRowSerializer(serializers.Serializer):
    partner_id = serializers.IntegerField()
    name = serializers.CharField()
    share = serializers.DecimalField(max_digits=5, decimal_places=2, coerce_to_string=True)
    amount = money_out()


class SuggestSerializer(serializers.Serializer):
    locals()["from"] = serializers.DateField()
    to = serializers.DateField()
    currency = serializers.CharField()
    profit = money_out()
    already = money_out()
    safe = money_out()
    amount = money_out()
    limited_by = serializers.ChoiceField(["safe", "profit"])
    split = SplitRowSerializer(many=True)


class DividendInputSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    amount = MoneySerializerField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class DividendPatchSerializer(serializers.Serializer):
    amount = MoneySerializerField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class DividendPayInputSerializer(serializers.Serializer):
    account = serializers.IntegerField()
    paid_on = serializers.DateField(required=False)
    lines = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=False
    )


class ReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


__all__ = [
    "DividendSerializer",
    "OwnerMoneySerializer",
    "PartnersSerializer",
    "ProfitShareSerializer",
    "SuggestSerializer",
]
