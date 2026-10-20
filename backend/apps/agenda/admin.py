"""Django admin for the company calendar."""

from django.contrib import admin

from apps.agenda.models import Event, EventAttendee


class AttendeeInline(admin.TabularInline):
    model = EventAttendee
    extra = 0
    raw_id_fields = ("membership",)
    readonly_fields = ("responded_at", "reminded_for")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "kind", "start", "all_day", "repeat", "cancelled_at")
    list_filter = ("kind", "all_day", "repeat")
    search_fields = ("title", "place", "company__name")
    raw_id_fields = ("branch", "created_by")
    inlines = [AttendeeInline]
