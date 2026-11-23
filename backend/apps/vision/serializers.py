"""Serializers of Ko‘z's owner endpoints (`owner_api.py`, docs/KOZ.md §6): what the requests may
carry, and the answers' shapes for the schema (`apps.vision.queries` and `analytics` build the
answers themselves). What a box sends is in `device_serializers.py`."""

from rest_framework import serializers

from apps.vision import zones
from apps.vision.insights import Kind as InsightKind
from apps.vision.insights import Severity
from apps.vision.models import Alert, Camera, Clip, VisionSettings

# Answers -------------------------------------------------------------------------------------


class VisionRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class VisionZoneSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(list(zones.KINDS))
    points = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2)
    )

    def get_fields(self):
        fields = super().get_fields()
        # "in" (the inside of an entrance line) is a Python keyword: added here.
        fields["in"] = serializers.ChoiceField(list(zones.SIDES), required=False)
        return fields


class VisionCameraSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    key = serializers.CharField()
    name = serializers.CharField()
    role = serializers.ChoiceField(Camera.Role.choices)
    enabled = serializers.BooleanField()
    branch = VisionRefSerializer()
    agent_id = serializers.IntegerField()
    source = serializers.ChoiceField(Camera.Source.choices, allow_null=True)
    channel = serializers.IntegerField(allow_null=True)
    w = serializers.IntegerField(allow_null=True)
    h = serializers.IntegerField(allow_null=True)
    online = serializers.BooleanField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    zones = VisionZoneSerializer(many=True)
    register = VisionRefSerializer(allow_null=True)
    snapshot_url = serializers.CharField(allow_null=True, help_text="Signed link, 10 minutes.")
    snapshot_at = serializers.DateTimeField(allow_null=True)


class VisionHostSerializer(serializers.Serializer):
    hostname = serializers.CharField()
    os = serializers.CharField()


class VisionAgentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    branch = VisionRefSerializer()
    online = serializers.BooleanField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    version = serializers.CharField(allow_null=True)
    host = VisionHostSerializer(allow_null=True)
    paired = serializers.BooleanField()
    cameras = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class VisionPairingSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Shown once: KOZ-XXXX-XXXX, valid 15 minutes.")
    expires_at = serializers.DateTimeField()
    command = serializers.CharField(help_text="The line to run on the box's PC.")


class VisionAgentCreatedSerializer(serializers.Serializer):
    agent = VisionAgentSerializer()
    pairing = VisionPairingSerializer()


class VisionClipStateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(Clip.State.choices)


class VisionAlertSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(Alert.Kind.choices)
    state = serializers.ChoiceField(Alert.State.choices)
    branch = VisionRefSerializer()
    camera = VisionRefSerializer(allow_null=True)
    started_at = serializers.DateTimeField()
    resolved_at = serializers.DateTimeField(allow_null=True)
    duration_s = serializers.IntegerField(allow_null=True)
    peak_queue = serializers.IntegerField()
    peak_wait_s = serializers.IntegerField()
    acknowledged_by = VisionRefSerializer(allow_null=True)
    acknowledged_at = serializers.DateTimeField(allow_null=True)
    photo_url = serializers.CharField(allow_null=True, help_text="Signed link, 10 minutes.")
    clip = VisionClipStateSerializer(allow_null=True)


class VisionClipSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    state = serializers.ChoiceField(Clip.State.choices)
    reason = serializers.ChoiceField(Clip.Reason.choices)
    camera = VisionRefSerializer()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    sale_id = serializers.IntegerField(allow_null=True)
    alert_id = serializers.IntegerField(allow_null=True)
    video_url = serializers.CharField(allow_null=True)
    poster_url = serializers.CharField(allow_null=True)
    duration_s = serializers.FloatField(allow_null=True)
    failure = serializers.ChoiceField(Clip.Failure.choices, allow_null=True)
    failure_text = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


class VisionSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisionSettings
        fields = (
            "queue_people",
            "queue_wait_s",
            "unattended_s",
            "clear_after_s",
            "cooldown_s",
            "analysis_fps",
            "live_fps",
            "privacy_blur",
            "alert_photo",
            "record_counter",
            "record_hours",
            "notify_on_shift",
            "notify_managers",
            "stats_keep_days",
            "photos_keep_days",
            "clips_keep_days",
        )


class VisionSetupSerializer(serializers.Serializer):
    agents = serializers.IntegerField()
    cameras = serializers.IntegerField(help_text="Cameras switched on.")
    entrance = serializers.BooleanField()
    counter = serializers.BooleanField()


class VisionAgentBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    branch_id = serializers.IntegerField()
    online = serializers.BooleanField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
    version = serializers.CharField(allow_null=True)


class VisionCompareSerializer(serializers.Serializer):
    visitors = serializers.IntegerField(allow_null=True)
    receipts = serializers.IntegerField(allow_null=True)
    conversion = serializers.FloatField(allow_null=True)
    label = serializers.ChoiceField(["same_weekday_last_week"])


