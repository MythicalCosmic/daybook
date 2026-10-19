from django.contrib import admin
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from apps.companies.models import Company
from apps.members.forms import AccessRoleForm
from apps.members.models import AccessRole, Membership, Position
from apps.members.services import create_default_roles


class PositionInline(TabularInline):
    model = Position
    extra = 0
    fields = ("name", "order", "is_active")


class AccessRoleInline(StackedInline):
    model = AccessRole
    form = AccessRoleForm
    extra = 0
    fields = ("name", "permissions", "is_owner", "is_default")


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = ("name", "slug", "timezone", "default_language", "member_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    fields = (
        "name",
        "slug",
        "timezone",
        "default_language",
        "is_active",
        "invite_code",
        "invite_link_display",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("invite_code", "invite_link_display", "created_at", "updated_at")
    actions = ("regenerate_invite_codes",)

    def get_queryset(self, request):
        approved = Q(memberships__status=Membership.Status.APPROVED)
        return super().get_queryset(request).annotate(member_count=Count("memberships", approved))

    def get_inlines(self, request, obj):
        # Default roles are created when the company is saved, so editing starts on the change page.
        return [PositionInline, AccessRoleInline] if obj else []

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            create_default_roles(obj)

    def has_delete_permission(self, request, obj=None):
        # Companies are deactivated, never deleted: their data must not cascade away.
        return False

    @admin.display(description=_("Members"), ordering="member_count")
    def member_count(self, obj):
        return obj.member_count

    @admin.display(description=_("Invite link"))
    def invite_link_display(self, obj):
        return obj.invite_link or _("Set EMPLOYEE_BOT_USERNAME to build the link")

    @admin.action(description=_("Regenerate invite links"))
    def regenerate_invite_codes(self, request, queryset):
        for company in queryset:
            company.regenerate_invite_code()
        self.message_user(request, _("Invite links regenerated. Old links no longer work."))
