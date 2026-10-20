from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.reminders.models import ReminderLog, ReminderPolicy, ReminderText


class ReminderTextInline(TabularInline):
    model = ReminderText
    extra = 0


@admin.register(ReminderPolicy)
class ReminderPolicyAdmin(ModelAdmin):
    list_display = (
        "name",
        "company",
        "is_default",
        "repeat_every_minutes",
        "escalate_after",
        "quiet_from",
        "quiet_until",
    )
    list_filter = ("company", "is_default")
    search_fields = ("name", "company__name")
    list_select_related = ("company",)
    inlines = (ReminderTextInline,)


@admin.register(ReminderLog)
class ReminderLogAdmin(ModelAdmin):
    list_display = ("task", "kind", "step", "recipient", "delivered", "error", "sent_at")
    list_filter = ("kind", "delivered")
    search_fields = ("task__title",)
    list_select_related = ("task", "recipient__user")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
