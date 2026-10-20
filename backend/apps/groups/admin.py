from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.groups.forms import TelegramGroupForm
from apps.groups.models import GroupReport, TelegramGroup


class TelegramGroupInline(TabularInline):
    """The company's groups. They are linked from Telegram, so none are added here."""

    model = TelegramGroup
    form = TelegramGroupForm
    extra = 0
    fields = ("title", "chat_id", "events", "is_active")
    readonly_fields = ("title", "chat_id")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TelegramGroup)
class TelegramGroupAdmin(ModelAdmin):
    form = TelegramGroupForm
    list_display = ("__str__", "company", "chat_id", "is_active", "linked_by")
    list_filter = ("company", "is_active")
    search_fields = ("title", "company__name")
    list_select_related = ("company", "linked_by__user")
    readonly_fields = ("chat_id", "linked_by", "created_at", "updated_at")


@admin.register(GroupReport)
class GroupReportAdmin(ModelAdmin):
    list_display = ("group", "kind", "day", "sent_at")
    list_filter = ("kind",)
    list_select_related = ("group",)

    def has_add_permission(self, request):
        return False
