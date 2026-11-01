"""Django admin for the AI features: each company's switch, block and spend (§8.6)."""

from django.contrib import admin
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.ai import availability
from apps.ai.models import AIDraft, AISettings, AIUsage


@admin.register(AISettings)
class AISettingsAdmin(ModelAdmin):
    list_display = (
        "company",
        "enabled",
        "platform_blocked",
        "monthly_budget_usd",
        "spent_this_month",
    )
    list_filter = ("enabled", "platform_blocked")
    list_editable = ("platform_blocked",)
    search_fields = ("company__name",)
    readonly_fields = ("enabled", "enabled_by", "enabled_at", "spent_this_month")
    fields = (
        "company",
        "enabled",
        "enabled_by",
        "enabled_at",
        "platform_blocked",
        "monthly_budget_usd",
        "spent_this_month",
        "share_task_text",
        "share_finance",
        "share_salaries",
        "voice_retention_days",
        "member_daily_drafts",
    )

    @admin.display(description=_("Spent this month (USD)"))
    def spent_this_month(self, row: AISettings) -> str:
        return f"{availability.to_usd(availability.month_spend_micro(row.company)):.2f}"


@admin.register(AIUsage)
class AIUsageAdmin(ModelAdmin):
    list_display = (
        "created_at",
        "company",
        "feature",
        "model",
        "cost",
        "latency_ms",
        "stop_reason",
    )
    list_filter = ("feature", "model", "stop_reason")
    search_fields = ("company__name", "request_id")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Cost (USD)"))
    def cost(self, row: AIUsage) -> str:
        return f"{row.cost_micro_usd / 1_000_000:.4f}"

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            rows = response.context_data["cl"].queryset
        except AttributeError, KeyError:
            return response
        total = rows.aggregate(total=Sum("cost_micro_usd"))["total"] or 0
        response.context_data["title"] = _("AI usage: %(usd)s USD") % {
            "usd": f"{total / 1_000_000:.2f}"
        }
        return response


@admin.register(AIDraft)
class AIDraftAdmin(ModelAdmin):
    """Metadata only: what was said stays with the company."""

    list_display = ("created_at", "company", "source", "status", "engine", "audio_seconds")
    list_filter = ("status", "source", "engine")
    search_fields = ("company__name",)
    fields = (
        "company",
        "source",
        "status",
        "engine",
        "audio_seconds",
        "error_code",
        "applied_at",
        "started_at",
        "transcribed_at",
        "finished_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
