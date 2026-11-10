"""Shapes of the insights and cockpit endpoints (money as strings, days as YYYY-MM-DD)."""

from rest_framework import serializers

from apps.core.money import MoneySerializerField
from apps.insights.models import Insight, InsightSettings

# Insights ------------------------------------------------------------------------------------


class InsightBranchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class InsightSubjectSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.IntegerField(allow_null=True)
    label = serializers.CharField()


class InsightWindowSerializer(serializers.Serializer):
    to = serializers.DateField(allow_null=True)

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = serializers.DateField(allow_null=True)
        return fields


class InsightTaskSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    status = serializers.CharField()


class InsightSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(Insight.Kind.choices)
    domain = serializers.ChoiceField(Insight.Domain.choices)
    severity = serializers.ChoiceField(Insight.Severity.choices)
    status = serializers.ChoiceField(Insight.Status.choices)
    branch = InsightBranchSerializer(allow_null=True)
    subject = InsightSubjectSerializer(allow_null=True)
    title = serializers.CharField()
    explanation = serializers.CharField(allow_blank=True)
    suggested_action = serializers.CharField(allow_blank=True)
    metrics = serializers.DictField(
        help_text="The numbers behind it: value, baseline, threshold, unit, series and the "
        "kind's own (money as strings)."
    )
    window = InsightWindowSerializer()
    detected_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    task = InsightTaskSerializer(allow_null=True)

    class Meta:
        ref_name = "InsightsInsight"


class InsightListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = InsightSerializer(many=True)


class DismissSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)


class MakeTaskSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    due_on = serializers.DateField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True, max_length=200)


class MadeTaskSerializer(serializers.Serializer):
    insight = InsightSerializer()
    task = InsightTaskSerializer()


class InsightSettingsSerializer(serializers.ModelSerializer):
    disabled_kinds = serializers.ListField(
        child=serializers.ChoiceField(Insight.Kind.choices), required=False
    )
    expense_alert_min_amount = MoneySerializerField(required=False)
    quiet_from = serializers.TimeField(format="%H:%M", required=False)
    quiet_to = serializers.TimeField(format="%H:%M", required=False)

    class Meta:
        model = InsightSettings
        ref_name = "InsightsSettings"
        fields = (
            "disabled_kinds",
            "sensitivity",
            "quiet_from",
            "quiet_to",
            "notify_critical_via_bot",
            "expense_alert_min_amount",
        )


class InsightKindSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    domain = serializers.CharField()
    available = serializers.BooleanField(help_text="Its module is on.")


class InsightSettingsResponseSerializer(InsightSettingsSerializer):
    kinds = InsightKindSerializer(many=True, read_only=True)
    last_run_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta(InsightSettingsSerializer.Meta):
        ref_name = "InsightsSettingsResponse"
        fields = (*InsightSettingsSerializer.Meta.fields, "kinds", "last_run_at")


class CheckResultSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    reopened = serializers.IntegerField()
    resolved = serializers.IntegerField()
    failed = serializers.IntegerField()
    notified = serializers.IntegerField()


# The cockpit ---------------------------------------------------------------------------------


class CockpitCanSerializer(serializers.Serializer):
    money = serializers.BooleanField()
    insights = serializers.BooleanField()
    settings = serializers.BooleanField()


class CockpitCostSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    color = serializers.CharField(allow_blank=True, required=False)
    amount = serializers.CharField()
    previous = serializers.CharField(allow_null=True, required=False)


class CockpitMissingSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    last_month = serializers.CharField()


class CockpitPreviousSerializer(serializers.Serializer):
    revenue = serializers.CharField()
    gross = serializers.CharField()
    gross_margin = serializers.CharField(allow_null=True)
    expense = serializers.CharField()
    profit = serializers.CharField()
    margin = serializers.CharField(allow_null=True)


class CockpitPeriodSerializer(serializers.Serializer):
    revenue = serializers.CharField()
    goods = serializers.CharField(help_text="Medicines and goods bought (booked on receipt).")
    gross = serializers.CharField()
    gross_margin = serializers.CharField(allow_null=True)
    expense = serializers.CharField()
    profit = serializers.CharField()
    margin = serializers.CharField(allow_null=True)
    costs = CockpitCostSerializer(many=True)
    previous = CockpitPreviousSerializer(allow_null=True)
    missing = CockpitMissingSerializer(many=True, required=False)


class CockpitTrendSerializer(serializers.Serializer):
    month = serializers.CharField()
    profit = serializers.CharField()


