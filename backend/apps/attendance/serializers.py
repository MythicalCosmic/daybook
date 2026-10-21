"""Serializers of the attendance endpoints.

Inputs are validated here; most outputs are the plain dicts `queries` builds
(`shift_payload`, `record_payload`, `day_board`…). The output serializers below describe
those dicts for the OpenAPI schema, so the dashboard's and the mini app's hand-written types
can be checked against them at integration.

Times without an offset ("2026-10-21T09:00") are read in the company's timezone.
"""

import zoneinfo

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSettings,
    ShiftSwap,
    ShiftTemplate,
    WorkSchedule,
    WorkShift,
)
from apps.attendance.services import BULK_ACTIONS, SETTINGS_FIELDS


class LocalDateTimeField(serializers.DateTimeField):
    """An instant; without an offset it is read in the company's timezone."""

    def enforce_timezone(self, value):
        company = self.context.get("company")
        if timezone.is_naive(value) and company is not None:
            return timezone.make_aware(value, zoneinfo.ZoneInfo(company.timezone))
        return super().enforce_timezone(value)


# Settings -------------------------------------------------------------------------------


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = "AttendanceSettings"
        model = AttendanceSettings
        fields = SETTINGS_FIELDS


# Shared shapes --------------------------------------------------------------------------


class RefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()

    class Meta:
        ref_name = "AttendanceRef"


class BranchRefSerializer(RefSerializer):
    code = serializers.CharField()

    class Meta:
        ref_name = "AttendanceBranchRef"


class BranchGeoSerializer(BranchRefSerializer):
    latitude = serializers.CharField(allow_null=True)
    longitude = serializers.CharField(allow_null=True)
    geofence_m = serializers.IntegerField()

    class Meta:
        ref_name = "BranchGeo"


class PersonCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    photo_url = serializers.CharField(allow_null=True)
    position = RefSerializer(allow_null=True)
    home_branch = RefSerializer(allow_null=True)
    status = serializers.CharField()


class ShiftOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member_id = serializers.IntegerField(allow_null=True)
    date = serializers.DateField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    start = serializers.CharField(help_text=_("Local start time, HH:MM."))
    end = serializers.CharField(help_text=_("Local end time, HH:MM."))
    break_minutes = serializers.IntegerField()
    minutes = serializers.IntegerField(help_text=_("Planned working minutes, the break left out."))
    branch = BranchRefSerializer(allow_null=True)
    position = RefSerializer(allow_null=True)
    status = serializers.ChoiceField(choices=WorkShift.Status.choices)
    source = serializers.ChoiceField(choices=WorkShift.Source.choices)
    published = serializers.BooleanField()
    note = serializers.CharField()
    time_off_id = serializers.IntegerField(allow_null=True)
    swap_pending = serializers.BooleanField()
    has_record = serializers.BooleanField()


class RecordOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member_id = serializers.IntegerField()
    shift_id = serializers.IntegerField(allow_null=True)
    date = serializers.DateField()
    status = serializers.ChoiceField(choices=AttendanceRecord.Status.choices)
    check_in_at = serializers.DateTimeField(allow_null=True)
    check_out_at = serializers.DateTimeField(allow_null=True)
    in_lat = serializers.CharField(allow_null=True)
    in_lng = serializers.CharField(allow_null=True)
    in_accuracy_m = serializers.IntegerField(allow_null=True)
    in_distance_m = serializers.IntegerField(allow_null=True)
    out_lat = serializers.CharField(allow_null=True)
    out_lng = serializers.CharField(allow_null=True)
    out_accuracy_m = serializers.IntegerField(allow_null=True)
    out_distance_m = serializers.IntegerField(allow_null=True)
    branch = BranchRefSerializer(allow_null=True)
    in_source = serializers.CharField()
    out_source = serializers.CharField()
    late_minutes = serializers.IntegerField()
    early_leave_minutes = serializers.IntegerField()
    worked_minutes = serializers.IntegerField()
    overtime_minutes = serializers.IntegerField()
    overtime_status = serializers.ChoiceField(choices=AttendanceRecord.Overtime.choices)
    is_late = serializers.BooleanField()
    flags = serializers.ListField(
        child=serializers.ChoiceField(choices=AttendanceRecord.Flag.choices)
    )
    note = serializers.CharField()
    has_photo = serializers.BooleanField()


