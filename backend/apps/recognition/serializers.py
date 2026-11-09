"""Shapes of the recognition endpoints (employee and owner), for the schema and the clients.

Names are snake_case JSON, times ISO in UTC (the clients show them in the company's zone).
`Meta.ref_name` keeps every schema name under the app's prefix.
"""

from rest_framework import serializers

from apps.recognition import rules
from apps.recognition.badges import TIERS
from apps.recognition.models import Kudos, PointsEntry, RecognitionSettings
from apps.recognition.queries import PERIODS

TIER_CHOICES = [(tier, tier) for tier in TIERS]
UNSEEN_TYPES = [("level", "level"), ("badge", "badge")]
BOXES = [("received", "received"), ("given", "given")]
SCOPES = RecognitionSettings.Scope.choices
PERIOD_CHOICES = [(period, period) for period in PERIODS]
KINDS = [("all", "all"), ("learning", "learning")]


class PersonSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)
    position = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "RecognitionPerson"


class LevelSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    name = serializers.CharField()
    starts_at = serializers.IntegerField()
    next_at = serializers.IntegerField(allow_null=True)
    next_name = serializers.CharField(
        allow_null=True, required=False, help_text="The next level's name (None at the top)."
    )

    class Meta:
        ref_name = "RecognitionLevel"


class LevelRefSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "RecognitionLevelRef"


class BadgeSerializer(serializers.Serializer):
    key = serializers.CharField()
    ref = serializers.CharField(help_text="The topic id or the month (YYYY-MM), else empty.")
    name = serializers.CharField()
    description = serializers.CharField()
    icon = serializers.CharField(help_text="A lucide icon name.")
    tier = serializers.ChoiceField(choices=TIER_CHOICES)
    awarded_at = serializers.DateTimeField()

    class Meta:
        ref_name = "RecognitionBadge"


class CatalogueBadgeSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(help_text="How to earn it.")
    icon = serializers.CharField()
    tier = serializers.ChoiceField(choices=TIER_CHOICES)

    class Meta:
        ref_name = "RecognitionCatalogueBadge"


class HistorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    points = serializers.IntegerField()
    reason = serializers.ChoiceField(choices=PointsEntry.Reason.choices)
    label = serializers.CharField()
    detail = serializers.CharField(help_text="What it was for: a title, a name, a note.")
    at = serializers.DateTimeField()

    class Meta:
        ref_name = "RecognitionHistory"


class UnseenSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=UNSEEN_TYPES)
    name = serializers.CharField()
    number = serializers.IntegerField(required=False, help_text="Levels.")
    starts_at = serializers.IntegerField(required=False)
    next_at = serializers.IntegerField(required=False, allow_null=True)
    key = serializers.CharField(required=False, help_text="Badges.")
    ref = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    icon = serializers.CharField(required=False)
    tier = serializers.ChoiceField(choices=TIER_CHOICES, required=False)
    awarded_at = serializers.DateTimeField(required=False)

    class Meta:
        ref_name = "RecognitionUnseen"


class TaskRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()

    class Meta:
        ref_name = "RecognitionTaskRef"


class KudosSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    # "from" is a Python keyword: declared through the class namespace (a DRF idiom).
    locals()["from"] = PersonSerializer()
    to = PersonSerializer()
    badge = serializers.ChoiceField(choices=Kudos.Badge.choices)
    badge_label = serializers.CharField()
    message = serializers.CharField()
    task = TaskRefSerializer(allow_null=True)
    at = serializers.DateTimeField()
    seen = serializers.BooleanField()
    mine = serializers.BooleanField(help_text="The viewer sent it.")

    class Meta:
        ref_name = "RecognitionKudos"


class MeSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Points are on in this company.")
    points = serializers.IntegerField()
    week_points = serializers.IntegerField()
    level = LevelSerializer()
    streak = serializers.IntegerField()
    best_streak = serializers.IntegerField()
    badges = BadgeSerializer(many=True)
    locked = CatalogueBadgeSerializer(many=True)
    recent = HistorySerializer(many=True)
    unseen = UnseenSerializer(many=True)
    kudos_enabled = serializers.BooleanField()
    kudos_left = serializers.IntegerField()
    kudos_today = KudosSerializer(many=True)
    leaderboard = serializers.BooleanField(help_text="The person may open the leaderboard.")

    class Meta:
        ref_name = "RecognitionMe"


class SeenSerializer(serializers.Serializer):
    kudos = serializers.BooleanField(
        required=False, default=False, help_text="Also mark the thanks received as seen."
    )

    class Meta:
        ref_name = "RecognitionSeen"


class BoardRowSerializer(serializers.Serializer):
    place = serializers.IntegerField()
    member = PersonSerializer()
    points = serializers.IntegerField()
    level = LevelRefSerializer()

    class Meta:
        ref_name = "RecognitionBoardRow"


class MyPlaceSerializer(serializers.Serializer):
    place = serializers.IntegerField(allow_null=True)
    points = serializers.IntegerField()

    class Meta:
        ref_name = "RecognitionMyPlace"


class StaffBoardSerializer(serializers.Serializer):
    visible = serializers.BooleanField()
    period = serializers.ChoiceField(choices=PERIOD_CHOICES)
    scope = serializers.ChoiceField(choices=SCOPES)
    start = serializers.DateTimeField(allow_null=True)
    end = serializers.DateTimeField(allow_null=True)
    rows = BoardRowSerializer(many=True)
    me = MyPlaceSerializer()

    class Meta:
        ref_name = "RecognitionStaffBoard"


class SendKudosSerializer(serializers.Serializer):
    to = serializers.IntegerField()
    badge = serializers.ChoiceField(choices=Kudos.Badge.choices, default=Kudos.Badge.THANKS)
    message = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    task = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        ref_name = "RecognitionSendKudos"


class ColleagueSerializer(PersonSerializer):
    branch = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "RecognitionColleague"


class ColleaguesSerializer(serializers.Serializer):
    per_day = serializers.IntegerField()
    left = serializers.IntegerField(help_text="How many more the person may thank today.")
    results = ColleagueSerializer(many=True)

    class Meta:
        ref_name = "RecognitionColleagues"


# Owner ---------------------------------------------------------------------------------------


class OwnerBoardRowSerializer(BoardRowSerializer):
    badges = serializers.IntegerField()
    streak = serializers.IntegerField()

    class Meta:
        ref_name = "RecognitionOwnerBoardRow"


class OwnerBoardSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=PERIOD_CHOICES)
    kind = serializers.ChoiceField(choices=KINDS)
    start = serializers.DateTimeField(allow_null=True)
    end = serializers.DateTimeField(allow_null=True)
    rows = OwnerBoardRowSerializer(many=True)

    class Meta:
        ref_name = "RecognitionOwnerBoard"


class ProfileSerializer(serializers.Serializer):
    member = PersonSerializer()
    points = serializers.IntegerField()
    week_points = serializers.IntegerField()
    month_points = serializers.IntegerField()
    level = LevelSerializer()
    streak = serializers.IntegerField()
    best_streak = serializers.IntegerField()
    badges = BadgeSerializer(many=True)
    history = HistorySerializer(many=True)
    kudos_received = serializers.IntegerField()
    kudos_given = serializers.IntegerField()

    class Meta:
        ref_name = "RecognitionProfile"


class AdjustSerializer(serializers.Serializer):
    points = serializers.IntegerField(min_value=-rules.MAX_ADJUST, max_value=rules.MAX_ADJUST)
    note = serializers.CharField(max_length=200)

    class Meta:
        ref_name = "RecognitionAdjust"


class HolderSerializer(serializers.Serializer):
    member = PersonSerializer()
    ref = serializers.CharField()
    name = serializers.CharField(help_text="The badge's name for this award (topic, month).")
    awarded_at = serializers.DateTimeField()

    class Meta:
        ref_name = "RecognitionHolder"


class CatalogueEntrySerializer(CatalogueBadgeSerializer):
    holders = HolderSerializer(many=True)
    count = serializers.IntegerField()

    class Meta:
        ref_name = "RecognitionCatalogueEntry"


class PointRowSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    default = serializers.IntegerField()
    points = serializers.IntegerField()

    class Meta:
        ref_name = "RecognitionPointRow"


class SettingsSerializer(serializers.ModelSerializer):
    points_table = serializers.DictField(
        child=serializers.IntegerField(min_value=0, max_value=rules.MAX_POINTS),
        required=False,
        help_text="Only the rows that differ from the defaults.",
    )
    points = PointRowSerializer(many=True, read_only=True)
    levels = LevelSerializer(many=True, read_only=True)

    class Meta:
        model = RecognitionSettings
        ref_name = "RecognitionSettings"
        fields = (
            "points_enabled",
            "leaderboard_for_staff",
            "leaderboard_scope",
            "task_points",
            "kudos_enabled",
            "kudos_per_day",
            "post_kudos_to_groups",
            "points_table",
            "points",
            "levels",
        )
        extra_kwargs = {"kudos_per_day": {"min_value": 1, "max_value": 20}}
