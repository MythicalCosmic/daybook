"""Django admin for exports: read-only, for support."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.exports.models import Export


@admin.register(Export)
class ExportAdmin(ModelAdmin):
    list_display = ("kind", "format", "status", "rows", "requested_by", "company", "created_at")
    list_filter = ("status", "format", "sensitive")
    search_fields = ("kind", "requested_by__first_name", "requested_by__last_name")
    list_select_related = ("requested_by", "company")
    exclude = ("file",)  # private: downloads only through signed, re-checked links

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
