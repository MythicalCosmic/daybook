from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.audit.admin import AuditedAdmin
from apps.core.exceptions import DomainError
from apps.members import services
from apps.members.forms import AccessRoleForm
from apps.members.models import AccessRole, Membership, Position


@admin.register(AccessRole)
class AccessRoleAdmin(AuditedAdmin, ModelAdmin):
    form = AccessRoleForm
    list_display = ("name", "company", "is_owner", "is_default", "permission_count")
    list_filter = ("company", "is_owner", "is_default")
    search_fields = ("name", "company__name")
    list_select_related = ("company",)
    fields = ("company", "name", "permissions", "is_owner", "is_default")

    @admin.display(description=_("Permissions"))
    def permission_count(self, obj):
        return _("All") if obj.is_owner else len(obj.permissions)


@admin.register(Position)
class PositionAdmin(AuditedAdmin, ModelAdmin):
    list_display = ("name", "company", "order", "is_active")
    list_filter = ("company", "is_active")
    search_fields = ("name", "company__name")
    list_select_related = ("company",)


@admin.register(Membership)
class MembershipAdmin(AuditedAdmin, ModelAdmin):
    list_display = ("__str__", "company", "status", "position", "role", "phone", "created_at")
    list_filter = ("status", "company")
    search_fields = (
        "first_name",
        "last_name",
        "user__phone",
        "user__first_name",
        "user__last_name",
        "user__telegram_username",
    )
    list_select_related = ("company", "user", "position", "role")
    fields = (
        "company",
        "user",
        "status",
        "first_name",
        "last_name",
        "phone",
        "position",
        "role",
        "decided_by",
        "decided_at",
        "onboarded_at",
        "created_at",
        "updated_at",
    )
    actions = ("approve_selected", "reject_selected", "block_selected")

    def get_readonly_fields(self, request, obj=None):
        readonly = ["phone", "decided_by", "decided_at", "onboarded_at", "created_at", "updated_at"]
        if obj is not None:
            # Status only changes through the actions, which run the permission checks.
            readonly += ["company", "user", "status"]
        return readonly

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            for name in ("role", "position"):
                field = form.base_fields.get(name)
                if field is not None:
                    field.queryset = field.queryset.filter(company=obj.company_id)
        return form

    @admin.display(description=_("Phone"))
    def phone(self, obj):
        return obj.user.phone if obj.user_id else ""

    @admin.action(description=_("Approve selected requests"))
    def approve_selected(self, request, queryset):
        self._apply(request, queryset, services.approve, _("Approved: %(count)d"))

    @admin.action(description=_("Reject selected requests"))
    def reject_selected(self, request, queryset):
        self._apply(request, queryset, services.reject, _("Rejected: %(count)d"))

    @admin.action(description=_("Block selected members"))
    def block_selected(self, request, queryset):
        self._apply(request, queryset, services.block, _("Blocked: %(count)d"))

    def _apply(self, request, queryset, service, success_message):
        count = 0
        for membership in queryset:
            try:
                service(membership, by=request.user)
            except (DomainError, PermissionDenied) as exc:
                self.message_user(request, f"{membership}: {exc}", messages.WARNING)
            else:
                count += 1
        if count:
            self.message_user(request, success_message % {"count": count}, messages.SUCCESS)
