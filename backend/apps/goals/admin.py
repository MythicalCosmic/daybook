"""Django admin for business goals: read mostly; the values are computed, never typed."""

from django.contrib import admin

from apps.goals.models import Goal, GoalPoint


class PointInline(admin.TabularInline):
    model = GoalPoint
    extra = 0
    readonly_fields = ("on", "value", "forecast", "state")
    can_delete = False


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "metric", "target", "ends_on", "status", "state")
    list_filter = ("status", "state", "metric")
    search_fields = ("title",)
    readonly_fields = (
        "value",
        "forecast",
        "baseline",
        "progress",
        "state",
        "computed_at",
        "notified_state",
    )
    inlines = (PointInline,)
