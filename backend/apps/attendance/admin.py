"""Django admin for attendance: read-mostly views for platform support. Owners and managers
work in the dashboard, where every change is audited."""

from django.contrib import admin

from apps.attendance.models import (
    AttendanceCorrection,
    AttendanceRecord,
    AttendanceSettings,
    MemberSchedule,
    ShiftSwap,
    ShiftTemplate,
    WorkSchedule,
    WorkScheduleDay,
    WorkShift,
)


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "require_location",
        "require_photo",
        "outside_action",
        "grace_minutes",
    )
    list_select_related = ("company",)


class WorkScheduleDayInline(admin.TabularInline):
    model = WorkScheduleDay
    extra = 0


@admin.register(WorkSchedule)
class WorkScheduleAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "kind", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "company__name")
    inlines = [WorkScheduleDayInline]


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "starts_at", "ends_at", "is_active")
    list_filter = ("is_active",)


@admin.register(MemberSchedule)
class MemberScheduleAdmin(admin.ModelAdmin):
    list_display = ("membership", "schedule", "effective_from", "company")
    list_select_related = ("membership", "schedule", "company")
    raw_id_fields = ("membership", "schedule")


@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "membership",
        "starts_at",
        "ends_at",
        "branch",
        "status",
        "source",
        "published_at",
    )
    list_filter = ("status", "source", "company")
    list_select_related = ("membership", "branch")
    date_hierarchy = "date"
    raw_id_fields = ("membership", "branch", "position", "time_off", "created_by")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "membership",
        "status",
        "check_in_at",
        "check_out_at",
        "is_late",
        "worked_minutes",
    )
    list_filter = ("status", "is_late", "overtime_status", "company")
    list_select_related = ("membership", "branch")
    date_hierarchy = "date"
    raw_id_fields = ("membership", "shift", "branch", "edited_by")
    readonly_fields = ("in_photo",)


@admin.register(AttendanceCorrection)
class AttendanceCorrectionAdmin(admin.ModelAdmin):
    list_display = ("date", "membership", "status", "check_in_at", "check_out_at", "decided_at")
    list_filter = ("status",)
    raw_id_fields = ("membership", "record", "decided_by")


@admin.register(ShiftSwap)
class ShiftSwapAdmin(admin.ModelAdmin):
    list_display = ("shift", "kind", "status", "requested_by", "accepted_by", "expires_at")
    list_filter = ("kind", "status")
    raw_id_fields = ("shift", "other_shift", "requested_by", "target", "accepted_by", "decided_by")
