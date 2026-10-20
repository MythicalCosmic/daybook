"""Django admin for the inbox: notifications, read-only, for support."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.inbox.models import Notification


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ("kind", "title", "recipient", "company", "created_at", "read_at", "acted_at")
    list_filter = ("severity", "in_app", "kind")
    search_fields = ("title", "kind", "recipient__first_name", "recipient__last_name")
    list_select_related = ("recipient", "company")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
