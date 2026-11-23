"""What a Ko‘z box may send (docs/KOZ.md §5): each request body is checked here before
`apps.vision.services` stores anything. Times are ISO 8601 (UTC with Z); camera keys match
`^[a-z0-9:_-]{1,64}$`; coordinates are 0..1 of the frame."""

from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.vision.models import Camera, Clip

KEY_PATTERN = r"^[a-z0-9:_-]{1,64}$"
MAX_STAT_ROWS = 2000
MANY = 1000  # people in a frame, a queue, at a counter: a ceiling, not a rule


def key_field(**kwargs) -> serializers.RegexField:
    return serializers.RegexField(KEY_PATTERN, max_length=64, **kwargs)


def count(**kwargs) -> serializers.IntegerField:
    kwargs.setdefault("required", False)
    kwargs.setdefault("default", 0)
    return serializers.IntegerField(min_value=0, max_value=MANY, **kwargs)


def seconds(**kwargs) -> serializers.IntegerField:
    kwargs.setdefault("required", False)
    kwargs.setdefault("default", 0)
    return serializers.IntegerField(min_value=0, max_value=86400, **kwargs)


class HostSerializer(serializers.Serializer):
    hostname = serializers.CharField(max_length=100, required=False, allow_blank=True)
    os = serializers.CharField(max_length=100, required=False, allow_blank=True)
    version = serializers.CharField(max_length=32, required=False, allow_blank=True)


class PairSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)
    host = HostSerializer(required=False)


class InventoryCameraSerializer(serializers.Serializer):
    key = key_field()
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    source = serializers.ChoiceField(Camera.Source.choices, required=False, allow_blank=True)
    channel = serializers.IntegerField(min_value=0, max_value=4096, required=False, allow_null=True)
    w = serializers.IntegerField(min_value=1, max_value=16384, required=False, allow_null=True)
    h = serializers.IntegerField(min_value=1, max_value=16384, required=False, allow_null=True)
    online = serializers.BooleanField(required=False, default=True)


class InventorySerializer(serializers.Serializer):
    cameras = serializers.ListField(child=InventoryCameraSerializer(), max_length=256)

    def validate_cameras(self, rows):
        keys = [row["key"] for row in rows]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError(_("Send each camera once."))
        return rows


class LiveAgentSerializer(serializers.Serializer):
    version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    fps = serializers.FloatField(min_value=0, max_value=10000, required=False, allow_null=True)
    cpu = serializers.FloatField(min_value=0, max_value=10000, required=False, allow_null=True)


class LiveCameraSerializer(serializers.Serializer):
    key = key_field()
    online = serializers.BooleanField(required=False, default=True)
    fps = serializers.FloatField(min_value=0, max_value=1000, required=False, allow_null=True)
    people = count(allow_null=True)
    queue = count(allow_null=True)
    staff = count(allow_null=True)
    wait_s = seconds(allow_null=True)
    error = serializers.CharField(
        max_length=200, required=False, allow_null=True, allow_blank=True, default=None
    )


class LiveSerializer(serializers.Serializer):
    at = serializers.DateTimeField(required=False)
    agent = LiveAgentSerializer(required=False)
    cameras = serializers.ListField(
        child=LiveCameraSerializer(), max_length=256, required=False, default=list
    )


class PersonSerializer(serializers.Serializer):
    track = serializers.IntegerField(min_value=0, max_value=2**31 - 1)
    box = serializers.ListField(
        child=serializers.FloatField(min_value=0, max_value=1), min_length=4, max_length=4
    )
    role = serializers.ChoiceField(["staff", "customer"])
    zone = serializers.CharField(max_length=16, required=False, allow_null=True, default=None)
    wait_s = serializers.IntegerField(
        min_value=0, max_value=86400, required=False, allow_null=True, default=None
    )


class FrameMetaSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    w = serializers.IntegerField(min_value=1, max_value=960)
    h = serializers.IntegerField(min_value=1, max_value=2000)
    people = serializers.ListField(
        child=PersonSerializer(), max_length=200, required=False, default=list
    )


class StatRowSerializer(serializers.Serializer):
    key = key_field()
    minute = serializers.DateTimeField()
    frames = serializers.IntegerField(min_value=0, max_value=100000, required=False, default=0)
    people_avg = serializers.FloatField(min_value=0, max_value=MANY, required=False, default=0)
    people_max = count()
    entered = serializers.IntegerField(min_value=0, max_value=100000, required=False, default=0)
    exited = serializers.IntegerField(min_value=0, max_value=100000, required=False, default=0)
    queue_avg = serializers.FloatField(min_value=0, max_value=MANY, required=False, default=0)
    queue_max = count()
    wait_max_s = seconds()
    staff_seconds = serializers.IntegerField(min_value=0, max_value=60, required=False, default=0)


class StatsSerializer(serializers.Serializer):
    minutes = serializers.ListField(child=StatRowSerializer(), max_length=MAX_STAT_ROWS)


class EventSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    incident_id = serializers.UUIDField()
    kind = serializers.ChoiceField(["queue", "unattended"])
    phase = serializers.ChoiceField(["start", "update", "end"])
    key = key_field()
    at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    queue = count()
    wait_s = seconds()
    staff = count()
    peak_queue = count()
    peak_wait_s = seconds()


class ClipMetaSerializer(serializers.Serializer):
    duration_s = serializers.FloatField(min_value=0, max_value=600, required=False, allow_null=True)
    source = serializers.ChoiceField(Clip.Source.choices, required=False, allow_blank=True)
    w = serializers.IntegerField(min_value=1, max_value=16384, required=False, allow_null=True)
    h = serializers.IntegerField(min_value=1, max_value=16384, required=False, allow_null=True)


BOX_FAILURES = [
    Clip.Failure.NOT_RECORDED,
    Clip.Failure.CAMERA_OFFLINE,
    Clip.Failure.NVR_ERROR,
    Clip.Failure.TOO_OLD,
]


class ClipFailureSerializer(serializers.Serializer):
    failed = serializers.ChoiceField([str(failure) for failure in BOX_FAILURES])
    detail = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