class RecordRowSerializer(RecordOutSerializer):
    member = PersonCardSerializer()
    shift = ShiftOutSerializer(allow_null=True)


class RecordDetailSerializer(RecordRowSerializer):
    photo_url = serializers.CharField(allow_null=True)
    edited_by = serializers.CharField(allow_null=True)
    branch_geo = BranchGeoSerializer(allow_null=True)


# The board ------------------------------------------------------------------------------


class BoardRowSerializer(serializers.Serializer):
    member = PersonCardSerializer()
    branch = BranchRefSerializer(allow_null=True)
    state = serializers.ChoiceField(choices=["in", "late", "not_yet", "absent", "off"])
    reason = serializers.CharField(
        allow_null=True,
        help_text=_(
            "Why: late (not here yet), leave, day_off, holiday, suspended, no_shift, excused."
        ),
    )
    shift = ShiftOutSerializer(allow_null=True)
    record = RecordOutSerializer(allow_null=True)


class BoardBranchSerializer(BranchGeoSerializer):
    rostered = serializers.IntegerField()
    checked_in = serializers.IntegerField()
    first_check_in = serializers.DateTimeField(allow_null=True)

    class Meta:
        ref_name = "BoardBranch"


class BoardSerializer(serializers.Serializer):
    date = serializers.DateField()
    is_today = serializers.BooleanField()
    now = serializers.DateTimeField()
    holiday = serializers.CharField(allow_null=True)
    totals = serializers.DictField(child=serializers.IntegerField())
    branches = BoardBranchSerializer(many=True)
    people = BoardRowSerializer(many=True)


# Timesheet, summary, roster ---------------------------------------------------------------


class CellSerializer(serializers.Serializer):
    code = serializers.ChoiceField(
        choices=[
            "present",
            "late",
            "absent",
            "leave",
            "off",
            "holiday",
            "excused",
            "open",
            "auto",
            "planned",
            "unscheduled",
        ]
    )
    minutes = serializers.IntegerField()
    late = serializers.IntegerField()
    record_id = serializers.IntegerField(allow_null=True)
    shift_id = serializers.IntegerField(allow_null=True)
    flags = serializers.ListField(child=serializers.CharField())


class PeriodSerializer(serializers.Serializer):
    scheduled_days = serializers.IntegerField()
    attended_days = serializers.IntegerField()
    leave_days = serializers.IntegerField()
    leave_time_off_ids = serializers.ListField(child=serializers.IntegerField())
    absent_days = serializers.IntegerField()
    worked_minutes = serializers.IntegerField()
    approved_overtime_minutes = serializers.IntegerField()
    late_arrivals = serializers.IntegerField()
    late_minutes = serializers.IntegerField()
    holiday_worked_days = serializers.IntegerField()
    has_schedule = serializers.BooleanField()
    overtime_minutes = serializers.IntegerField(required=False)


class TimesheetRowSerializer(serializers.Serializer):
    member = PersonCardSerializer()
    totals = PeriodSerializer()
    cells = serializers.DictField(child=CellSerializer())


class TimesheetSerializer(serializers.Serializer):
    month = serializers.CharField()
    days = serializers.ListField(child=serializers.DateField())
    today = serializers.DateField()
    holidays = serializers.DictField(child=serializers.CharField())
    people = TimesheetRowSerializer(many=True)


class SummarySerializer(serializers.Serializer):
    range = serializers.DictField(child=serializers.DateField())
    compare = serializers.DictField(child=serializers.DateField(), allow_null=True)
    currency = serializers.CharField()
    totals = serializers.DictField()
    previous = serializers.DictField(allow_null=True)
    series = serializers.ListField(child=serializers.DictField())
    breakdown = serializers.ListField(child=serializers.DictField())


class RosterMemberSerializer(PersonCardSerializer):
    schedule = RefSerializer(allow_null=True)
    minutes = serializers.IntegerField()
    leave = serializers.ListField(child=serializers.DateField())


