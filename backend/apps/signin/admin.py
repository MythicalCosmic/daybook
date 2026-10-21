"""Django admin for owner sign-in.

- Device sessions: read-only; the action ends them.
- Login links: read-only, for looking into a strange sign-in.
- Signup codes: a platform admin makes one here (or with `manage.py signup_code`) and sees it
  once; only its hash is kept.
"""

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from apps.signin import services, signup
from apps.signin.models import DeviceSession, LoginLink, SignupCode


@admin.register(DeviceSession)
class DeviceSessionAdmin(ModelAdmin):
    list_display = ("user", "user_agent", "ip", "created_at", "last_seen_at", "revoked_at")
    list_filter = ("revoked_at",)
    search_fields = ("user__username", "user__first_name", "user__last_name", "ip")
    readonly_fields = (
        "user",
        "refresh_jti",
        "previous_jti",
        "rotated_at",
        "user_agent",
        "ip",
        "created_at",
        "last_seen_at",
        "revoked_at",
    )
    actions = ("revoke",)

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("End the selected sessions"))
    def revoke(self, request, queryset):
        for session in queryset.filter(revoked_at__isnull=True):
            services.revoke_session(session)


@admin.register(LoginLink)
class LoginLinkAdmin(ModelAdmin):
    list_display = ("created_at", "status", "bot", "user", "ip", "user_agent", "decided_at")
    list_filter = ("status", "bot")
    search_fields = ("user__username", "user__first_name", "user__last_name", "ip")
    readonly_fields = (
        "id",
        "status",
        "bot",
        "user",
        "user_agent",
        "ip",
        "created_at",
        "expires_at",
        "decided_at",
        "consumed_at",
    )
    exclude = ("code_hash", "poll_hash", "match_code")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SignupCode)
class SignupCodeAdmin(ModelAdmin):
    list_display = ("__str__", "uses_left", "expires_at", "created_by", "created_at")
    list_filter = ("expires_at",)
    search_fields = ("note",)
    fields = ("note", "uses_left", "expires_at", "created_by", "created_at")
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        raw = signup.generate()
        while SignupCode.objects.filter(code_hash=signup.code_hash(raw)).exists():
            raw = signup.generate()
        obj.code_hash = signup.code_hash(raw)
        obj.created_by = request.user
        super().save_model(request, obj, form, change)
        messages.success(
            request,
            format_html(
                gettext("Signup code <b>{code}</b>. Copy it now: it is shown only once."),
                code=raw,
            ),
        )
