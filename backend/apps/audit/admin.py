from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.companies.models import Company


class AuditedAdmin:
    """Mixin for ModelAdmins: what's saved or deleted in the admin lands in the audit log."""

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and not form.changed_data:
            return  # saved without changes
        action = AuditLog.Action.ADMIN_CHANGED if change else AuditLog.Action.ADMIN_CREATED
        _record(action, request, obj, fields=sorted(form.changed_data))

    def delete_model(self, request, obj):
        _record(AuditLog.Action.ADMIN_DELETED, request, obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            _record(AuditLog.Action.ADMIN_DELETED, request, obj)
        super().delete_queryset(request, queryset)


def _record(action, request, obj, **details) -> None:
    company_id = obj.pk if isinstance(obj, Company) else obj.company_id
    audit.record(action, company_id=company_id, actor=request.user, target=obj, **details)


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ("created_at", "company", "actor", "action", "target")
    list_filter = ("company", "action")
    search_fields = ("target", "actor__first_name", "actor__last_name", "actor__username")
    list_select_related = ("company", "actor")
    date_hierarchy = "created_at"
    readonly_fields = (
        "created_at",
        "company",
        "actor",
        "action",
        "target_type",
        "target_id",
        "target",
        "details",
    )
    fields = readonly_fields

    # The log is a record of the past: nobody adds to, edits or deletes it by hand.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