class RosterSerializer(serializers.Serializer):
    week = serializers.DateField()
    days = serializers.ListField(child=serializers.DateField())
    holidays = serializers.DictField(child=serializers.CharField())
    members = RosterMemberSerializer(many=True)
    shifts = ShiftOutSerializer(many=True)
    unpublished = serializers.IntegerField()
    coverage = serializers.DictField(child=serializers.DictField(child=serializers.IntegerField()))


# Writes: records ------------------------------------------------------------------------


class RecordEditSerializer(serializers.Serializer):
    check_in_at = LocalDateTimeField(required=False, allow_null=True)
    check_out_at = LocalDateTimeField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)
    reason = serializers.CharField(max_length=300)


class RecordCreateSerializer(serializers.Serializer):
    member_id = serializers.IntegerField()
    date = serializers.DateField()
    check_in_at = LocalDateTimeField()
    check_out_at = LocalDateTimeField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")
    reason = serializers.CharField(max_length=300)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)

    class Meta:
        ref_name = "AttendanceReason"


class DecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class OptionalReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


# Writes: schedules, templates, shifts ----------------------------------------------------


class ScheduleDaySerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    starts_at = serializers.TimeField(format="%H:%M")
    ends_at = serializers.TimeField(format="%H:%M")
    break_minutes = serializers.IntegerField(min_value=0, max_value=480, default=60)


class ScheduleSerializer(serializers.ModelSerializer):
    days = ScheduleDaySerializer(many=True, required=False)
    rotation_starts_at = serializers.TimeField(format="%H:%M", required=False, allow_null=True)
    rotation_ends_at = serializers.TimeField(format="%H:%M", required=False, allow_null=True)
    member_ids = serializers.SerializerMethodField()
    weekly_minutes = serializers.SerializerMethodField()

    class Meta:
        model = WorkSchedule
        fields = (
            "id",
            "name",
            "kind",
            "color",
            "days",
            "rotation",
            "rotation_start",
            "rotation_starts_at",
            "rotation_ends_at",
            "rotation_break_minutes",
            "is_active",
            "member_ids",
            "weekly_minutes",
        )
        read_only_fields = ("id", "is_active", "member_ids", "weekly_minutes")

    def get_member_ids(self, schedule) -> list[int]:
        return self.context.get("assignments", {}).get(schedule.pk, [])

    def get_weekly_minutes(self, schedule) -> int:
        from apps.attendance.rules import weekly_minutes

        return weekly_minutes(schedule)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["days"] = ScheduleDaySerializer(instance.days.all(), many=True).data
        return data


class AssignSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, max_length=500
    )
    effective_from = serializers.DateField(required=False, allow_null=True)


class UnassignSerializer(serializers.Serializer):
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, max_length=500
    )


class TemplateSerializer(serializers.ModelSerializer):
    starts_at = serializers.TimeField(format="%H:%M")
    ends_at = serializers.TimeField(format="%H:%M")
    position_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = ShiftTemplate
        fields = (
            "id",
            "name",
            "starts_at",
            "ends_at",
            "break_minutes",
            "color",
            "position_id",
            "order",
            "is_active",
        )
        read_only_fields = ("id", "is_active")


class ShiftWriteSerializer(serializers.Serializer):
    member_id = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField()
    start = serializers.TimeField()
    end = serializers.TimeField()
    break_minutes = serializers.IntegerField(min_value=0, max_value=480, default=60)
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    publish = serializers.BooleanField(required=False, default=False)


class ShiftPatchSerializer(serializers.Serializer):
    member_id = serializers.IntegerField(required=False, allow_null=True)
    date = serializers.DateField(required=False)
    start = serializers.TimeField(required=False)
    end = serializers.TimeField(required=False)
    break_minutes = serializers.IntegerField(min_value=0, max_value=480, required=False)
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    position_id = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class BulkSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=BULK_ACTIONS)
    week = serializers.DateField(help_text=_("Any day of the week; it starts on Monday."))
    branch_id = serializers.IntegerField(required=False, allow_null=True)
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )

    class Meta:
        ref_name = "AttendanceBulk"


