from django import forms
from django.contrib import admin
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from apps.audit.admin import AuditedAdmin
from apps.companies.models import Branch, Company
from apps.companies.services import setup_company
from apps.core import uploads
from apps.groups.admin import TelegramGroupInline
from apps.members.forms import AccessRoleForm
from apps.members.models import AccessRole, Membership, Position
from apps.timeoff.admin import HolidayInline


class PositionInline(TabularInline):
    model = Position
    extra = 0
    fields = ("name", "order", "is_active")


class AccessRoleInline(StackedInline):
    model = AccessRole
    form = AccessRoleForm
    extra = 0
    fields = ("name", "permissions", "is_owner", "is_default")


class BranchInline(TabularInline):
    model = Branch
    extra = 0
    fields = ("name", "code", "address", "opens_at", "closes_at", "is_active", "order")
    show_change_link = True

    def has_delete_permission(self, request, obj=None):
        return False  # branches are deactivated; tasks and money keep pointing at them


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ("logo",)  # the admin adds its own `fields`; this form only cleans the logo

    def clean_logo(self):
        """Logos are re-encoded like every other uploaded picture."""
        logo = self.cleaned_data.get("logo")
        if isinstance(logo, UploadedFile):
            try:
                return uploads.sanitize_image(logo, max_side=1024)
            except uploads.InvalidUpload as exc:
                raise forms.ValidationError(str(exc)) from exc
        return logo


@admin.register(Company)
class CompanyAdmin(AuditedAdmin, ModelAdmin):
    form = CompanyForm
    list_display = ("name", "slug", "timezone", "default_language", "member_count", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    fields = (
        "name",
        "slug",
        "timezone",
        "default_language",
        "base_currency",
        "logo",
        "features",
        "workdays",
        "rejoin_cooldown_hours",
        "morning_report_at",
        "evening_report_at",
        "morning_digest",
        "owner_sees_personal_tasks",
        "team_directory_phones",
        "is_active",
        "invite_code",
        "invite_link_display",
        "setup_completed_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = (
        "invite_code",
        "invite_link_display",
        "setup_completed_at",
        "created_at",
        "updated_at",
    )
    actions = ("regenerate_invite_codes",)

    def get_queryset(self, request):
        approved = Q(memberships__status=Membership.Status.APPROVED)
        return super().get_queryset(request).annotate(member_count=Count("memberships", approved))

    def get_inlines(self, request, obj):
        # Default roles and the first branch are created when the company is saved, so editing
        # starts on the change page.
        if obj is None:
            return []
        return [BranchInline, PositionInline, AccessRoleInline, HolidayInline, TelegramGroupInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            # The same start as a company created in the owner bot; `by` is no member here.
            setup_company(obj, None)

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


@admin.register(Branch)
class BranchAdmin(AuditedAdmin, ModelAdmin):
    list_display = ("name", "company", "code", "opens_at", "closes_at", "is_active", "order")
    list_filter = ("is_active", "company")
    search_fields = ("name", "code", "company__name", "address")
    list_select_related = ("company",)
    raw_id_fields = ("manager",)
    fields = (
        "company",
        "name",
        "code",
        "address",
        "phone",
        ("latitude", "longitude"),
        "geofence_m",
        ("opens_at", "closes_at"),
        "open_weekdays",
        "manager",
        "cash_limit",
        "is_active",
        "order",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        # A branch never moves to another company: its tasks and money would go with it.
        return (*self.readonly_fields, "company") if obj else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead
