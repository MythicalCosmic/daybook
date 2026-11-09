"""Serializers of the Face ID owner endpoints (`faceid/…`): inputs are validated here, outputs
are the dicts `owner_api` builds, described for the OpenAPI schema."""

from django.db import models
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.attendance.serializers import BranchRefSerializer, PersonCardSerializer, RefSerializer
from apps.faceid.models import FaceDevice, FaceEvent, FaceIdSettings
from apps.faceid.services import SETTINGS_FIELDS


class DeviceStatus(models.TextChoices):
    ONLINE = "online", _("Online")
    QUIET = "quiet", _("Quiet")
    NEVER = "never", _("Never connected")
    DISABLED = "disabled", _("Switched off")


STATUSES = DeviceStatus.choices


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = "FaceIdSettings"
        model = FaceIdSettings
        fields = SETTINGS_FIELDS


class DeviceInSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    branch_id = serializers.IntegerField()
    direction = serializers.ChoiceField(
        choices=FaceDevice.Direction.choices, default=FaceDevice.Direction.TOGGLE
    )


class DevicePatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    branch_id = serializers.IntegerField(required=False)
    direction = serializers.ChoiceField(choices=FaceDevice.Direction.choices, required=False)
    enabled = serializers.BooleanField(required=False)


class LastScanSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    name = serializers.CharField()
    action = serializers.ChoiceField(choices=FaceEvent.Action.choices)


class DeviceOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    branch = BranchRefSerializer()
    direction = serializers.ChoiceField(choices=FaceDevice.Direction.choices)
    enabled = serializers.BooleanField()
    vendor = serializers.CharField()
    model = serializers.CharField()
    ip = serializers.CharField()
    mac = serializers.CharField()
    status = serializers.ChoiceField(choices=STATUSES)
    last_seen_at = serializers.DateTimeField(allow_null=True)
    last_event_at = serializers.DateTimeField(allow_null=True)
    heartbeats = serializers.BooleanField()
    clock_offset_s = serializers.IntegerField(allow_null=True)
    clock_off = serializers.BooleanField()
    scans_today = serializers.IntegerField()
    hourly = serializers.ListField(child=serializers.IntegerField())
    last_scan = LastScanSerializer(allow_null=True)
    created_at = serializers.DateTimeField()

    class Meta:
        ref_name = "FaceIdDevice"


class ProtocolSerializer(serializers.Serializer):
    port = serializers.IntegerField()
    url = serializers.CharField()

    class Meta:
        ref_name = "FaceIdProtocol"


class SetupSerializer(serializers.Serializer):
    host = serializers.CharField()
    addressing = serializers.ChoiceField(choices=["hostname", "ipaddress"])
    path = serializers.CharField()
    recommended = serializers.ChoiceField(choices=["https", "http"])
    heartbeat_minutes = serializers.IntegerField()
    http = ProtocolSerializer()
    https = ProtocolSerializer()
    last_event_at = serializers.DateTimeField(allow_null=True)
    last_test_at = serializers.DateTimeField(allow_null=True)

    class Meta:
        ref_name = "FaceIdSetup"


class RecordBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    check_in_at = serializers.DateTimeField(allow_null=True)
    check_out_at = serializers.DateTimeField(allow_null=True)
    is_late = serializers.BooleanField()
    late_minutes = serializers.IntegerField()
    worked_minutes = serializers.IntegerField()

    class Meta:
        ref_name = "FaceIdRecordBrief"


class EventOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    event_at = serializers.DateTimeField()
    received_at = serializers.DateTimeField()
    device = RefSerializer()
    branch = BranchRefSerializer()
    kind = serializers.ChoiceField(choices=FaceEvent.Kind.choices)
    action = serializers.ChoiceField(choices=FaceEvent.Action.choices)
    method = serializers.CharField()
    verify_mode = serializers.CharField()
    employee_no = serializers.CharField()
    name_on_device = serializers.CharField()
    member = PersonCardSerializer(allow_null=True)
    record = RecordBriefSerializer(allow_null=True)
    flags = serializers.ListField(child=serializers.ChoiceField(choices=FaceEvent.Flag.choices))
    photo_url = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "FaceIdEvent"


class SuggestionSerializer(serializers.Serializer):
    member = PersonCardSerializer()
    score = serializers.IntegerField(help_text=_("How close the names are, 0 to 100."))
    has_number = serializers.BooleanField()

    class Meta:
        ref_name = "FaceIdSuggestion"


class LinkBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    auto = serializers.BooleanField()
    ignored = serializers.BooleanField()

    class Meta:
        ref_name = "FaceIdLinkBrief"


class PersonRowSerializer(serializers.Serializer):
    employee_no = serializers.CharField()
    name_on_device = serializers.CharField()
    first_at = serializers.DateTimeField()
    last_at = serializers.DateTimeField()
    scans = serializers.IntegerField()
    device = RefSerializer()
    photo_url = serializers.CharField(allow_null=True)
    member = PersonCardSerializer(allow_null=True)
    link = LinkBriefSerializer(allow_null=True)
    suggestions = SuggestionSerializer(many=True)

    class Meta:
        ref_name = "FaceIdPerson"


class NumberSerializer(serializers.Serializer):
    employee_no = serializers.CharField(max_length=32)


class LinkInSerializer(NumberSerializer):
    member_id = serializers.IntegerField()


class LinkOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    employee_no = serializers.CharField()
    member = PersonCardSerializer(allow_null=True)
    auto = serializers.BooleanField()
    ignored = serializers.BooleanField()
    created_at = serializers.DateTimeField()

    class Meta:
        ref_name = "FaceIdLink"


class StatusDeviceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    branch = BranchRefSerializer()
    status = serializers.ChoiceField(choices=STATUSES)
    last_event_at = serializers.DateTimeField(allow_null=True)
    scans_today = serializers.IntegerField()

    class Meta:
        ref_name = "FaceIdStatusDevice"


class StatusSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    online = serializers.IntegerField()
    quiet = serializers.IntegerField()
    never = serializers.IntegerField()
    unlinked = serializers.IntegerField(allow_null=True)
    devices = StatusDeviceSerializer(many=True)

    class Meta:
        ref_name = "FaceIdStatus"
