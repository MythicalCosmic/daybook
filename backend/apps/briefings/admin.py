"""Django admin for briefings: read-only, for support (what a company's reviews said and to
whom they went)."""

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.briefings.models import Briefing, BriefingDelivery, BriefingSettings


class ReadOnly(ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BriefingSettings)
class BriefingSettingsAdmin(ReadOnly):
    list_display = ("company", "weekly_enabled", "monthly_enabled", "weekday", "send_at")
    list_filter = ("weekly_enabled", "monthly_enabled", "recipients")


class DeliveryInline(TabularInline):
    model = BriefingDelivery
    extra = 0
    can_delete = False
    readonly_fields = ("membership", "via", "sent_at", "opened_at")
    fields = readonly_fields


@admin.register(Briefing)
class BriefingAdmin(ReadOnly):
    list_display = ("company", "kind", "day", "language", "written_by", "written_at")
    list_filter = ("kind", "written_by", "language")
    readonly_fields = (
        "company",
        "kind",
        "day",
        "language",
        "domains",
        "branch_ids",
        "scope_key",
        "written_by",
        "model",
        "written_at",
        "content",
        "facts",
    )
    inlines = (DeliveryInline,)
