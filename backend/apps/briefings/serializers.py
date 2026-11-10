"""Shapes of the briefings owner endpoints (apps.briefings.owner_api)."""

from rest_framework import serializers

from apps.briefings.models import Briefing, BriefingSettings


class BriefingsPeriodSerializer(serializers.Serializer):
    kind = serializers.CharField()
    start = serializers.DateField()
    end = serializers.DateField()


class BriefingsSectionSerializer(serializers.Serializer):
    key = serializers.ChoiceField(["went_well", "went_wrong"])
    title = serializers.CharField()
    bullets = serializers.ListField(child=serializers.CharField())
    facts = serializers.ListField(
        child=serializers.CharField(), help_text="The signal key each bullet rests on."
    )


class BriefingsActionSerializer(serializers.Serializer):
    text = serializers.CharField(help_text="The suggestion.")
    fact = serializers.CharField(help_text="The signal it is about (a key of facts.signals).")
    label = serializers.CharField(help_text="The button's words.")
    url = serializers.CharField(help_text="A dashboard path, /c/<company>/…")


class BriefingsSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(Briefing.Kind.choices)
    day = serializers.DateField(help_text="The first day of the period it reviews.")
    period = BriefingsPeriodSerializer()
    headline = serializers.CharField(allow_blank=True)
    written_by = serializers.ChoiceField(Briefing.WrittenBy.choices)
    written_at = serializers.DateTimeField(allow_null=True)
    language = serializers.CharField()


class BriefingsReviewSerializer(BriefingsSummarySerializer):
    sections = BriefingsSectionSerializer(many=True)
    actions = BriefingsActionSerializer(many=True, help_text="Up to three suggestions.")
    facts = serializers.DictField(
        help_text=(
            "Every number of the review (apps.briefings.facts): money as strings, the "
            "sections of the domains the reader may see, and `signals`."
        )
    )


class BriefingsListSerializer(serializers.Serializer):
    results = BriefingsSummarySerializer(many=True)


class BriefingsNextSerializer(serializers.Serializer):
    weekly = serializers.DateTimeField(allow_null=True)
    monthly = serializers.DateTimeField(allow_null=True)


class BriefingsLatestSerializer(serializers.Serializer):
    review = BriefingsReviewSerializer(allow_null=True, help_text="Null before the first one.")
    next = BriefingsNextSerializer(help_text="When the next reviews go out (null: off).")
    writer = serializers.ChoiceField(
        ["ai", "template"], help_text="Who writes the reviews now: Claude or the templates."
    )
    advisor_on = serializers.BooleanField(help_text="Maslahatchi works here and is on.")
    chat = serializers.BooleanField(help_text='"Ask the advisor" is open to the caller.')
    has_data = serializers.BooleanField(
        help_text="The caller sees something a review talks about (money, sales, stock, people)."
    )
    can_regenerate = serializers.BooleanField(help_text="company.settings")
    regenerations_left = serializers.IntegerField()
    can_configure = serializers.BooleanField(help_text="company.settings: the review settings.")


class BriefingsQueuedSerializer(serializers.Serializer):
    queued = serializers.BooleanField()


class BriefingsRegenerateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(Briefing.Kind.choices, default=Briefing.Kind.WEEKLY)


class BriefingsSettingsSerializer(serializers.ModelSerializer):
    send_at = serializers.TimeField(format="%H:%M")

    class Meta:
        model = BriefingSettings
        fields = ("weekly_enabled", "monthly_enabled", "weekday", "send_at", "recipients")


class BriefingsConversationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    last_activity_at = serializers.DateTimeField()
