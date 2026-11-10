"""Django admin for insights: read-only lists, for support."""

from django.contrib import admin

from apps.insights.models import Insight, InsightSettings


@admin.register(Insight)
class InsightAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "kind", "severity", "status", "branch", "detected_at")
    list_filter = ("kind", "severity", "status")
    search_fields = ("title", "dedupe_key", "company__name")
    readonly_fields = [field.name for field in Insight._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(InsightSettings)
class InsightSettingsAdmin(admin.ModelAdmin):
    list_display = ("company", "sensitivity", "notify_critical_via_bot", "last_run_at")
    raw_id_fields = ("company",)