class PublishSerializer(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    branch_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        ref_name = "AttendancePublish"

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            raise serializers.ValidationError({"end": _("The last day can't be before the first.")})
        if (attrs["end"] - attrs["start"]).days > 62:
            raise serializers.ValidationError({"end": _("Publish at most two months at once.")})
        return attrs


class CountSerializer(serializers.Serializer):
    count = serializers.IntegerField()

    class Meta:
        ref_name = "AttendanceCount"


# Swaps and corrections ------------------------------------------------------------------


class SwapOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=ShiftSwap.Kind.choices)
    status = serializers.ChoiceField(choices=ShiftSwap.Status.choices)
    shift = ShiftOutSerializer()
    other_shift = ShiftOutSerializer(allow_null=True)
    requested_by = RefSerializer()
    target = RefSerializer(allow_null=True)
    accepted_by = RefSerializer(allow_null=True)
    note = serializers.CharField()
    decision_note = serializers.CharField()
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    decided_at = serializers.DateTimeField(allow_null=True)


class CorrectionOutSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    member = PersonCardSerializer()
    date = serializers.DateField()
    check_in_at = serializers.DateTimeField(allow_null=True)
    check_out_at = serializers.DateTimeField(allow_null=True)
    reason = serializers.CharField()
    status = serializers.ChoiceField(choices=AttendanceCorrection.Status.choices)
    decision_note = serializers.CharField()
    record = RecordOutSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    decided_at = serializers.DateTimeField(allow_null=True)


# The employee side ----------------------------------------------------------------------


class CheckInSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=11, decimal_places=7, required=False, allow_null=True)
    accuracy = serializers.FloatField(required=False, allow_null=True, min_value=0)
    photo = serializers.FileField(required=False, allow_null=True)


class CheckOutSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=11, decimal_places=7, required=False, allow_null=True)
    accuracy = serializers.FloatField(required=False, allow_null=True, min_value=0)


class MyDaySerializer(serializers.Serializer):
    now = serializers.DateTimeField()
    date = serializers.DateField()
    state = serializers.ChoiceField(choices=["off", "upcoming", "due", "late", "in", "done"])
    settings = serializers.DictField()
    shift = ShiftOutSerializer(allow_null=True)
    branch = BranchGeoSerializer(allow_null=True)
    record = RecordOutSerializer(allow_null=True)
    next_shift = ShiftOutSerializer(allow_null=True)
    open_shifts = serializers.IntegerField()
    requests = serializers.IntegerField()


class CheckResultSerializer(serializers.Serializer):
    record = RecordOutSerializer()
    created = serializers.BooleanField()
    outside = serializers.BooleanField()
    distance_m = serializers.IntegerField(allow_null=True)


class MyMonthSerializer(serializers.Serializer):
    month = serializers.CharField()
    days = serializers.ListField(child=serializers.DateField())
    today = serializers.DateField()
    holidays = serializers.DictField(child=serializers.CharField())
    cells = serializers.DictField(child=CellSerializer())
    totals = PeriodSerializer()


class CorrectionRequestSerializer(serializers.Serializer):
    date = serializers.DateField()
    check_in_at = LocalDateTimeField(required=False, allow_null=True)
    check_out_at = LocalDateTimeField(required=False, allow_null=True)
    record_id = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=300)


class SwapRequestSerializer(serializers.Serializer):
    shift_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=[ShiftSwap.Kind.COVER, ShiftSwap.Kind.SWAP])
    other_shift_id = serializers.IntegerField(required=False, allow_null=True)
    target_id = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class MySwapsSerializer(serializers.Serializer):
    mine = SwapOutSerializer(many=True)
    requests = SwapOutSerializer(many=True)


class CandidateSerializer(serializers.Serializer):
    member = PersonCardSerializer()
    shifts = ShiftOutSerializer(many=True, help_text=_("Their coming shifts you could swap for."))


class OpenShiftSerializer(ShiftOutSerializer):
    claimed = serializers.BooleanField()
