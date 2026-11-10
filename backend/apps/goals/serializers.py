"""Serializers of the business goals endpoints: values and targets go out as strings, days as
ISO dates."""

from rest_framework import serializers

from apps.goals.metrics import METRICS
from apps.goals.models import Goal, Metric


def number(**kwargs):
    return serializers.DecimalField(
        max_digits=18, decimal_places=2, coerce_to_string=True, **kwargs
    )


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PointSerializer(serializers.Serializer):
    on = serializers.DateField()
    value = number(allow_null=True)
    forecast = number(allow_null=True)
    state = serializers.ChoiceField(Goal.State.choices)


class GoalSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    metric = serializers.ChoiceField(Metric.choices)
    unit = serializers.ChoiceField(["money", "percent", "count"])
    better = serializers.ChoiceField(["up", "down"])
    kind = serializers.ChoiceField(["sum", "rate", "ratio", "level"])
    target = number()
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    branch = RefSerializer(allow_null=True)
    owner = RefSerializer(allow_null=True)
    note = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(Goal.Status.choices)
    state = serializers.ChoiceField(Goal.State.choices)
    value = number(allow_null=True)
    forecast = number(allow_null=True)
    baseline = number(allow_null=True)
    progress = serializers.DecimalField(
        max_digits=7, decimal_places=1, coerce_to_string=True, allow_null=True
    )
    days_left = serializers.IntegerField()
    time_share = serializers.DecimalField(max_digits=6, decimal_places=4, coerce_to_string=True)
    available = serializers.BooleanField()
    series = PointSerializer(many=True)
    can_edit = serializers.BooleanField()


class GoalListSerializer(serializers.Serializer):
    today = serializers.DateField()
    currency = serializers.CharField()
    can_manage = serializers.BooleanField()
    goals = GoalSerializer(many=True)
    counts = serializers.DictField(child=serializers.IntegerField())


class MetricSerializer(serializers.Serializer):
    key = serializers.ChoiceField(Metric.choices)
    label = serializers.CharField()
    hint = serializers.CharField()
    unit = serializers.ChoiceField(["money", "percent", "count"])
    better = serializers.ChoiceField(["up", "down"])
    kind = serializers.ChoiceField(["sum", "rate", "ratio", "level"])
    branchable = serializers.BooleanField()
    available = serializers.BooleanField()
    feature = serializers.CharField(allow_null=True)


class MetricsSerializer(serializers.Serializer):
    metrics = MetricSerializer(many=True)
    branches = RefSerializer(many=True)
    people = RefSerializer(many=True)
    company_wide = serializers.BooleanField(help_text="May set goals for the whole company.")


class PreviewSerializer(serializers.Serializer):
    metric = serializers.ChoiceField(Metric.choices)
    state = serializers.ChoiceField(Goal.State.choices, allow_null=True)
    value = number(allow_null=True)
    forecast = number(allow_null=True)
    baseline = number(allow_null=True)
    progress = serializers.DecimalField(
        max_digits=7, decimal_places=1, coerce_to_string=True, allow_null=True
    )
    days_left = serializers.IntegerField()


class GoalInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    metric = serializers.ChoiceField(Metric.choices)
    target = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField()
    branch = serializers.IntegerField(required=False, allow_null=True)
    owner = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_metric(self, value):
        if value not in METRICS:
            raise serializers.ValidationError("Unknown metric.")
        return value


class GoalPatchSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    target = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0, required=False)
    starts_on = serializers.DateField(required=False)
    ends_on = serializers.DateField(required=False)
    owner = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