class CockpitFiguresSerializer(serializers.Serializer):
    month = CockpitPeriodSerializer()
    last_month = CockpitPeriodSerializer()
    trend = CockpitTrendSerializer(many=True)


class CockpitStateSerializer(serializers.Serializer):
    state = serializers.ChoiceField(["green", "amber", "red"])
    reasons = serializers.ListField(child=serializers.CharField())


class CockpitStatesSerializer(serializers.Serializer):
    month = CockpitStateSerializer()
    last_month = CockpitStateSerializer()


class CockpitBranchSerializer(CockpitFiguresSerializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField(allow_blank=True)
    states = CockpitStatesSerializer()


class CockpitRangeSerializer(serializers.Serializer):
    to = serializers.DateField()
    previous_from = serializers.DateField()
    previous_to = serializers.DateField()

    def get_fields(self):
        fields = super().get_fields()
        fields["from"] = serializers.DateField()
        return fields


class CockpitPeriodsSerializer(serializers.Serializer):
    month = CockpitRangeSerializer()
    last_month = CockpitRangeSerializer()


class CockpitRestSerializer(serializers.Serializer):
    revenue = serializers.CharField()
    goods = serializers.CharField()
    gross = serializers.CharField()
    expense = serializers.CharField()
    profit = serializers.CharField()
    costs = CockpitCostSerializer(many=True)


class CockpitUnassignedSerializer(serializers.Serializer):
    month = CockpitRestSerializer()
    last_month = CockpitRestSerializer()


class CockpitMoneySerializer(serializers.Serializer):
    periods = CockpitPeriodsSerializer()
    total = CockpitFiguresSerializer()
    branches = CockpitBranchSerializer(many=True)
    unassigned = CockpitUnassignedSerializer(
        allow_null=True, help_text="What is booked on no branch (every-branch callers only)."
    )


class CockpitRunwaySerializer(serializers.Serializer):
    days = serializers.IntegerField(allow_null=True)
    basis = serializers.ChoiceField(["spending", "forecast"])
    below_zero_on = serializers.DateField(allow_null=True)
    horizon = serializers.IntegerField()


class CockpitCauseSerializer(serializers.Serializer):
    title = serializers.CharField()
    kind = serializers.CharField()
    date = serializers.DateField()
    amount = serializers.CharField()
    overdue = serializers.BooleanField()


class CockpitLowSerializer(serializers.Serializer):
    date = serializers.DateField()
    balance = serializers.CharField()
    short_by = serializers.CharField()
    under_buffer_by = serializers.CharField()
    causes = CockpitCauseSerializer(many=True)


class CockpitPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    balance = serializers.CharField()


class CockpitCashSerializer(serializers.Serializer):
    currency = serializers.CharField()
    now = serializers.CharField()
    buffer = serializers.CharField()
    buffer_source = serializers.ChoiceField(["setting", "fixed_costs"])
    daily_spend = serializers.CharField()
    runway = CockpitRunwaySerializer()
    low = CockpitLowSerializer()
    end = serializers.CharField()
    points = CockpitPointSerializer(many=True)
    basis = serializers.DictField()


class CockpitQueueActionSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    style = serializers.CharField()
    method = serializers.CharField()
    endpoint = serializers.CharField(help_text="Relative to /api/v1/owner/companies/{cid}/.")
    body = serializers.DictField()
    needs_reason = serializers.BooleanField()


class CockpitDecisionSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField()
    subtitle = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField(allow_null=True)
    url = serializers.CharField(allow_blank=True)
    actions = CockpitQueueActionSerializer(many=True)
    source = serializers.CharField()
    group = serializers.CharField()


class CockpitSourceSerializer(serializers.Serializer):
    key = serializers.CharField()
    group = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class CockpitDecisionsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    sources = CockpitSourceSerializer(many=True)
    items = CockpitDecisionSerializer(many=True)


class CockpitInsightsSerializer(serializers.Serializer):
    live = serializers.IntegerField()
    open = serializers.IntegerField()
    critical = serializers.IntegerField()
    items = InsightSerializer(many=True)


class CockpitSerializer(serializers.Serializer):
    today = serializers.DateField()
    currency = serializers.CharField()
    generated_at = serializers.DateTimeField()
    can = CockpitCanSerializer()
    money = CockpitMoneySerializer(
        required=False, help_text="Only with finance.view and the finance module."
    )
    cash = CockpitCashSerializer(
        required=False, help_text="Only with finance.view and the finance module."
    )
    decisions = CockpitDecisionsSerializer()
    insights = CockpitInsightsSerializer()