class VisionTotalsSerializer(serializers.Serializer):
    visitors = serializers.IntegerField(allow_null=True)
    receipts = serializers.IntegerField(allow_null=True)
    conversion = serializers.FloatField(allow_null=True)
    conversion_note = serializers.ChoiceField(["entrance_undercount"], allow_null=True)
    left = serializers.IntegerField(allow_null=True)
    wait_avg_s = serializers.IntegerField(allow_null=True)
    wait_max_s = serializers.IntegerField()
    alerts = serializers.IntegerField()
    unattended_minutes = serializers.IntegerField()
    compare = VisionCompareSerializer()


class VisionHourSerializer(serializers.Serializer):
    hour = serializers.IntegerField(min_value=0, max_value=23)
    visitors = serializers.IntegerField(allow_null=True)
    receipts = serializers.IntegerField(allow_null=True)
    queue_max = serializers.IntegerField()
    wait_max_s = serializers.IntegerField()
    staff_avg = serializers.FloatField(allow_null=True)
    staff_checked_in = serializers.IntegerField(allow_null=True)
    unattended_minutes = serializers.IntegerField()


class VisionInsightSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(InsightKind.choices)
    severity = serializers.ChoiceField(Severity.choices)
    hour = serializers.IntegerField(allow_null=True)
    text = serializers.CharField()


class VisionOverviewSerializer(serializers.Serializer):
    day = serializers.DateField()
    branch = VisionRefSerializer(allow_null=True)
    setup = VisionSetupSerializer()
    agents = VisionAgentBriefSerializer(many=True)
    totals = VisionTotalsSerializer()
    hours = VisionHourSerializer(many=True)
    insights = VisionInsightSerializer(many=True)
    open_alerts = VisionAlertSerializer(many=True)


class VisionTodaySerializer(serializers.Serializer):
    visitors = serializers.IntegerField(allow_null=True)
    receipts = serializers.IntegerField(allow_null=True)


class VisionLiveCameraSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    role = serializers.ChoiceField(Camera.Role.choices)
    branch_id = serializers.IntegerField()
    online = serializers.BooleanField()
    stale = serializers.BooleanField(help_text="No live report for 30 s.")
    people = serializers.IntegerField(allow_null=True)
    queue = serializers.IntegerField(allow_null=True)
    staff = serializers.IntegerField(allow_null=True)
    wait_s = serializers.IntegerField(allow_null=True)
    fps = serializers.FloatField(allow_null=True)


class VisionLiveSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    today = VisionTodaySerializer()
    cameras = VisionLiveCameraSerializer(many=True)
    open_alerts = VisionAlertSerializer(many=True)


class VisionPersonSerializer(serializers.Serializer):
    track = serializers.IntegerField()
    box = serializers.ListField(child=serializers.FloatField(), min_length=4, max_length=4)
    role = serializers.ChoiceField(["staff", "customer"])
    zone = serializers.CharField(allow_null=True)
    wait_s = serializers.IntegerField(allow_null=True)


class VisionFrameSerializer(serializers.Serializer):
    at = serializers.CharField()
    w = serializers.IntegerField()
    h = serializers.IntegerField()
    people = VisionPersonSerializer(many=True)
    image_b64 = serializers.CharField(help_text="The JPEG, base64.")


class VisionSnapshotRequestedSerializer(serializers.Serializer):
    snapshot_requested_at = serializers.DateTimeField()


class VisionReviewItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(["void", "payout"])
    at = serializers.DateTimeField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, coerce_to_string=True)
    sale_id = serializers.IntegerField(allow_null=True)
    cash_movement_id = serializers.IntegerField(allow_null=True)
    cashier = VisionRefSerializer(allow_null=True)
    camera = VisionRefSerializer(allow_null=True)
    queue_max = serializers.IntegerField()
    clip = VisionClipStateSerializer(allow_null=True)


class VisionReviewSerializer(serializers.Serializer):
    items = VisionReviewItemSerializer(many=True)


# Requests ------------------------------------------------------------------------------------


class VisionCameraWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    role = serializers.ChoiceField(Camera.Role.choices, required=False)
    enabled = serializers.BooleanField(required=False)
    zones = serializers.JSONField(required=False, help_text="Up to 8 zones (docs/KOZ.md §4).")
    register_id = serializers.IntegerField(required=False, allow_null=True)


class VisionAgentWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    branch_id = serializers.IntegerField()


class VisionClipRequestSerializer(serializers.Serializer):
    """`{sale_id}`, or `{camera_id, at, before_s, after_s}` (60 s at most in all)."""

    sale_id = serializers.IntegerField(required=False)
    camera_id = serializers.IntegerField(required=False)
    at = serializers.DateTimeField(required=False)
    before_s = serializers.IntegerField(min_value=0, max_value=60, required=False, default=10)
    after_s = serializers.IntegerField(min_value=0, max_value=60, required=False, default=5)

    def validate(self, data):
        from django.utils.translation import gettext as _

        if data.get("sale_id") is None and (
            data.get("camera_id") is None or data.get("at") is None
        ):
            raise serializers.ValidationError(_("Pick a sale, or a camera and a moment."))
        if data.get("sale_id") is None:
            total = data["before_s"] + data["after_s"]
            if total <= 0 or total > 60:
                raise serializers.ValidationError(_("A clip is 1 to 60 seconds long."))
        return data


class VisionSettingsWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisionSettings
        fields = VisionSettingsSerializer.Meta.fields
